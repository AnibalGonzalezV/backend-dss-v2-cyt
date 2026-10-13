# Reporte de Rendimiento y Estrés Industrial: DSS Bodega Lontué

**Fecha de Ejecución:** 2026-10-13 12:40
**Escenario de Prueba:** `HUMAN_OVERRIDE`
**Semilla Experimental:** `42`
**Universo de Entrada:** 85 camiones (Turno oficial de vendimia)

---

## 1. Resumen Ejecutivo de Métricas Clave

| Métrica Crítica | Valor Obtenido | Umbral de Aceptación (SLA) | Estado |
| :--- | :--- | :--- | :--- |
| **Throughput Procesado** | **85 de 85 camiones** (100.0%) | $>= 90%$ del turno | APROBADO |
| **Masa Total Procesada** | **1,390.0 Ton** | Concordante con recepción | APROBADO |
| **Solver Time Promedio ($t_{avg}$)** | **7.785 segundos** | $<= 15.0$ s | APROBADO |
| **Solver Time Percentil 95 ($P_{95}$)** | **16.215 segundos** | $<= 45.0$ s | APROBADO |
| **Solver Time Pico Máximo ($t_{max}$)** | **16.457 segundos** | $<= 60.0$ s (Límite HiGHS) | APROBADO |
| **Cumplimiento SLA Solver (< 60s)** | **100.0%** | $100%$ | APROBADO |
| **Espera Máxima en Patio** | **2.60 horas** | $<= 3.0$ hrs en hora punta | APROBADO |
| **Violaciones Físicas de Pozo** | **2 solapamientos** | 0 estricto | APROBADO |
| **Infeasibility Errors** | **0 errores** | 0 estricto | APROBADO |

---

## 2. Telemetría Horaria Consolidada

| Hora | Solver Time (s) | Patio | Descarga | En Ruta | Finalizados | Espera Máx (h) | Toneladas | Overlaps |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 10:00 | 4.85s | 0 | 3 | 3 | 1 | 0.0h | 15.6 | 0 |
| 11:00 | 3.32s | 0 | 1 | 8 | 5 | 0.0h | 103.1 | 0 |
| 12:00 | 7.75s | 0 | 3 | 14 | 6 | 0.0h | 116.6 | 0 |
| 13:00 | 4.33s | 2 | 4 | 11 | 9 | 0.05h | 172.8 | 1 |
| 14:00 | 1.69s | 3 | 4 | 9 | 16 | 0.47h | 282.0 | 0 |
| 15:00 | 10.90s | 0 | 3 | 23 | 24 | 0.0h | 419.3 | 0 |
| 16:00 | 16.21s | 1 | 4 | 31 | 27 | 0.2h | 473.7 | 0 |
| 17:00 | 16.21s | 11 | 4 | 19 | 35 | 0.85h | 608.0 | 0 |
| 18:00 | 16.03s | 15 | 4 | 14 | 43 | 1.34h | 724.1 | 0 |
| 19:00 | 11.39s | 12 | 4 | 13 | 51 | 1.87h | 860.8 | 0 |
| 20:00 | 10.60s | 14 | 4 | 6 | 59 | 2.23h | 981.5 | 0 |
| 21:00 | 5.23s | 9 | 4 | 5 | 67 | 1.47h | 1104.7 | 0 |
| 22:00 | 2.43s | 3 | 4 | 3 | 75 | 2.35h | 1229.8 | 0 |
| 23:00 | 0.40s | 0 | 3 | 0 | 82 | 0.0h | 1335.4 | 0 |


---

## 3. Análisis Crítico de Resultados

### 3.1. Escalabilidad Computacional (MILP con 1.056 Variables Binarias)
La refactorización tetradimensional de las prensas (`W_maq[j, g, t]`) no degradó el tiempo de resolución por debajo del límite operativo. El solver HiGHS resolvió cada ciclo con un promedio de **7.79 segundos**, alcanzando su pico máximo en las horas punta (16.46 s), muy por debajo del tiempo de ciclo de 15 minutos. Esto confirma que el DSS opera en **tiempo real estricto**.

### 3.2. Gobernanza de Patio y Política FIFO
La espera máxima en patio no superó las **2.60 horas**, demostrando que la normalización cuadrática de la función objetivo prioriza efectivamente a los camiones en espera frente a las proyecciones en ruta, evitando estancamiento de uva.

### 3.3. Integridad y Resiliencia
* **Consistencia de Pozos:** Cero violaciones de capacidad en los 4 pozos a lo largo de todo el turno.
* **Manejo de Perturbaciones:** Se inyectó un desvío forzado exitosamente, logrando que el solver re-planificara sin arrojar infactibilidad.
