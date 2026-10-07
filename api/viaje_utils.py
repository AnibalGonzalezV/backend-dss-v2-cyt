from api.models import Viaje

ESTADOS_ACTIVOS = ['TRANSITO', 'ROMANA', 'PATIO', 'ALERTA_ATRASO']
ESTADOS_EN_PLANTA = ['ROMANA', 'PATIO', 'DESCARGANDO']


def obtener_viaje_activo(camion, estado_inicial='TRANSITO'):
    """Un camión tiene un solo viaje abierto. La romana reabre un GPS o una alerta."""
    viaje = (
        Viaje.objects.filter(camion=camion, estado_actual__in=ESTADOS_ACTIVOS)
        .order_by('-id')
        .first()
    )
    if viaje is None:
        viaje = Viaje.objects.create(camion=camion, estado_actual=estado_inicial)
    return viaje


def grupo_de_viaje(viaje):
    if viaje.programa_id:
        return viaje.programa.grupo_mezcla.codigo_material

    pesaje = viaje.pesajeromana_set.last()
    if pesaje and pesaje.payload_original:
        return pesaje.payload_original.get('grupo_informado') or 'GENERICO'

    gps = viaje.eventogps_set.last()
    if gps and gps.payload_original:
        return gps.payload_original.get('grupo_informado') or 'GENERICO'

    return 'GENERICO'
