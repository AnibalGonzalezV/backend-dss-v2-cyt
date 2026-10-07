# DSS Backend - Planning & Scheduling

Este repositorio contiene el backend del Sistema de Soporte de Decisiones (DSS) diseñado para la optimización logística de patios de recepción de uva para la Bodega Lontué. El sistema utiliza Programación Lineal Entera Mixta (MILP) para planificar de forma óptima el flujo logístico de los camiones.

## Arquitectura y Tecnologías
*   **Framework:** Django 5.0 y Django REST Framework.
*   **Motor de Optimización:** Pyomo y HiGHS Solver (`highspy`).
*   **Procesamiento Asíncrono:** Celery y Redis.
*   **Base de Datos:** SQLite (configurado por defecto para desarrollo local, adaptable a PostgreSQL).

## Estructura del Proyecto
*   `api/`: Lógica central, modelos de datos, endpoints REST y tareas asíncronas de Celery.
*   `optimization/`: Formulación del modelo MILP (conjuntos, parámetros, variables, función objetivo y restricciones).
*   `dss_core/`: Configuraciones de Django y Celery.

## Principios de Funcionamiento
1.  **Desacoplamiento:** El motor de optimización matemática se ejecuta de manera asíncrona mediante Celery, evitando bloquear el ciclo HTTP de respuesta al frontend.
2.  **Gestión de Ventanas de Tiempo (Time Fences):** Los camiones próximos a descargar o con asignaciones manuales se fijan en el modelo matemático para mantener la continuidad operativa.
3.  **Intervención Manual:** Soporte nativo para ajustes manuales desde la interfaz, permitiendo que el optimizador reasigne los recursos disponibles respetando las restricciones establecidas por el usuario.

## Guía de Instalación y Despliegue Local

### Requisitos Previos
*   Docker y Docker Compose (Recomendado para simplificar la instalación)
*   Python 3.10+ (En caso de ejecución nativa)

### Despliegue con Docker (Recomendado)
El proyecto incluye un archivo `docker-compose.yml` preconfigurado con Django, Celery y Redis.

1. Construir y levantar los servicios:
```bash
docker-compose up --build -d
```
2. Ejecutar las migraciones de la base de datos:
```bash
docker-compose exec web python manage.py migrate
```
3. (Opcional) Carga de datos maestros si la base de datos está vacía:
```bash
docker-compose exec web python manage.py importar_maquinas
docker-compose exec web python manage.py cargar_programa "Programa Vendimia 2024.xlsx"
```
El backend quedará expuesto en `http://localhost:8080`.

### Despliegue Nativo (Sin Docker)
1. Instalar un servidor Redis local y asegurar su ejecución en el puerto 6379.
2. Crear un entorno virtual e instalar las dependencias:
```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```
3. Aplicar las migraciones:
```bash
python manage.py migrate
```
4. Levantar el servidor de Django (Terminal 1):
```bash
python manage.py runserver 8080
```
5. Levantar el Worker de Celery (Terminal 2):
```bash
celery -A dss_core worker -l info --pool=solo
```

## Endpoints Principales (API REST)
*   `POST /api/v1/init-simulacion/`: Limpia la base de datos y genera datos iniciales de camiones para el turno.
*   `POST /api/v1/simular-paso/`: Avanza el periodo actual y ejecuta la reoptimización en Celery. Retorna un identificador de tarea (`task_id`).
*   `GET /api/v1/task-status/<task_id>/`: Permite consultar el estado de finalización de una tarea en Celery.
*   `GET /api/v1/gantt/`: Retorna el estado actual del patio y las asignaciones estructuradas para su visualización.
*   `POST /api/v1/asignacion/fijar/`: Aplica un ajuste manual (Override) a un camión específico y desencadena una reoptimización instantánea para el resto.
