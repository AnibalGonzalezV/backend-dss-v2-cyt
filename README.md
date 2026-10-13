# DSS Backend - Planning & Scheduling (Bodega Lontué)

Backend del Sistema de Soporte a la Decisión (DSS v2.0) para la recepción, pesaje y asignación óptima de uva en la Bodega Lontué (Viña Concha y Toro). Desarrollado con Django, Pyomo, HiGHS Solver, Celery y PostgreSQL en arquitectura contenerizada.

---

## 1. Arquitectura y Tecnologías
* **Framework:** Django 5.0 y Django REST Framework.
* **Motor de Optimización Matemática:** Pyomo 6.7+ con solver HiGHS (`appsi_highs` / `highspy`).
* **Base de Datos:** PostgreSQL 15 (Docker) persistente en volumen `dss_v2_pgdata`.
* **Procesamiento Asíncrono y Cache:** Celery y Redis 7 (Docker).
* **Control Predictivo:** Rolling Horizon MPC (Model Predictive Control) con pasos de tiempo discretos ($\Delta t = 10\text{ min}$).
* **Modelo Híbrido Desacoplado:** Micro-scheduling binario en pozos y prensas con balance volumétrico continuo de bodega ($S_{\text{bodega}}$).

---

## 2. Topología de Planta Soportada
El sistema integra los **274 activos industriales reales** de Bodega Lontué catastrados en `settings.xlsx`:
* **4 Pozos de Recepción:** `P_01`, `P_02`, `P_03`, `P_04` (Cota: 50 Ton / $50.000\text{ kg}$).
* **12 Prensas Neumáticas:** `PR_01` a `PR_12` (Cota: 80 Ton / $80.000\text{ kg}$ cada una).
* **24 Cubas de Pre-flotación (`CubaPF`):** $50.000\text{ L}$ c/u.
* **4 Flotadores Continuos (`FLT`):** $50.000\text{ L}$ c/u.
* **230 Cubas de Fermentación (`CubaF_01` a `CubaF_230`):** $65.000\text{ L}$ c/u ($\approx 14.950.000\text{ L}$ totales).

---

## 3. Guía de Instalación y Despliegue con Docker (Recomendado)

### 3.1. Requisitos Previos
* Docker Engine 20.10+ y Docker Compose v2.
* Git.
* Puertos libres en el host: `8080` (Web), `5433` (Postgres), `6380` (Redis).

> **Nota sobre Puertos:** Se configuraron puertos alternativos en el host (`8080`, `5433`, `6380`) para evitar cualquier colisión si la máquina anfitriona ya tiene instancias locales de PostgreSQL (5432), Redis (6379) o Gunicorn (8000).

### 3.2. Construcción y Puesta en Marcha
1. Clonar el repositorio y posicionarse en el directorio raíz del backend:
```bash
cd dss_v2_backend
```

2. Construir y levantar los 4 contenedores en segundo plano (`db`, `redis`, `web`, `worker`):
```bash
docker-compose up --build -d
```

3. Verificar que todos los contenedores estén en estado `Up`:
```bash
docker ps
```
Debe listar: `dss_v2_web` (8080->8000), `dss_v2_worker`, `dss_v2_redis` (6380->6379), `dss_v2_db` (5433->5432).

### 3.3. Inicialización y Carga de Datos Maestros
Ejecutar los siguientes comandos en orden estricto dentro del contenedor:

1. **Aplicar migraciones relacionales:**
```bash
docker-compose exec web python manage.py migrate
```

2. **Importar la topología física real (274 maquinarias):**
```bash
docker-compose exec web python manage.py importar_maquinas settings.xlsx
```

3. **Cargar el programa de vendimia oficial:**
```bash
docker-compose exec web python manage.py cargar_programa "Programa Vendimia 2024.xlsx"
```

El backend quedará operativo y escuchando peticiones en:
```text
http://localhost:8080/
```

---

## 4. Ejecución de Pruebas y Benchmarking Industrial

El repositorio incluye un arnés de simulación y benchmarking para validar el comportamiento del solver HiGHS y los algoritmos de control ante 85 camiones:

### 4.1. Verificación Rápida del Modelo Híbrido
Valida que el solver HiGHS resuelva la ventana crítica sin colapsar:
```bash
docker-compose exec web python test_nuevo_modelo_hibrido.py
```

### 4.2. Ejecución de la Suite Completa de Rendimiento
El comando `ejecutar_benchmark` ejecuta una simulación discreta de 65 ticks de 15 minutos (turno completo de 09:00 a 23:30):

* **Escenario 1 (Nominal):**
```bash
docker-compose exec web python manage.py ejecutar_benchmark --camiones 85 --scenario nominal
```

* **Escenario 2 (Incertidumbre GPS Jitter con retrasos en ruta):**
```bash
docker-compose exec web python manage.py ejecutar_benchmark --camiones 85 --scenario gps_jitter
```

* **Escenario 3 (Intervención y Desvío Forzado Human Override):**
```bash
docker-compose exec web python manage.py ejecutar_benchmark --camiones 85 --scenario human_override
```

Los reportes consolidados y archivos CSV de telemetría se generan automáticamente en la raíz del contenedor (`/app`).

---

## 5. Endpoints REST Principales
| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `POST` | `/api/v1/init-simulacion/` | Reinicia la base de datos (Clean Slate) y programa 85 camiones con curvas horarias de vendimia. |
| `POST` | `/api/v1/simular-paso/` | Avanza el reloj virtual 15 minutos y dispara el cálculo del solver HiGHS. |
| `GET` | `/api/v1/gantt/` | Retorna las asignaciones temporales de pozos y colas de patio estructuradas para el Frontend. |
| `POST` | `/api/v1/asignacion/fijar/` | Aplica una restricción dura manual (*Time Fence / Override*) sobre un camión. |
| `POST` | `/api/v1/recepcion/gps/` | Ingesta webhook de aviso anticipado de camión en ruta. |
| `POST` | `/api/v1/recepcion/romana/` | Ingesta pesaje definitivo de báscula (fuente de verdad $w_k$). |

---

## 6. Despliegue Nativo (Sin Docker)
En caso de ejecutar fuera de contenedores:
1. Asegurar un PostgreSQL local activo en el puerto `5433` con base de datos `dss_v2_db`, usuario `dss_user`, password `dss_password`.
2. Asegurar un Redis activo en el puerto `6380`.
3. Crear entorno virtual e instalar requerimientos:
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py importar_maquinas settings.xlsx
```
4. Iniciar el servidor web:
```bash
python manage.py runserver 8080
```
5. Iniciar el worker de Celery (Terminal separada):
```bash
celery -A dss_core worker -l info --pool=solo
```

---

## 7. Solución de Problemas Frecuentes (Troubleshooting)
* **Error `port already in use`:** Si Docker falla al levantar, verificar que no existan contenedores antiguos ocupando los puertos:
  ```bash
  docker ps
  # Detener procesos en conflicto o reconfigurar puertos en docker-compose.yml
  ```
* **Error de conexión a PostgreSQL:** El servicio `web` depende de `db`. Si la base de datos demora en inicializar, esperar 10 segundos y reintentar `docker-compose exec web python manage.py migrate`.
* **Pyomo / Solver HiGHS:** El binario de HiGHS se compila e instala automáticamente mediante el paquete `highspy` en Python. No requiere instalación de librerías nativas adicionales del sistema operativo.
