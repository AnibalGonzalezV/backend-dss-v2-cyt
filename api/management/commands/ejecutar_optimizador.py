import math
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
import pyomo.environ as pyo

from api.models import Viaje, Instalacion, ProgramaVendimia, GrupoMezcla, AsignacionGantt, InventarioBodega
from optimization.pyomo_model import build_dss_model

class Command(BaseCommand):
    help = 'Ejecuta el solver HiGHS utilizando la foto actual de la base de datos (Rolling Horizon).'

    def add_arguments(self, parser):
        parser.add_argument('--virtual-time', type=str, help='Hora virtual a inyectar (YYYY-MM-DD HH:MM:SS)')

    def handle(self, *args, **kwargs):
        self.stdout.write("Obteniendo foto actual del patio...")
        
        virtual_time = kwargs.get('virtual_time')
        if virtual_time:
            from datetime import datetime
            ahora = datetime.strptime(virtual_time, '%Y-%m-%d %H:%M:%S')
        else:
            from django.utils import timezone
            ahora = timezone.now()
            
        from datetime import timedelta
        # Auto-Desplazamiento TRANSITO
        transitos = Viaje.objects.filter(estado_actual='TRANSITO')
        for v in transitos:
            gps = v.eventogps_set.last()
            if not gps:
                continue
            
            # Normalizar ETA a naive
            eta = gps.eta_proyectado
            if eta and hasattr(eta, 'tzinfo') and eta.tzinfo is not None:
                eta = eta.replace(tzinfo=None)
                
            if eta and eta <= ahora:
                # Usar el ETA original para la alerta crítica
                original_eta_str = gps.payload_original.get('eta') if gps.payload_original else None
                if original_eta_str:
                    from dateutil.parser import parse
                    original_eta_dt = parse(original_eta_str)
                    if hasattr(original_eta_dt, 'tzinfo') and original_eta_dt.tzinfo is not None:
                        original_eta_dt = original_eta_dt.replace(tzinfo=None)
                    if ahora >= original_eta_dt + timedelta(hours=2):
                        v.estado_actual = 'ALERTA_ATRASO'
                        v.save()
                        continue
                gps.eta_proyectado = ahora + timedelta(minutes=15)
                gps.save()

        viajes_espera = Viaje.objects.filter(estado_actual__in=['ROMANA', 'PATIO', 'TRANSITO'])
        if not viajes_espera.exists():
            self.stdout.write(self.style.WARNING("El patio está vacío. No hay nada que optimizar."))
            return
            
        K = []
        K_gps = []
        w = {}
        Gk = {}
        Pk = {}
        c_espera = {}
        tmin = {}
        T_commit = 2  # 20 minutos fijos para bloquear GPS
        
        # Horizonte rodante: Solo planificamos las próximas 2 horas (T = 12 intervalos de 10 min)
        T = list(range(1, 13))
        
        for viaje in viajes_espera:
            k_id = f"V{viaje.id}"
            K.append(k_id)
            
            pesaje = None
            gps = None
            # Obtener peso según el estado
            if viaje.estado_actual == 'TRANSITO':
                gps = viaje.eventogps_set.last()
                peso = float(gps.payload_original.get('peso_estimado_kg', 15000.0)) if gps and gps.payload_original else 15000.0
                K_gps.append(k_id)
                # tmin: Intervalo donde cae el ETA
                if gps and gps.eta_proyectado > ahora:
                    minutos_espera = (gps.eta_proyectado - ahora).total_seconds() / 60.0
                    t_llegada = math.ceil(minutos_espera / 10.0) + 1
                    tmin[k_id] = max(1, min(int(t_llegada), 13))
                else:
                    tmin[k_id] = 1
            else:
                pesaje = viaje.pesajeromana_set.last()
                peso = float(pesaje.peso_neto_kg) if pesaje else 15000.0 # Por defecto
                tmin[k_id] = 1
            w[k_id] = peso
            
            # Tiempo de descarga realista (Ajuste IO): 
            # 10 min (1 int) fijo por maniobra (cuadrar, lavar) + 10 min por cada 12.500 kg.
            # Ej: Camión de 25.000 kg -> 1 + ceil(2.0) = 3 intervalos (30 min).
            Pk[k_id] = math.ceil(peso / 12500.0) + 1
            
            # Identificar grupo de mezcla (Jerarquía: Programa > Pesaje > GPS > Default)
            grupo = "GENERICO"
            if viaje.programa:
                grupo = viaje.programa.grupo_mezcla.codigo_material
            elif pesaje and pesaje.payload_original:
                grupo = pesaje.payload_original.get('grupo_informado', 'GENERICO')
            elif viaje.estado_actual == 'TRANSITO':
                gps = viaje.eventogps_set.last()
                grupo = gps.payload_original.get('grupo_informado', 'GENERICO') if gps and gps.payload_original else 'GENERICO'
            Gk[k_id] = grupo
            
            # Costo de Deterioro: Camiones que llevan más tiempo esperando tienen mayor Costo
            espera_minutos = 0
            if viaje.estado_actual == 'TRANSITO' and gps and gps.eta_proyectado:
                espera_minutos = max(0, (ahora - gps.eta_proyectado).total_seconds() / 60)
            elif pesaje and pesaje.hora_llegada_real:
                espera_minutos = max(0, (ahora - pesaje.hora_llegada_real).total_seconds() / 60)
            
            if viaje.estado_actual in ['ROMANA', 'PATIO']:
                espera_minutos += 120  # Simulamos 2 hrs extra de espera para darle máxima prioridad matemática
                
            for t in T:
                # El costo crece proporcionalmente al tiempo total que la uva pasa en el camión
                # El costo de espera debe ser NO LINEAL para forzar prioridad FIFO natural
                c_espera[(k_id, t)] = (espera_minutos + (t * 10.0)) ** 1.5

        # 2. Obtener Maquinarias Activas
        instalaciones = Instalacion.objects.filter(esta_activa=True)
        J = []
        J_pozos = []
        J_prensas = []
        J_cubas_pf = []
        J_flt = []
        J_cubas_f = []
        
        Vmin = {}
        Vmax = {}
        
        for inst in instalaciones:
            j_id = inst.nombre
            J.append(j_id)
            Vmin[j_id] = float(inst.cap_minima)
            Vmax[j_id] = float(inst.cap_maxima)
            
            # Clasificación topológica STN
            if j_id.startswith('P_'):
                J_pozos.append(j_id)
            elif j_id.startswith('PR_'):
                J_prensas.append(j_id)
            elif j_id.startswith('CubaPF_'):
                J_cubas_pf.append(j_id)
            elif j_id.startswith('FLT_'):
                J_flt.append(j_id)
            elif j_id.startswith('CubaF_'):
                J_cubas_f.append(j_id)

        # 3. Grupos de mezcla únicos
        G = list(set(Gk.values()))

        # --- HITO 5: STATE HANDOFF (TRASPASO DE ESTADO) ---
        
        # 1. TIME FENCE (Zona Congelada) & OVERRIDES MANUALES: Salvar asignaciones de corto plazo o fijadas por el usuario
        frontera_congelada = ahora + timedelta(minutes=30)
        from django.db.models import Q
        bloques_a_congelar = AsignacionGantt.objects.filter(
            viaje__estado_actual__in=['ROMANA', 'PATIO']
        ).filter(
            Q(hora_inicio__gte=ahora, hora_inicio__lt=frontera_congelada) | Q(override_manual=True)
        )
        
        frozen_assignments = []
        for b in bloques_a_congelar:
            minutos_diff = (b.hora_inicio - ahora).total_seconds() / 60.0
            t_idx = int(round(minutos_diff / 10.0)) + 1
            if 1 <= t_idx <= 12:
                frozen_assignments.append((f"V{b.viaje.id}", b.instalacion.nombre, t_idx))

        # 2. Limpiar TODA asignación de camiones que no estén descargando (excepto los fijados manualmente)
        AsignacionGantt.objects.filter(
            viaje__estado_actual__in=['ROMANA', 'PATIO', 'TRANSITO', 'ALERTA_ATRASO'],
            override_manual=False
        ).delete()
        
        bloqueo_inicial = {j: 0 for j in J_pozos}
        # Solo las descargas que están físicamente ocurriendo bloquean el pozo
        descargas_activas = AsignacionGantt.objects.filter(instalacion__tipo='POZO', hora_fin__gt=ahora, viaje__estado_actual='DESCARGANDO')
        for desc in descargas_activas:
            minutos_restantes = (desc.hora_fin - ahora).total_seconds() / 60.0
            if minutos_restantes > 0:
                t_bloqueados = math.ceil(minutos_restantes / 10.0)
                pozo_name = desc.instalacion.nombre
                if pozo_name in bloqueo_inicial:
                    bloqueo_inicial[pozo_name] = max(bloqueo_inicial[pozo_name], t_bloqueados)

        datos = {
            'frozen_assignments': frozen_assignments,
            'bloqueo_inicial': bloqueo_inicial,
            'T': T,
            'K': K,
            'K_gps': K_gps,
            'tmin': tmin,
            'T_commit': T_commit,
            'J': J,
            'J_pozos': J_pozos if J_pozos else J,
            'J_prensas': J_prensas,
            'J_cubas_pf': J_cubas_pf,
            'J_flt': J_flt,
            'J_cubas_f': J_cubas_f,
            'G': G,
            'w': w,
            'Gk': Gk,
            'Pk': Pk,
            'Vmin': Vmin,
            'Vmax': Vmax,
            'c_espera': c_espera
        }

        self.stdout.write(f"Iniciando Optimizador HiGHS: {len(K)} Camiones, {len(J)} Máquinas, {len(G)} Grupos.")
        
        # 4. Construir y Resolver
        modelo = build_dss_model(datos)
        
        try:
            solver = pyo.SolverFactory('appsi_highs')
            # Límite de tiempo estricto para asegurar agilidad operativa (60 seg)
            solver.options['time_limit'] = 60 
            
            resultados = solver.solve(modelo, tee=False)
            
            if resultados.solver.termination_condition in [pyo.TerminationCondition.optimal, pyo.TerminationCondition.maxTimeLimit, pyo.TerminationCondition.feasible] or (hasattr(resultados.solver, 'status') and str(resultados.solver.status) == 'ok'):
                obj_val = pyo.value(modelo.Z)
                self.stdout.write(self.style.SUCCESS(f"¡Solución Óptima Encontrada! (Z = {obj_val})"))
                
                                
                # Resumen de Asignaciones (Para terminal y BD)
                for k in K:
                    for j in J_pozos:
                        for t in T:
                            if pyo.value(modelo.X[k, j, t]) and pyo.value(modelo.X[k, j, t]) > 0.5:
                                hora_asignada = ahora + timedelta(minutes=(t-1)*10)
                                hora_str = hora_asignada.strftime('%H:%M')
                                peso_kg = w[k]
                                
                                if t <= 6:
                                    grupo_str = Gk[k]
                                    viaje_id = int(k[1:])
                                    viaje_obj = Viaje.objects.get(id=viaje_id)
                                    pesaje = viaje_obj.pesajeromana_set.last()
                                    espera_hrs = 0.0
                                    llegada_str = "--:--"
                                    if pesaje and pesaje.hora_llegada_real:
                                        espera_hrs = max(0, (hora_asignada - pesaje.hora_llegada_real).total_seconds() / 3600.0)
                                        llegada_str = pesaje.hora_llegada_real.strftime('%H:%M')
                                    
                                    self.stdout.write(f" - Camión {k} (Llegó {llegada_str}) asignado a {j} en el intervalo T={t} ({hora_str}) | Peso: {peso_kg:,.0f} kg | Grupo: {grupo_str} | Espera: {espera_hrs:.1f} hrs")
                                    instalacion = Instalacion.objects.get(nombre=j)
                                    
                                    AsignacionGantt.objects.create(
                                        viaje_id=viaje_id,
                                        instalacion=instalacion,
                                        hora_inicio=hora_asignada,
                                        hora_fin=hora_asignada + timedelta(minutes=Pk[k]*10)
                                    )
                                else:
                                    grupo_str = Gk[k]
                                    viaje_id = int(k[1:])
                                    viaje_obj = Viaje.objects.get(id=viaje_id)
                                    pesaje = viaje_obj.pesajeromana_set.last()
                                    espera_hrs = 0.0
                                    llegada_str = "--:--"
                                    if pesaje and pesaje.hora_llegada_real:
                                        hora_proyectada = ahora + timedelta(minutes=(t-1)*10)
                                        espera_hrs = max(0, (hora_proyectada - pesaje.hora_llegada_real).total_seconds() / 3600.0)
                                        llegada_str = pesaje.hora_llegada_real.strftime('%H:%M')
                                    
                                    self.stdout.write(self.style.WARNING(f" - (TENTATIVO) Camión {k} (Llegó {llegada_str}) proyectado a {j} en T={t} ({hora_str}) | Grupo: {grupo_str} | Espera al inicio: {espera_hrs:.1f} hrs -> Se descartará para MPC."))
                                
                # --- HITO 4: Persistencia de Flujo (Líquidos en Bodega) ---
                for j in modelo.J_lentas:
                    for g in modelo.G:
                        vol_committed = 0.0
                        for j_in in modelo.J:
                            if (j_in, j) in modelo.Arcs_fast:
                                rho = 1.0
                                if j_in in modelo.J_pozos: rho = 0.96
                                elif j_in in modelo.J_prensas: rho = 0.6536
                                elif j_in in modelo.J_flt: rho = 0.94
                                
                                for t in range(1, 7): # SOLO T=1 a 6
                                    if t in modelo.T:
                                        f_val = pyo.value(modelo.F[j_in, j, g, t])
                                        if f_val and f_val > 0.01:
                                            vol_committed += f_val * rho
                            elif (j_in, j) in modelo.Arcs_slow:
                                rho = 1.0
                                if j_in in modelo.J_prensas: rho = 0.6536
                                elif j_in in modelo.J_flt: rho = 0.94
                                
                                f_val = pyo.value(modelo.F_slow[j_in, j, g])
                                if f_val and f_val > 0.01:
                                    vol_committed += f_val * rho
                                            
                        if vol_committed >= 1.0:
                            inst = Instalacion.objects.get(nombre=j)
                            InventarioBodega.objects.create(
                                instalacion=inst,
                                grupo_mezcla=g,
                                volumen_litros=vol_committed
                            )
                                
            elif resultados.solver.termination_condition == pyo.TerminationCondition.infeasible:
                self.stdout.write(self.style.ERROR("El modelo es INFACTIBLE. Revise las restricciones de mezcla."))
            else:
                self.stdout.write(self.style.WARNING("El solver termin pero no con un estado ptimo."))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error crítico del solver: {e}"))
