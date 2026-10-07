# DSS Backend (Advanced Planning & Scheduling)

Este repositorio contiene el backend del **Sistema de Soporte de Decisiones (DSS)** diseñado para la optimización de patios de recepción de uva (Bodega Lontué). Utiliza Inteligencia Artificial Matemática (MILP) para planificar de forma óptima el flujo logístico de camiones.

## 🚀 Arquitectura Tecnológica
El proyecto está estructurado de manera modular y escalable:
*   **Framework Core:** Django 5.0 + Django REST Framework.
*   **Motor de Optimización (IA Matemática):** Pyomo + HiGHS Solver (`highspy`).
*   **Procesamiento Asíncrono (Game Loop):** Celery + Redis.
*   **Base de Datos:** Configurado para PostgreSQL/SQLite (actualmente usando SQLite local para desarrollo rápido).

## 📂 Estructura de Directorios Clave
*   `api/`: Lógica central del sistema (Core App).
    *   `models.py`: Estructura relacional de Datos (Viajes, Camiones, Grupos de Mezcla, Asignaciones).
    *   `views.py`: Endpoints REST consumidos por el Frontend (React).
    *   `tasks.py`: Tareas asíncronas de Celery (`simular_paso_task`, `recalcular_gantt_task`).
    *   `management/commands/`: Scripts de CLI y carga inicial.
        *   `ejecutar_optimizador.py`: **[Core]** Pre-procesa los datos, consolida restricciones manuales (Time Fences y Pines) y llama al solver matemático.
        *   `cargar_programa.py` / `importar_maquinas.py`: Scripts de carga de maestros (Excel).
*   `optimization/`:
    *   `pyomo_model.py`: **[Core Matemático]** Contiene la formulación MILP (Programación Lineal Entera Mixta). Define Conjuntos, Parámetros, Variables, Función Objetivo y Restricciones.
*   `dss_core/`: Configuraciones de Django y Celery.

## ⚙️ Principios de Diseño
1.  **Event-Driven / Desacoplado:** El motor de optimización matemática pesado (que puede tardar entre 1 y 5 segundos) está desacoplado del ciclo HTTP usando Celery. Las APIs responden con `HTTP 202 Accepted` y delegan la carga algorítmica al Worker.
2.  **State Handoff (Time Fences):** Resuelve el problema del "Nerviosismo del Sistema". Camiones a menos de 30 minutos de descargar o con *Override Manual (Pinned)* se pasan como variables hardcodeadas ($X_{k,j,t} = 1$) al modelo matemático para no romper la continuidad operativa.
3.  **Human-in-the-Loop:** Soporte nativo para intervenciones humanas (Drag & Drop en UI) mediante el flag `override_manual`. El optimizador reconstruye el puzzle esquivando las decisiones bloqueadas por el humano.

## 💻 Guía de Instalación (Local)

### Requisitos Previos
*   Docker y Docker Compose (Recomendado)
*   Python 3.10+ (Si se ejecuta de forma nativa)

### Opción 1: Levantar con Docker (Recomendado)
El proyecto incluye un `docker-compose.yml` que levanta el entorno de Django (web), Celery (worker) y Redis (broker).

```bash
# 1. Construir y levantar contenedores
docker-compose up --build -d

# 2. Ejecutar migraciones de base de datos
docker-compose exec web python manage.py migrate

# 3. (Opcional) Cargar datos maestros (Si la BD está vacía)
docker-compose exec web python manage.py importar_maquinas
docker-compose exec web python manage.py cargar_programa "Programa Vendimia 2024.xlsx"
```
El backend estará disponible en: `http://localhost:8080`

### Opción 2: Levantar Nativo (Sin Docker)
1. Instala un servidor Redis y asegúrate de que esté corriendo en `localhost:6379`.
2. Crea tu entorno virtual e instala dependencias:
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Ejecuta migraciones:
   ```bash
   python manage.py migrate
   ```
4. Levanta el servidor Django (Terminal 1):
   ```bash
   python manage.py runserver 8080
   ```
5. Levanta el Worker de Celery (Terminal 2):
   ```bash
   celery -A dss_core worker -l info --pool=solo
   ```

## 📡 Endpoints Principales (API REST)
*   `POST /api/v1/init-simulacion/`: Limpia la BD y genera ~85 camiones (Programa + Genéricos) para el turno.
*   `POST /api/v1/simular-paso/`: Avanza el reloj virtual 15 min y desencadena la re-optimización vía Celery. Devuelve un `task_id`.
*   `GET /api/v1/task-status/<task_id>/`: Polling endpoint para consultar si Celery finalizó la tarea.
*   `GET /api/v1/gantt/`: Retorna el estado actual del patio, KPIs y asignaciones serializadas para la Carta Gantt.
*   `POST /api/v1/asignacion/fijar/`: Aplica un Override Manual a un camión (lo bloquea en un pozo/hora específico) y desencadena una re-optimización instantánea en cascada (`recalcular_gantt_task`).
