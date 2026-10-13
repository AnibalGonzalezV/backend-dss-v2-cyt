import os
import django
import sys

# Configurar Django
sys.path.append('/app')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dss_core.settings")
django.setup()

from django.core.management import call_command
from api.models import SimulacionState, TrazabilidadFlujo

def run_test():
    estado = SimulacionState.objects.first()
    if not estado:
        print("No hay simulación iniciada.")
        return
        
    time_str = estado.reloj_virtual.strftime('%Y-%m-%d %H:%M:%S')

    print("================================================")
    print(f"=== TEST DE VALIDACIÓN: TRAZABILIDAD EXACTA ===")
    print(f"Reloj Virtual Actual: {time_str}")
    
    # Limpiar flujos de prueba
    TrazabilidadFlujo.objects.all().delete()

    print("\nEjecutando optimizador HiGHS (con Post-Procesador)...")
    call_command('ejecutar_optimizador', virtual_time=time_str)

    # Consultar la Base de Datos
    flujos = TrazabilidadFlujo.objects.all().order_by('hora_flujo', 'origen__nombre')

    print(f"\n[MÉTRICAS DE BASE DE DATOS]")
    print(f"Registros de Trazabilidad Creados: {flujos.count()}")

    print("\n[VERIFICACIÓN DE INFERENCIA LÓGICA (Patente -> Pozo -> Prensa)]")
    if flujos.count() == 0:
        print("Aún no hay suficiente acumulación en pozos para iniciar el bombeo a prensas en este tick.")
    else:
        for f in flujos:
            print(f" [{f.hora_flujo.strftime('%H:%M')}] Camión {f.viaje.camion.patente} | {f.origen.nombre} bombeó {f.volumen_kg:,.2f} kg hacia {f.destino.nombre}")
    
    print("================================================\n")

if __name__ == '__main__':
    run_test()
