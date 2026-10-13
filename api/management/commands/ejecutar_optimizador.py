import json
import math
from datetime import datetime, timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
import pyomo.environ as pyo

from api.models import Viaje, Instalacion, ProgramaVendimia, GrupoMezcla, AsignacionGantt, InventarioBodega, TrazabilidadFlujo
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
                # Usar el ETA original para la alerta crÃ­tica
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
            return json.dumps({
                'status': 'EMPTY',
                'solver_time': 0.0,
                'build_time': 0.0,
                'total_camiones_ventana': 0,
                'camiones_asignados': 0,
                'camiones_drop': 0,
                'dropped_trucks': []
            })
            
        K = []
        K_gps = []
        w = {}
        Gk = {}
        Pk = {}
        c_espera = {}
        c_drop = {}
        tmin = {}
        T_commit = 2  # 20 minutos fijos para bloquear GPS
        
                # Horizonte rodante: Planificamos las próximas 4 horas (T = 24 intervalos de 10 min) para dar mayor visibilidad a futuro
        T = list(range(1, 25))
        
        for viaje in viajes_espera:
            k_id = f"V{viaje.id}"
            K.append(k_id)
            
            pesaje = None
            gps = None
            # Obtener peso segÃºn el estado
            if viaje.estado_actual == 'TRANSITO':
                gps = viaje.eventogps_set.last()
                peso = float(gps.payload_original.get('peso_estimado_kg', 15000.0)) if gps and gps.payload_original else 15000.0
                K_gps.append(k_id)
                # tmin: Intervalo donde cae el ETA
                if gps and gps.eta_proyectado > ahora:
                    minutos_espera = (gps.eta_proyectado - ahora).total_seconds() / 60.0
                    t_llegada = math.ceil(minutos_espera / 10.0) + 1
                    tmin[k_id] = max(1, min(int(t_llegada), 24))
                else:
                    tmin[k_id] = 1
            else:
                pesaje = viaje.pesajeromana_set.last()
                peso = float(pesaje.peso_neto_kg) if pesaje else 15000.0 # Por defecto
                tmin[k_id] = 1
            w[k_id] = peso
            
            # Tiempo de descarga realista (Ajuste IO): 
            # 10 min (1 int) fijo por maniobra (cuadrar, lavar) + 10 min por cada 12.500 kg.
            # Ej: CamiÃ³n de 25.000 kg -> 1 + ceil(2.0) = 3 intervalos (30 min).
            Pk[k_id] = math.ceil(peso / 12500.0) + 1
            
            # Identificar grupo de mezcla (JerarquÃ­a: Programa > Pesaje > GPS > Default)
            grupo = "GENERICO"
            if viaje.programa:
                grupo = viaje.programa.grupo_mezcla.codigo_material
            elif pesaje and pesaje.payload_original:
                grupo = pesaje.payload_original.get('grupo_informado', 'GENERICO')
            elif viaje.estado_actual == 'TRANSITO':
                gps = viaje.eventogps_set.last()
                grupo = gps.payload_original.get('grupo_informado', 'GENERICO') if gps and gps.payload_original else 'GENERICO'
            Gk[k_id] = grupo
            
            # Costo de Deterioro: Camiones que llevan mÃ¡s tiempo esperando tienen mayor Costo
            espera_minutos = 0
            if viaje.estado_actual == 'TRANSITO' and gps and gps.eta_proyectado:
                espera_minutos = max(0, (ahora - gps.eta_proyectado).total_seconds() / 60)
            elif pesaje and pesaje.hora_llegada_real:
                espera_minutos = max(0, (ahora - pesaje.hora_llegada_real).total_seconds() / 60)
            
            if viaje.estado_actual in ['ROMANA', 'PATIO']:
                espera_minutos += 120  # Simulamos 2 hrs extra de espera para darle mÃ¡xima prioridad matemÃ¡tica
                
            for t in T:
                # El costo crece proporcionalmente al tiempo total que la uva pasa en el camión
                # El costo de espera debe ser NO LINEAL para forzar prioridad FIFO natural
                c_espera[(k_id, t)] = (espera_minutos + (t * 10.0)) ** 1.5
                
            # PENALIZACIÓN PROFESIONAL: Si el camión es pateado al "Nodo Futuro", 
            # asume que esperará todo el horizonte (len(T) * 10 min) + 60 min extras de castigo.
            c_drop[k_id] = (espera_minutos + (len(T) * 10.0) + 60.0) ** 1.5

        # 2. Obtener Maquinarias Activas (Topología Híbrida Desacoplada)
        instalaciones = Instalacion.objects.filter(esta_activa=True)
        J_pozos = [inst.nombre for inst in instalaciones if inst.tipo == 'POZO']
        J_prensas = [inst.nombre for inst in instalaciones if inst.tipo == 'PRENSA']
        
        Vmin = {inst.nombre: float(inst.cap_minima) for inst in instalaciones}
        Vmax = {inst.nombre: float(inst.cap_maxima) for inst in instalaciones}

        # 3. Grupos de mezcla Ãºnicos
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

        # 2. Limpiar TODA asignaciÃ³n de camiones que no estÃ©n descargando (excepto los fijados manualmente)
        AsignacionGantt.objects.filter(
            viaje__estado_actual__in=['ROMANA', 'PATIO', 'TRANSITO', 'ALERTA_ATRASO'],
            override_manual=False
        ).delete()
        TrazabilidadFlujo.objects.filter(hora_flujo__gte=ahora).delete()  # Limpiar prediccion de flujos

        
        bloqueo_inicial = {j: 0 for j in J_pozos}
        # Solo las descargas que estÃ¡n fÃ­sicamente ocurriendo bloquean el pozo
        descargas_activas = AsignacionGantt.objects.filter(instalacion__tipo='POZO', hora_fin__gt=ahora, viaje__estado_actual='DESCARGANDO')
        for desc in descargas_activas:
            minutos_restantes = (desc.hora_fin - ahora).total_seconds() / 60.0
            if minutos_restantes > 0:
                t_bloqueados = math.ceil(minutos_restantes / 10.0)
                pozo_name = desc.instalacion.nombre
                if pozo_name in bloqueo_inicial:
                    bloqueo_inicial[pozo_name] = max(bloqueo_inicial[pozo_name], t_bloqueados)

        # --- CÁLCULO DE NORMALIZADORES PARA PYOMO ---
        total_w = sum(w.values()) if w else 1.0
        max_espera = max(c_espera.values()) if c_espera else 1.0
        max_drop = max(c_drop.values()) if c_drop else 1.0
        
        # Capacidad de fermentación agregada por grupo (230 cubas de 65.000 L en Lontué)
        cap_bodega_grupo = {g: 1300000.0 for g in G}

        datos = {
            'frozen_assignments': frozen_assignments,
            'bloqueo_inicial': bloqueo_inicial,
            'T': T,
            'K': K,
            'K_gps': K_gps,
            'tmin': tmin,
            'T_commit': T_commit,
            'J_pozos': J_pozos,
            'J_prensas': J_prensas,
            'cap_bodega_grupo': cap_bodega_grupo,
            'G': G,
            'w': w,
            'Gk': Gk,
            'Pk': Pk,
            'Vmax': Vmax,
            'c_espera': c_espera,
            'c_drop': c_drop,
            'total_w': total_w,
            'max_espera': max_espera,
            'max_drop': max_drop
        }

        self.stdout.write(f"Iniciando Optimizador HiGHS: {len(K)} Camiones, {len(J_pozos) + len(J_prensas)} Máquinas, {len(G)} Grupos.")
        
                # 4. Construir y Resolver (Instrumentado con Telemetría)
        import time
        t_build_start = time.time()
        modelo = build_dss_model(datos)
        t_build = time.time() - t_build_start
        
        try:
            solver = pyo.SolverFactory('appsi_highs')
            # Límite de tiempo estricto para asegurar agilidad operativa (60 seg)
            solver.highs_options['time_limit'] = 15.0
            solver.highs_options['mip_rel_gap'] = 0.05 
            
            t_solve_start = time.time()
            resultados = solver.solve(modelo, tee=False)
            t_solve = time.time() - t_solve_start
            
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
                                
                                grupo_str = Gk[k]
                                viaje_id = int(k[1:])
                                viaje_obj = Viaje.objects.get(id=viaje_id)
                                pesaje = viaje_obj.pesajeromana_set.last()
                                espera_hrs = 0.0
                                llegada_str = "--:--"
                                if pesaje and pesaje.hora_llegada_real:
                                    espera_hrs = max(0, (hora_asignada - pesaje.hora_llegada_real).total_seconds() / 3600.0)
                                    llegada_str = pesaje.hora_llegada_real.strftime('%H:%M')
                                
                                estado_viaje = viaje_obj.estado_actual
                                es_gps = "(GPS)" if estado_viaje == "TRANSITO" else "(Patio)"
                                
                                self.stdout.write(f" - {es_gps} Camión {k} (Llegó {llegada_str}) asignado a {j} en el intervalo T={t} ({hora_str}) | Peso: {peso_kg:,.0f} kg | Grupo: {grupo_str} | Espera: {espera_hrs:.1f} hrs")
                                instalacion = Instalacion.objects.get(nombre=j)
                                
                                AsignacionGantt.objects.create(
                                    viaje_id=viaje_id,
                                    instalacion=instalacion,
                                    hora_inicio=hora_asignada,
                                    hora_fin=hora_asignada + timedelta(minutes=Pk[k]*10)
                                )
                
                # --- HITO POST-OPT: SINCRONIZACIÓN DE ESTADOS INMEDIATOS ---
                # Si la IA programó un camión del patio para que empiece "AHORA MISMO" (hora_inicio <= ahora),
                # debemos pasarlo a DESCARGANDO inmediatamente para que el usuario pueda interactuar con él.
                ids_a_actualizar = AsignacionGantt.objects.filter(
                    hora_inicio__lte=ahora,
                    viaje__estado_actual__in=['ROMANA', 'PATIO'],
                    override_manual=False
                ).values_list('viaje_id', flat=True)
                
                if ids_a_actualizar:
                    Viaje.objects.filter(id__in=ids_a_actualizar).update(estado_actual='DESCARGANDO')
                    self.stdout.write(self.style.SUCCESS(f"Sincronizacion Automatica: {len(ids_a_actualizar)} camiones pasaron a DESCARGANDO."))
                
                # --- HITO 4: Persistencia en Cubas Físicas Reales de Bodega ---
                cubas_reales = list(Instalacion.objects.filter(tipo='CUBA', nombre__startswith='CubaF_').order_by('nombre'))
                cuba_idx = 0
                rho_rendimiento = 0.6536 * 0.94

                for g in G:
                    mosto_t6 = sum(
                        (pyo.value(modelo.F[p, pr, g, t]) or 0.0) * rho_rendimiento
                        for p in J_pozos
                        for pr in J_prensas
                        for t in range(1, 7)
                        if t in modelo.T
                    )
                    volumen_restante = mosto_t6
                    while volumen_restante >= 1.0 and cuba_idx < len(cubas_reales):
                        cuba_inst = cubas_reales[cuba_idx]
                        cap_cuba = float(cuba_inst.cap_maxima)
                        vol_asignar = min(volumen_restante, cap_cuba)
                        InventarioBodega.objects.create(
                            instalacion=cuba_inst,
                            grupo_mezcla=g,
                            volumen_litros=vol_asignar
                        )
                        volumen_restante -= vol_asignar
                        if vol_asignar >= cap_cuba:
                            cuba_idx += 1

                # -------------------------------------------------------------
                # POST-PROCESADOR DE TRAZABILIDAD (DESACOPLADO DE LA MATRIZ MILP)
                # -------------------------------------------------------------
                camion_memoria = {}
                # Primero poblamos la memoria de qué camión estaba en qué pozo a cada instante T
                for t_idx in T:
                    for k_id in K:
                        for j_pozo in J_pozos:
                            if pyo.value(modelo.X[k_id, j_pozo, t_idx]) and pyo.value(modelo.X[k_id, j_pozo, t_idx]) > 0.5:
                                camion_memoria[(j_pozo, t_idx)] = k_id
                
                # Ahora leemos el flujo F (Pozos -> Prensas)
                for t_idx in T:
                    for j_pozo in J_pozos:
                        for j_prensa in J_prensas:
                            for g in G:
                                f_val = pyo.value(modelo.F[j_pozo, j_prensa, g, t_idx])
                                if f_val and f_val > 0.1:
                                    # Buscar de quién vino esta uva
                                    # 1. ¿Hay alguien descargando en este instante en el pozo?
                                    k_origen = camion_memoria.get((j_pozo, t_idx))
                                    # 2. Si no, buscar el camión más reciente que descargó antes de T
                                    if not k_origen:
                                        for back_t in range(t_idx - 1, 0, -1):
                                            if (j_pozo, back_t) in camion_memoria:
                                                k_origen = camion_memoria[(j_pozo, back_t)]
                                                break
                                    
                                    if k_origen:
                                        viaje_id = int(k_origen.replace('V', ''))
                                        hora_flujo = ahora + timedelta(minutes=(t_idx-1)*10)
                                        # Guardar trazabilidad inferida en BD
                                        pozo_inst = Instalacion.objects.get(nombre=j_pozo)
                                        prensa_inst = Instalacion.objects.get(nombre=j_prensa)
                                        TrazabilidadFlujo.objects.create(
                                            viaje_id=viaje_id,
                                            origen=pozo_inst,
                                            destino=prensa_inst,
                                            volumen_kg=f_val,
                                            hora_flujo=hora_flujo
                                        )
                # -------------------------------------------------------------

                # Conteo de camiones en X_drop
                dropped_trucks = []
                for k in K:
                    try:
                        if pyo.value(modelo.X_drop[k]) and pyo.value(modelo.X_drop[k]) > 0.5:
                            dropped_trucks.append(k)
                    except Exception:
                        pass
                
                if dropped_trucks:
                    self.stdout.write(self.style.WARNING(f"Camiones enviados a Nodo Futuro (X_drop): {len(dropped_trucks)} ({', '.join(dropped_trucks)})"))

                return json.dumps({
                    'status': str(resultados.solver.termination_condition),
                    'obj_val': float(obj_val) if 'obj_val' in locals() and obj_val is not None else None,
                    'solver_time': round(t_solve, 3),
                    'build_time': round(t_build, 3),
                    'total_camiones_ventana': len(K),
                    'camiones_asignados': AsignacionGantt.objects.filter(hora_inicio__gte=ahora, hora_inicio__lte=ahora+timedelta(hours=4)).count(),
                    'camiones_drop': len(dropped_trucks),
                    'dropped_trucks': dropped_trucks
                })

            elif resultados.solver.termination_condition == pyo.TerminationCondition.infeasible:
                self.stdout.write(self.style.ERROR("El modelo es INFACTIBLE. Revise las restricciones de mezcla."))
                return json.dumps({
                    'status': 'INFEASIBLE',
                    'solver_time': round(t_solve, 3) if 't_solve' in locals() else 0.0,
                    'build_time': round(t_build, 3) if 't_build' in locals() else 0.0,
                    'total_camiones_ventana': len(K),
                    'camiones_asignados': 0,
                    'camiones_drop': 0,
                    'dropped_trucks': []
                })
            else:
                self.stdout.write(self.style.WARNING("El solver terminó pero no con un estado óptimo."))
                return json.dumps({
                    'status': str(resultados.solver.termination_condition) if 'resultados' in locals() else 'NON_OPTIMAL',
                    'solver_time': round(t_solve, 3) if 't_solve' in locals() else 0.0,
                    'build_time': round(t_build, 3) if 't_build' in locals() else 0.0,
                    'total_camiones_ventana': len(K),
                    'camiones_asignados': 0,
                    'camiones_drop': 0,
                    'dropped_trucks': []
                })
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error crítico del solver: {e}"))
            return json.dumps({
                'status': 'ERROR',
                'error': str(e),
                'solver_time': 0.0,
                'build_time': round(t_build, 3) if 't_build' in locals() else 0.0,
                'total_camiones_ventana': len(K),
                'camiones_asignados': 0,
                'camiones_drop': 0,
                'dropped_trucks': []
            })





