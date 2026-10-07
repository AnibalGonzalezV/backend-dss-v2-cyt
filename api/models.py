from django.db import models

class GrupoMezcla(models.Model):
    """
    Agrupación enológica (Gk) que define la compatibilidad de la uva.
    """
    codigo_material = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return self.codigo_material

class ProgramaVendimia(models.Model):
    """
    Lo planificado inicialmente en el Excel por los enólogos.
    """
    ctto_contrato = models.CharField(max_length=100)
    grupo_mezcla = models.ForeignKey(GrupoMezcla, on_delete=models.CASCADE)
    productor = models.CharField(max_length=200)
    fundo = models.CharField(max_length=200)
    variedad = models.CharField(max_length=100)
    kilos_programados = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_programada = models.DateField()

    def __str__(self):
        return f"{self.ctto_contrato} - {self.productor}"

class Camion(models.Model):
    """
    Entidad física indivisible que llega al patio.
    """
    patente = models.CharField(max_length=20, unique=True)
    tipo_camion = models.CharField(max_length=50, blank=True, null=True) # Simple, Con Carro
    es_externo = models.BooleanField(default=False) # True para camiones "Sin Patente"

    def __str__(self):
        return self.patente

class Viaje(models.Model):
    """
    El evento logístico del día. Desacopla el Programa del Camión físico.
    """
    ESTADOS = [
        ('TRANSITO', 'En Tránsito'),
        ('ROMANA', 'En Romana'),
        ('PATIO', 'En Patio (Esperando)'),
        ('DESCARGANDO', 'Descargando'),
        ('FINALIZADO', 'Finalizado'),
        ('ALERTA_ATRASO', 'Alerta: Atraso Crítico'),
    ]
    camion = models.ForeignKey(Camion, on_delete=models.CASCADE)
    # Permite NULL para resolver el problema de camiones externos que no están en el Excel
    programa = models.ForeignKey(ProgramaVendimia, on_delete=models.SET_NULL, null=True, blank=True)
    estado_actual = models.CharField(max_length=50, choices=ESTADOS, default='TRANSITO')
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Viaje {self.id} - {self.camion.patente}"

class EventoGPS(models.Model):
    """
    Aviso temprano de llegada (API Divantech).
    """
    viaje = models.ForeignKey(Viaje, on_delete=models.CASCADE)
    eta_proyectado = models.DateTimeField()
    hora_aviso = models.DateTimeField(null=True, blank=True)
    fecha_lectura = models.DateTimeField(auto_now_add=True)
    
    # PATRÓN DATA LAKE: Guarda el JSON íntegro por si Divantech cambia su estructura
    payload_original = models.JSONField(null=True, blank=True)

class PesajeRomana(models.Model):
    """
    La única fuente de verdad (API CII). El peso_neto_kg es el parámetro Wk del modelo MILP.
    """
    viaje = models.ForeignKey(Viaje, on_delete=models.CASCADE)
    peso_neto_kg = models.DecimalField(max_digits=10, decimal_places=2)
    hora_llegada_real = models.DateTimeField()
    
    # PATRÓN DATA LAKE: Guarda el JSON íntegro de la romana
    payload_original = models.JSONField(null=True, blank=True)

class Instalacion(models.Model):
    """
    Maquinaria física disponible (Pozos, Prensas, Cubas).
    """
    TIPOS = [
        ('POZO', 'Pozo Descarga'),
        ('PRENSA', 'Prensa'),
        ('CUBA', 'Cuba')
    ]
    ALAS = [
        ('IZQ', 'Ala Izquierda'),
        ('DER', 'Ala Derecha'),
        ('N/A', 'No Aplica')
    ]
    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=50, choices=TIPOS)
    ala = models.CharField(max_length=50, choices=ALAS, default='N/A')
    cap_maxima = models.DecimalField(max_digits=10, decimal_places=2)
    cap_minima = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    esta_activa = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.tipo} - {self.nombre}"

class AsignacionGantt(models.Model):
    """
    Output del Motor Matemático (HiGHS) para ser consumido por React.
    """
    viaje = models.ForeignKey(Viaje, on_delete=models.CASCADE)
    instalacion = models.ForeignKey(Instalacion, on_delete=models.CASCADE)
    hora_inicio = models.DateTimeField()
    hora_fin = models.DateTimeField()
    es_tentativo = models.BooleanField(default=True)
    override_manual = models.BooleanField(default=False) # True si el Jefe de Patio lo editó

class InventarioBodega(models.Model):
    """
    Output del Hito 4: Sumideros de capacidad (Prensas y Cubas).
    Guarda el volumen real procesado/asignado tras las mermas (rho).
    """
    instalacion = models.ForeignKey(Instalacion, on_delete=models.CASCADE)
    grupo_mezcla = models.CharField(max_length=100)
    volumen_litros = models.DecimalField(max_digits=12, decimal_places=2)
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.instalacion.nombre} | {self.grupo_mezcla} | {self.volumen_litros} L"

class SimulacionState(models.Model):
    """ Modelo Singleton para mantener el estado del Reloj Virtual """
    reloj_virtual = models.DateTimeField()
    
    class Meta:
        db_table = 'simulacion_state'

class EventoSimulacion(models.Model):
    """ Cola de eventos futuros (GPS/ROMANA) para procesar iterativamente en /tick """
    hora_evento = models.DateTimeField()
    tipo = models.CharField(max_length=50) # 'GPS' o 'ROMANA'
    payload = models.JSONField()
    procesado = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'evento_simulacion'
        ordering = ['hora_evento']
