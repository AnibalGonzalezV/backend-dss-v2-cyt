from celery import shared_task
from django.core.management import call_command
from datetime import timedelta
import random

@shared_task
def simular_paso_task():
    from .models import SimulacionState, EventoSimulacion, Camion, EventoGPS, PesajeRomana, AsignacionGantt
    from .views import obtener_viaje_activo
    
    estado = SimulacionState.objects.first()
    if not estado:
        return "No hay simulacion inicializada."
        
    ahora = estado.reloj_virtual + timedelta(minutes=15)
    
    # Procesar eventos que ocurren en esta ventana
    eventos_pendientes = EventoSimulacion.objects.filter(procesado=False, hora_evento__lte=ahora)
    
    for ev in eventos_pendientes:
        datos = ev.payload
        if ev.tipo == 'GPS':
            camion, _ = Camion.objects.get_or_create(patente=datos['patente'])
            v = obtener_viaje_activo(camion, estado_inicial='TRANSITO')
            from dateutil.parser import parse
            eta_dt = parse(datos['eta'])
            EventoGPS.objects.create(viaje=v, eta_proyectado=eta_dt, payload_original={'peso_estimado_kg': datos['peso'], 'grupo_informado': datos['grupo'], 'eta': datos['eta']})
        elif ev.tipo == 'ROMANA':
            pat = datos['patente']
            es_ext = False
            if pat == 'SIN PATENTE':
                pat = f"EXT-{random.randint(100,999)}"
                es_ext = True
            camion, _ = Camion.objects.get_or_create(patente=pat, defaults={'es_externo': es_ext})
            v = obtener_viaje_activo(camion, estado_inicial='ROMANA')
            v.estado_actual = 'ROMANA'
            v.save()
            PesajeRomana.objects.create(viaje=v, peso_neto_kg=datos['peso'], hora_llegada_real=ev.hora_evento, payload_original={'grupo_informado': datos['grupo']})
        ev.procesado = True
        ev.save()
    
    # Avanzar estados de Gantt: DESCARGANDO -> FINALIZADO
    asigs = AsignacionGantt.objects.all()
    for a in asigs:
        if a.hora_fin <= ahora and a.viaje.estado_actual != 'FINALIZADO':
            if a.viaje.estado_actual in ['DESCARGANDO', 'ROMANA', 'PATIO']:
                a.viaje.estado_actual = 'FINALIZADO'
                a.viaje.save()
        elif a.hora_inicio <= ahora < a.hora_fin:
            if a.viaje.estado_actual in ['ROMANA', 'PATIO']:
                a.viaje.estado_actual = 'DESCARGANDO'
                a.viaje.save()

    estado.reloj_virtual = ahora
    estado.save()
    
    time_str = ahora.strftime('%Y-%m-%d %H:%M:%S')
    
    
    # Llama al optimizador
    call_command('ejecutar_optimizador', virtual_time=time_str)
    
    return f"Tick procesado. Reloj avanzado a {time_str}"

@shared_task
def recalcular_gantt_task():
    """
    Recalcula la optimización en el tiempo actual sin avanzar el reloj.
    Usado cuando el usuario hace un override manual.
    """
    from .models import SimulacionState
    estado = SimulacionState.objects.first()
    if estado:
        time_str = estado.reloj_virtual.strftime('%Y-%m-%d %H:%M:%S')
        call_command('ejecutar_optimizador', virtual_time=time_str)
    return "Recálculo manual completado."
