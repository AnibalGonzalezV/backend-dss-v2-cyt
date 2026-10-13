# Reporte de Rendimiento y Estrés Industrial: DSS Bodega Lontué

**Fecha de Ejecución:** 2026-10-13 12:30
**Escenario de Prueba:** `GPS_JITTER`
**Semilla Experimental:** `42`
**Universo de Entrada:** 85 camiones (Turno oficial de vendimia)

---

## 1. Resumen Ejecutivo de Métricas Clave

| Métrica Crítica | Valor Obtenido | Umbral de Aceptación (SLA) | Estado |
| :--- | :--- | :--- | :--- |
| **Throughput Procesado** | **85 de 85 camiones** (100.0%) | $>= 90%$ del turno | APROBADO |
| **Masa Total Procesada** | **1,370.0 Ton** | Concordante con recepción | APROBADO |
| **Solver Time Promedio ($t_{avg}$)** | **6.793 segundos** | $<= 15.0$ s | APROBADO |
| **Solver Time Percentil 95 ($P_{95}$)** | **16.063 segundos** | $<= 45.0$ s | APROBADO |
| **Solver Time Pico Máximo ($t_{max}$)** | **16.195 segundos** | $<= 60.0$ s (Límite HiGHS) | APROBADO |
| **Cumplimiento SLA Solver (< 60s)** | **100.0%** | $100%$ | APROBADO |
| **Espera Máxima en Patio** | **1.81 horas** | $<= 3.0$ hrs en hora punta | APROBADO |
| **Violaciones Físicas de Pozo** | **0 solapamientos** | 0 estricto | APROBADO |
| **Infeasibility Errors** | **0 errores** | 0 estricto | APROBADO |

---

## 2. Telemetría Horaria Consolidada

| Hora | Solver Time (s) | Patio | Descarga | En Ruta | Finalizados | Espera Máx (h) | Toneladas | Overlaps |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 10:00 | 6.07s | 0 | 2 | 7 | 1 | 0.0h | 15.6 | 0 |
| 11:00 | 4.04s | 0 | 1 | 12 | 5 | 0.0h | 79.9 | 0 |
| 12:00 | 3.34s | 0 | 4 | 13 | 7 | 0.0h | 123.9 | 0 |
| 13:00 | 6.66s | 1 | 3 | 14 | 12 | 0.18h | 225.9 | 0 |
| 14:00 | 4.14s | 2 | 4 | 11 | 19 | 0.41h | 327.2 | 0 |
| 15:00 | 6.63s | 1 | 4 | 16 | 27 | 0.21h | 462.9 | 0 |
| 16:00 | 16.01s | 2 | 4 | 27 | 32 | 0.2h | 540.6 | 0 |
| 17:00 | 16.06s | 3 | 3 | 24 | 40 | 0.15h | 669.8 | 0 |
| 18:00 | 12.14s | 13 | 4 | 12 | 47 | 0.73h | 780.0 | 0 |
| 19:00 | 11.16s | 12 | 4 | 9 | 55 | 1.35h | 899.8 | 0 |
| 20:00 | 3.12s | 11 | 4 | 4 | 63 | 1.81h | 1017.9 | 0 |
| 21:00 | 1.81s | 4 | 4 | 5 | 71 | 1.42h | 1135.5 | 0 |
| 22:00 | 1.97s | 0 | 2 | 3 | 79 | 0.0h | 1279.8 | 0 |
| 23:00 | 0.37s | 0 | 0 | 1 | 84 | 0.0h | 1354.2 | 0 |
| 00:00 | 0.00s | 0 | 0 | 0 | 85 | 0.0h | 1370.0 | 0 |


---

## 3. Análisis Crítico de Resultados

### 3.1. Escalabilidad Computacional (MILP con 1.056 Variables Binarias)
La refactorización tetradimensional de las prensas (`W_maq[j, g, t]`) no degradó el tiempo de resolución por debajo del límite operativo. El solver HiGHS resolvió cada ciclo con un promedio de **6.79 segundos**, alcanzando su pico máximo en las horas punta (16.20 s), muy por debajo del tiempo de ciclo de 15 minutos. Esto confirma que el DSS opera en **tiempo real estricto**.

### 3.2. Gobernanza de Patio y Política FIFO
La espera máxima en patio no superó las **1.81 horas**, demostrando que la normalización cuadrática de la función objetivo prioriza efectivamente a los camiones en espera frente a las proyecciones en ruta, evitando estancamiento de uva.

### 3.3. Integridad y Resiliencia
* **Consistencia de Pozos:** Cero violaciones de capacidad en los 4 pozos a lo largo de todo el turno.
* **Manejo de Perturbaciones:** El sistema operó de forma continua bajo el escenario evaluado.
