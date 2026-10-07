import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from datetime import datetime
from api.models import GrupoMezcla, ProgramaVendimia

class Command(BaseCommand):
    help = 'Ejecuta el pipeline ETL para ingerir el Programa Vendimia 2024 a la Base de Datos.'

    def add_arguments(self, parser):
        parser.add_argument('ruta_excel', type=str, help='Ruta al archivo Programa Vendimia 2024.xlsx')
        parser.add_argument('--fecha', type=str, default='2024-03-18', help='Fecha específica a filtrar (YYYY-MM-DD)')

    def handle(self, *args, **kwargs):
        ruta = kwargs['ruta_excel']
        fecha_filtro_str = kwargs['fecha']
        
        try:
            fecha_filtro = pd.to_datetime(fecha_filtro_str).date()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Formato de fecha inválido. Usa YYYY-MM-DD. Error: {e}"))
            return

        self.stdout.write(f"Iniciando extracción ETL desde: {ruta} para la fecha {fecha_filtro_str}")
        
        try:
            # 1. EXTRAER (Extract): Leer la hoja plana DIARIOxBLOQUE saltando la basura visual
            df = pd.read_excel(ruta, sheet_name='DIARIOxBLOQUE', header=3)
            
            # Limpiar filas completamente vacías
            df = df.dropna(how='all')
            
            # 2. TRANSFORMAR (Transform): Limpieza de datos
            # Convertir la columna FECHA a datetime para poder filtrar
            df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce').dt.date
            
            # Filtrar solo la fecha requerida (El Día Cero de nuestra simulación)
            df_dia = df[df['FECHA'] == fecha_filtro]
            
            if df_dia.empty:
                self.stdout.write(self.style.WARNING(f"No se encontraron registros para la fecha {fecha_filtro_str}."))
                return

            self.stdout.write(f"Se encontraron {len(df_dia)} registros planificados para el {fecha_filtro_str}.")

            # Limpieza previa para evitar duplicidad o datos basura de pruebas anteriores
            ProgramaVendimia.objects.filter(fecha_programada=fecha_filtro).delete()

            # 3. CARGAR (Load): Inyectar a PostgreSQL asegurando integridad relacional
            with transaction.atomic():
                contador_grupos = 0
                contador_programas = 0
                
                for index, row in df_dia.iterrows():
                    ctto = str(row['CTTO']).replace('.0', '').strip() if pd.notna(row['CTTO']) else "SIN_CTTO"
                    if ctto == "SIN_CTTO" or ctto == "nan":
                        continue

                    # CORRECCIÓN DE NEGOCIO: Usamos el BLOQUE como identificador real de mezcla operativa.
                    bloque = str(row['BLOQUE']).replace('.0', '').strip() if pd.notna(row['BLOQUE']) else "0"
                    id_bloque = f"BLOQUE-{bloque}"
                    
                    codigo_sap = str(row['CODIGO']).replace('.0', '').strip() if pd.notna(row['CODIGO']) else "GENERICO"
                    
                    # a. Gestionar el Grupo de Mezcla (Bloques)
                    grupo, g_created = GrupoMezcla.objects.get_or_create(
                        codigo_material=id_bloque,
                        defaults={'descripcion': f"Mezcla Operativa {bloque}"}
                    )
                    if g_created: contador_grupos += 1
                    
                    productor = str(row['PRODUCTOR']).strip() if pd.notna(row['PRODUCTOR']) else "Desconocido"
                    variedad_excel = str(row['VARIEDAD']).strip() if pd.notna(row['VARIEDAD']) else "No Especificada"
                    
                    # Guardamos el código SAP granular dentro del nombre de la variedad para no perder trazabilidad
                    variedad_completa = f"{variedad_excel} (Cod: {codigo_sap})"
                    kilos = float(row['KG DIARIOS']) if pd.notna(row['KG DIARIOS']) else 0.0

                    # b. Inyectar la cuota al Programa Vendimia
                    ProgramaVendimia.objects.create(
                        ctto_contrato=ctto,
                        fecha_programada=fecha_filtro,
                        grupo_mezcla=grupo,
                        productor=productor,
                        fundo=productor,
                        variedad=variedad_completa,
                        kilos_programados=kilos
                    )
                    contador_programas += 1

            self.stdout.write(self.style.SUCCESS(
                f"¡ETL Finalizado con Éxito!\n"
                f" - Nuevos Grupos de Mezcla creados: {contador_grupos}\n"
                f" - Contratos Programados inyectados: {contador_programas}"
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error crítico en el pipeline ETL: {e}"))
