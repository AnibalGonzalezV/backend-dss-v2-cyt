import os
import sys
import django

sys.path.append('/app')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dss_core.settings")
django.setup()

from datetime import timedelta
from django.core.management import call_command
from api.models import (
    SimulacionState, EventoSimulacion, Viaje, Camion, EventoGPS,
    PesajeRomana, AsignacionGantt, Instalacion, InventarioBodega, TrazabilidadFlujo
)
from api.views import obtener_viaje_activo, InitSimulacionView
from rest_framework.test import APIRequestFactory

def test_capacidades():
    print("================================================================================")
    print(" VALIDACIÓN EXPERIMENTAL: CORRECCIÓN DIMENSIONAL DE CAPACIDADES")
    print("================================================================================")

    # 1. Reiniciar simulación
    print("1. Reiniciando escenario con 85 camiones...")
    factory = APIRequestFactory()
    request = factory.post('/api/v1/init-simulacion/')
    InitSimulacionView.as_view()(request)

    estado = SimulacionState.objects.first()
    ahora = estado.reloj_virtual

    # 2. Simular 4 pasos de 15 min (hasta las 10:00) para acumular flujo en patio y bodega
    print("2. Avanzando reloj virtual a las 10:00 AM para generar uva en patio...")
    for step in range(4):
        ahora += timedelta(minutes=15)
        # Procesar eventos hasta 'ahora'
        eventos = EventoSimulacion.objects.filter(procesado=False, hora_evento__lte=ahora)
        for ev in eventos:
            datos = ev.payload
            if ev.tipo == 'GPS':
                camion, _ = Camion.objects.get_or_create(patente=datos['patente'])
                v = obtener_viaje_activo(camion, estado_inicial='TRANSITO')
                from dateutil.parser import parse
                eta_dt = parse(datos['eta'])
                if hasattr(eta_dt, 'tzinfo') and eta_dt.tzinfo is not None:
                    eta_dt = eta_dt.replace(tzinfo=None)
                EventoGPS.objects.create(viaje=v, eta_proyectado=eta_dt, payload_original={'peso_estimado_kg': datos['peso'], 'grupo_informado': datos['grupo'], 'eta': datos['eta']})
            elif ev.tipo == 'ROMANA':
                pat = datos['patente']
                es_ext = (pat == 'SIN PATENTE' or 'EXT-' in pat)
                camion, _ = Camion.objects.get_or_create(patente=pat, defaults={'es_externo': es_ext})
                v = obtener_viaje_activo(camion, estado_inicial='ROMANA')
                v.estado_actual = 'ROMANA'
                v.save()
                PesajeRomana.objects.create(viaje=v, peso_neto_kg=datos['peso'], hora_llegada_real=ev.hora_evento, payload_original={'grupo_informado': datos['grupo']})
            ev.procesado = True
            ev.save()

        # Avanzar estados de Gantt
        for a in AsignacionGantt.objects.all():
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

    # 3. Ejecutar Optimizador a las 10:00 con el modelo corregido
    time_str = ahora.strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n3. Ejecutando Optimizador HiGHS en Reloj Virtual: {time_str}...")
    call_command('ejecutar_optimizador', virtual_time=time_str)

    # 4. Validar Asignaciones generadas
    asigs = AsignacionGantt.objects.filter(hora_inicio__gte=ahora)
    print(f"\n4. Asignaciones generadas en Gantt: {asigs.count()}")

    # 5. Auditoría de Inventario en Cubas y Máquinas
    print("\n5. Auditoría de Capacidades Físicas (Tope de Cubas: 50,000 L / Prensas: 100,000 kg):")
    inventarios = InventarioBodega.objects.all()
    print(f"   Total registros de inventario en bodega: {inventarios.count()}")

    violaciones = 0
    for inv in inventarios:
        cap_max = float(inv.instalacion.cap_maxima) # 50,000 para cubas
        vol = float(inv.volumen_litros)
        unidad = "kg" if inv.instalacion.tipo == 'PRENSA' else "L"
        es_valido = vol <= cap_max
        if not es_valido:
            violaciones += 1
            print(f"   [VIOLACIÓN] {inv.instalacion.nombre} ({inv.grupo_mezcla}): {vol:,.1f} {unidad} > Tope {cap_max:,.1f} {unidad}")
        else:
            print(f"   [VÁLIDO]    {inv.instalacion.nombre} ({inv.grupo_mezcla}): {vol:,.1f} {unidad} <= Tope {cap_max:,.1f} {unidad}")

    # 6. Auditoría de Trazabilidad
    flujos = TrazabilidadFlujo.objects.all()
    print(f"\n6. Flujos de Trazabilidad creados (Pozos -> Prensas): {flujos.count()}")
    for f in flujos[:5]:
        print(f"   - {f.origen.nombre} -> {f.destino.nombre}: {f.volumen_kg:,.1f} kg ({f.viaje.camion.patente})")

    print("\n================================================================================")
    if violaciones == 0:
        print(" RESULTADO: SUITE DE PRUEBAS APROBADA AL 100%. CERO VIOLACIONES DIMENSIONALES.")
    else:
        print(f" RESULTADO: FALLO - Se detectaron {violaciones} violaciones de capacidad.")
    print("================================================================================")

if __name__ == '__main__':
    test_capacidades()
