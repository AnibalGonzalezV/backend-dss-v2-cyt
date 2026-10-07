import pandas as pd
from django.core.management.base import BaseCommand
from api.models import Instalacion

class Command(BaseCommand):
    help = 'Importa las máquinas desde el archivo settings.xlsx directamente a PostgreSQL'

    def add_arguments(self, parser):
        parser.add_argument('ruta_excel', type=str, help='Ruta absoluta o relativa al archivo settings.xlsx')

    def handle(self, *args, **kwargs):
        ruta = kwargs['ruta_excel']
        self.stdout.write(f"Leyendo archivo: {ruta}")
        
        try:
            # Leer todas las pestañas por si acaso, pero usaremos la primera
            df = pd.read_excel(ruta, sheet_name=0)
            contador = 0
            
            for index, row in df.iterrows():
                nombre = str(row['Máquina']).strip()
                bmax = float(row['Bmax'])
                estado = str(row['Estado']).strip().lower()
                tarea = str(row['Tarea']).strip().upper()
                
                # Mapear la tarea del Excel al tipo de máquina en nuestro modelo
                tipo_db = 'CUBA'
                if 'DESPALILLADO' in tarea:
                    tipo_db = 'POZO'
                elif 'PRENSADO' in tarea:
                    tipo_db = 'PRENSA'
                
                # Regla de Ala (Izquierda/Derecha). Por defecto N/A hasta definir lógica física.
                ala_db = 'N/A'
                
                # Capacidad mínima: El ingeniero confirmó que NO hay límite estricto del 40%.
                # Se procesan cargas pequeñas priorizando prensas de menor capacidad.
                cmin = 0
                
                esta_activa = (estado == 'habilitado')
                
                # Actualizar si existe, crear si no existe
                Instalacion.objects.update_or_create(
                    nombre=nombre,
                    defaults={
                        'tipo': tipo_db,
                        'ala': ala_db,
                        'cap_maxima': bmax,
                        'cap_minima': cmin,
                        'esta_activa': esta_activa
                    }
                )
                contador += 1
                
            self.stdout.write(self.style.SUCCESS(f'¡Éxito! Se han importado/actualizado {contador} máquinas en la Base de Datos.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error al leer el Excel: {e}'))
