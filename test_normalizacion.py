import os
import django
import sys
import time
from datetime import timedelta

# Configurar Django
sys.path.append('/app')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dss_core.settings")
django.setup()

from django.core.management import call_command
from api.models import AsignacionGantt, SimulacionState, Viaje

def run_test():
    # 1. Asegurar estado
    estado = SimulacionState.objects.first()
    if not estado:
        print("No hay simulaciÃ³n iniciada.")
        return
        
    time_str = estado.reloj_virtual.strftime('%Y-%m-%d %H:%M:%S')

    print("================================================")
    print(f"=== TEST DE VALIDACIÃ“N: FUNCIÃ“N OBJETIVO ===")
    print(f"Reloj Virtual Actual: {time_str}")
    
    # Limpiar Gantt para ver el resultado puro del solver
    AsignacionGantt.objects.filter(override_manual=False).delete()

    print("\nEjecutando optimizador HiGHS (con NormalizaciÃ³n)...")
    t0 = time.time()
    # Capturar la salida estÃ¡ndar
    call_command('ejecutar_optimizador', virtual_time=time_str)
    t1 = time.time()

    asignaciones = AsignacionGantt.objects.all().order_by('hora_inicio')

    print(f"\n[MÃ‰TRICAS DE RENDIMIENTO]")
    print(f"Tiempo de ejecuciÃ³n total: {t1-t0:.3f} segundos")
    print(f"Asignaciones generadas (Horizonte 4h): {asignaciones.count()}")

    print("\n[VERIFICACIÃ“N DE POLÃTICA FIFO Y PRIORIDADES]")
    print("Si la normalizaciÃ³n funciona, los primeros bloques asignados")
    print("deben ser camiones de PATIO con la mayor espera acumulada.\n")
    
    for asig in asignaciones[:10]:
        viaje = Viaje.objects.get(id=asig.viaje_id)
        if viaje.estado_actual == 'TRANSITO':
            eta = viaje.eventogps_set.last().eta_proyectado
            print(f" [GPS]   Patente: {viaje.camion.patente} | ETA: {eta.strftime('%H:%M')} -> Asignado a las: {asig.hora_inicio.strftime('%H:%M')} en {asig.instalacion.nombre}")
        else:
            llegada = viaje.pesajeromana_set.last().hora_llegada_real if viaje.pesajeromana_set.exists() else estado.reloj_virtual
            wait_hours = (asig.hora_inicio - llegada).total_seconds() / 3600.0
            print(f" [PATIO] Patente: {viaje.camion.patente} | Espera: {wait_hours:.1f} hrs -> Asignado a las: {asig.hora_inicio.strftime('%H:%M')} en {asig.instalacion.nombre}")

    print("================================================\n")

if __name__ == '__main__':
    run_test()

