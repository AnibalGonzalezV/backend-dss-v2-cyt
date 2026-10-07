from .viaje_utils import obtener_viaje_activo
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Camion, Viaje, EventoGPS, PesajeRomana
from .serializers import EventoGPSSerializer, PesajeRomanaSerializer
import uuid

class RecepcionGPSView(APIView):
    def post(self, request):
        serializer = EventoGPSSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            
            # 1. Buscar o crear camión
            camion, _ = Camion.objects.get_or_create(
                patente=data['patente'],
                defaults={'es_externo': False}
            )
            
            viaje = obtener_viaje_activo(camion, estado_inicial='TRANSITO')
            
            # 3. Guardar evento (y el JSON intacto por seguridad)
            EventoGPS.objects.create(
                viaje=viaje,
                eta_proyectado=data['eta'],
                payload_original=data.get('payload_raw', request.data)
            )
            
            return Response({"status": "GPS registrado", "viaje_id": viaje.id}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RecepcionRomanaView(APIView):
    def post(self, request):
        serializer = PesajeRomanaSerializer(data=request.data)
        if serializer.is_valid():
            data = serializer.validated_data
            patente = data.get('patente', '')
            if patente:
                patente = patente.strip().upper()
            
            # LA MAGIA ANTI "SIN PATENTE":
            es_externo = False
            if not patente or patente == 'SIN PATENTE':
                # Generamos una patente virtual única (Ej: EXT-A1B2)
                patente = f"EXT-{str(uuid.uuid4())[:4].upper()}"
                es_externo = True
                
            camion, _ = Camion.objects.get_or_create(
                patente=patente,
                defaults={'es_externo': es_externo}
            )
            
            viaje = obtener_viaje_activo(camion, estado_inicial='ROMANA')
            viaje.estado_actual = 'ROMANA'
            viaje.save()
            
            # Guardamos la Verdad Física (Wk del modelo)
            PesajeRomana.objects.create(
                viaje=viaje,
                peso_neto_kg=data['peso_neto'],
                hora_llegada_real=data['hora_llegada'],
                payload_original=data.get('payload_raw', request.data)
            )
            
            # TODO (Fase 4): Aquí llamaremos asíncronamente a Celery para que corra HiGHS
            # optimizar_patio_task.delay()
            
            return Response({
                "status": "Pesaje validado", 
                "patente_asignada": patente,
                "viaje_id": viaje.id
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


from .models import AsignacionGantt, Instalacion

class GanttDataView(APIView):
    """
    Entrega la foto actual del patio (Cola y Asignaciones) estructurada para el Frontend.
    """
    def get(self, request):
        from .models import SimulacionState
        estado = SimulacionState.objects.first()
        reloj_virtual = estado.reloj_virtual if estado else None
        
        pozos_qs = Instalacion.objects.filter(tipo='POZO').order_by('nombre')
        pozos_data = []
        asignaciones = AsignacionGantt.objects.all().order_by('hora_inicio')
        
        for pozo in pozos_qs:
            asigs_pozo = asignaciones.filter(instalacion=pozo)
            bloques = []
            for a in asigs_pozo:
                viaje = a.viaje
                pesaje = viaje.pesajeromana_set.last()
                gps = viaje.eventogps_set.last()
                
                grupo = "GENERICO"
                peso = 15000.0
                if viaje.camion.es_externo and pesaje and pesaje.payload_original:
                    grupo = pesaje.payload_original.get('grupo_informado', 'GENERICO')
                    peso = float(pesaje.peso_neto_kg)
                elif viaje.programa:
                    grupo = viaje.programa.grupo_mezcla.codigo_material
                    if pesaje: peso = float(pesaje.peso_neto_kg)
                    elif gps and gps.payload_original: peso = float(gps.payload_original.get('peso_estimado_kg', 15000.0))
                elif gps and gps.payload_original:
                    grupo = gps.payload_original.get('grupo_informado', 'GENERICO')
                    peso = float(gps.payload_original.get('peso_estimado_kg', 15000.0))
                    
                espera_hrs = 0.0
                if pesaje and pesaje.hora_llegada_real:
                    espera_hrs = max(0, (a.hora_inicio - pesaje.hora_llegada_real).total_seconds() / 3600.0)

                bloques.append({
                    "id": a.id,
                    "viaje_id": viaje.id,
                    "patente": viaje.camion.patente,
                    "grupo": grupo,
                    "peso_kg": peso,
                    "hora_inicio": a.hora_inicio.isoformat(),
                    "hora_fin": a.hora_fin.isoformat(),
                    "espera_hrs": round(espera_hrs, 1),
                    "es_tentativo": a.es_tentativo,
                    "estado": viaje.estado_actual,
                    "override_manual": a.override_manual
                })
            
            pozos_data.append({
                "id": pozo.id,
                "nombre": pozo.nombre,
                "operativa": pozo.esta_activa,
                "asignaciones": bloques
            })
            
        viajes_activos = Viaje.objects.filter(estado_actual__in=['PATIO', 'ROMANA', 'TRANSITO', 'ALERTA_ATRASO']).order_by('fecha_creacion')
        cola_data = []
        for v in viajes_activos:
            pesaje = v.pesajeromana_set.last()
            gps = v.eventogps_set.last()
            
            grupo = "GENERICO"
            if v.camion.es_externo and pesaje and pesaje.payload_original:
                grupo = pesaje.payload_original.get('grupo_informado', 'GENERICO')
            elif v.programa:
                grupo = v.programa.grupo_mezcla.codigo_material
            elif gps and gps.payload_original:
                grupo = gps.payload_original.get('grupo_informado', 'GENERICO')
            
            llegada = None
            if pesaje and pesaje.hora_llegada_real:
                llegada = pesaje.hora_llegada_real
            elif gps and gps.eta_proyectado:
                llegada = gps.eta_proyectado
                
            cola_data.append({
                "viaje_id": v.id,
                "patente": v.camion.patente,
                "grupo": grupo,
                "hora_llegada": llegada.isoformat() if llegada else None,
                "estado": v.estado_actual
            })
            
        # ---- KPIs ----
        ahora = reloj_virtual if reloj_virtual else datetime.now()
        viajes_totales = Viaje.objects.all()
        procesados = viajes_totales.filter(estado_actual='FINALIZADO').count()
        en_patio = viajes_totales.filter(estado_actual__in=['ROMANA', 'PATIO']).count()
        en_ruta = viajes_totales.filter(estado_actual='TRANSITO').count()
        atrasados = viajes_totales.filter(estado_actual='ALERTA_ATRASO').count()
        descargando = viajes_totales.filter(estado_actual='DESCARGANDO').count()
        
        espera_max = 0
        for v in viajes_totales.filter(estado_actual__in=['ROMANA', 'PATIO']):
            p = v.pesajeromana_set.last()
            if p and p.hora_llegada_real:
                # Quitar timezone si viene con el
                hlt = p.hora_llegada_real.replace(tzinfo=None)
                aht = ahora.replace(tzinfo=None)
                espera_hrs = (aht - hlt).total_seconds() / 3600.0
                if espera_hrs > espera_max:
                    espera_max = espera_hrs
                    
        kpis = {
            'procesados': procesados,
            'en_patio': en_patio,
            'descargando': descargando,
            'en_ruta': en_ruta,
            'atrasados': atrasados,
            'espera_max_hrs': round(espera_max, 1),
            'total_dia': viajes_totales.count()
        }

        return Response({
            "reloj_virtual": reloj_virtual.isoformat() if reloj_virtual else None,
            "pozos": pozos_data,
            "cola_patio": cola_data,
            "kpis": kpis
        }, status=status.HTTP_200_OK)


from .models import SimulacionState, EventoSimulacion, InventarioBodega
import random
from datetime import datetime, timedelta

class InitSimulacionView(APIView):
    """
    Inicializa el escenario de prueba (85 camiones) en la tabla EventoSimulacion
    y resetea el reloj a las 09:00 hrs.
    """
    def post(self, request):
        # 1. Limpiar base de datos
        AsignacionGantt.objects.all().delete()
        InventarioBodega.objects.all().delete()
        EventoGPS.objects.all().delete()
        PesajeRomana.objects.all().delete()
        Viaje.objects.all().delete()
        EventoSimulacion.objects.all().delete()
        
        # 2. Generar Caos
        base_time = datetime.today().replace(hour=9, minute=0, second=0, microsecond=0)
        grupos = [f"GRUPO-{i}" for i in range(1, 12)]
        
        eventos_a_crear = []
        consonantes = "BCDFGHJKLMNPRSTVWXYZ"
        for i in range(1, 86):
            # Formato Chileno Nuevo: 4 Consonantes, 2 Números
            letras = "".join(random.choices(consonantes, k=4))
            numeros = str(random.randint(10, 99))
            patente = f"{letras}-{numeros}"
            
            grupo = random.choice(grupos)
            
            horas_offset = random.gauss(8, 4) 
            horas_offset = max(0, min(19, horas_offset))
            eta_gps = base_time + timedelta(hours=horas_offset)
            
            caos = random.random()
            es_externo = caos < 0.10
            es_atrasado = 0.10 <= caos < 0.30
            es_sobrepeso = 0.30 <= caos < 0.40
            
            peso_estimado = random.uniform(12000, 18000)
            
            if es_externo:
                llegada_real = eta_gps
                peso_real = random.uniform(12000, 25000)
                # Externos siempre van a GENERICO (a menos que se sepa, pero el MVP asume esto por ahora)
                payload = {'patente': patente, 'grupo': 'GENERICO', 'peso': peso_real, 'desc': 'EXTERNO'}
                eventos_a_crear.append(EventoSimulacion(hora_evento=llegada_real, tipo='ROMANA', payload=payload))
            else:
                hora_aviso_gps = eta_gps - timedelta(hours=2)
                if hora_aviso_gps < base_time: hora_aviso_gps = base_time
                
                payload_gps = {'patente': patente, 'grupo': grupo, 'eta': eta_gps.isoformat(), 'peso': peso_estimado}
                eventos_a_crear.append(EventoSimulacion(hora_evento=hora_aviso_gps, tipo='GPS', payload=payload_gps))
                
                llegada_real = eta_gps
                peso_real = peso_estimado
                if es_atrasado: llegada_real += timedelta(hours=random.uniform(1, 3))
                if es_sobrepeso: peso_real += random.uniform(5000, 15000)
                
                payload_romana = {'patente': patente, 'grupo': grupo, 'peso': peso_real, 'desc': 'NORMAL'}
                eventos_a_crear.append(EventoSimulacion(hora_evento=llegada_real, tipo='ROMANA', payload=payload_romana))
        
        EventoSimulacion.objects.bulk_create(eventos_a_crear)
        
        estado, _ = SimulacionState.objects.get_or_create(id=1, defaults={'reloj_virtual': base_time})
        estado.reloj_virtual = base_time
        estado.save()
        
        return Response({"status": "Simulación inicializada (09:00 hrs) con 85 camiones."}, status=status.HTTP_200_OK)

class SimularPasoView(APIView):
    """
    Desencadena el avance del reloj y optimización mediante Celery.
    """
    def post(self, request):
        from .tasks import simular_paso_task
        try:
            # Mandamos la tarea a Celery
            task = simular_paso_task.delay()
            return Response({"task_id": task.id, "status": "Procesando en Celery..."}, status=status.HTTP_202_ACCEPTED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class TaskStatusView(APIView):
    """
    Consulta el estado de una tarea Celery.
    """
    def get(self, request, task_id):
        from celery.result import AsyncResult
        task_result = AsyncResult(task_id)
        return Response({
            "task_id": task_id,
            "status": task_result.status,
            "result": task_result.result if task_result.ready() else None
        }, status=status.HTTP_200_OK)

class FijarAsignacionView(APIView):
    def post(self, request):
        from django.utils.dateparse import parse_datetime
        asignacion_id = request.data.get('asignacion_id')
        pozo_id = request.data.get('pozo_id')
        hora_inicio = request.data.get('hora_inicio')
        fijado = request.data.get('fijado', True)
        
        try:
            asig = AsignacionGantt.objects.get(id=asignacion_id)
            
            if asig.viaje.estado_actual not in ['ROMANA', 'PATIO']:
                return Response({"error": "Solo se pueden fijar camiones en patio o romana."}, status=status.HTTP_400_BAD_REQUEST)
                
            from .models import SimulacionState
            estado = SimulacionState.objects.first()
            ahora = estado.reloj_virtual if estado else None
            
            if fijado:
                if pozo_id:
                    from .models import Instalacion
                    asig.instalacion = Instalacion.objects.get(id=pozo_id)
                if hora_inicio:
                    from django.utils import timezone
                    dt = parse_datetime(hora_inicio)
                    if dt and dt.tzinfo is not None:
                        # Como USE_TZ=False en settings, toda la BD es naive. 
                        # Debemos quitarle la zona horaria al input del frontend.
                        dt = dt.replace(tzinfo=None)
                        
                    if ahora and dt < ahora:
                        return Response({"error": "No puedes fijar un camion en el pasado."}, status=status.HTTP_400_BAD_REQUEST)
                    delta = asig.hora_fin - asig.hora_inicio
                    asig.hora_inicio = dt
                    asig.hora_fin = dt + delta
                    
            asig.override_manual = fijado
            asig.save()
            
            # Al fijar manualmente, disparamos un tick de celery para recalcular el resto del patio
            from .tasks import recalcular_gantt_task
            task = recalcular_gantt_task.delay()
            
            return Response({
                "status": "Asignacion fijada" if fijado else "Asignacion liberada",
                "task_id": task.id
            }, status=status.HTTP_200_OK)
        except AsignacionGantt.DoesNotExist:
            return Response({"error": "Asignacion no encontrada"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
