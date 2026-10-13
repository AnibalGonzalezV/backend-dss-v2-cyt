import os
import sys
import django

sys.path.append('/app')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dss_core.settings")
django.setup()

import time
import pyomo.environ as pyo
from api.models import Viaje, Instalacion
from datetime import datetime

def test_modelo():
    print("================================================================================")
    print(" PRUEBA DEL MODELO HÍBRIDO CON TOPOLOGÍA REAL DE BODEGA LONTUÉ")
    print("================================================================================")

    # 1. Cargar las 74 camiones que antes se quedaban en Drop
    viajes = list(Viaje.objects.filter(estado_actual__in=['ROMANA', 'PATIO'])[:20]) # Probar con 20 camiones
    print(f"Camiones a evaluar en la ventana: {len(viajes)}")

    T = list(range(1, 25))
    K = [f"V{v.id}" for v in viajes]
    w = {}
    Gk = {}
    Pk = {}
    c_espera = {}
    c_drop = {}
    tmin = {}

    for v in viajes:
        k = f"V{v.id}"
        p = v.pesajeromana_set.last()
        peso = float(p.peso_neto_kg) if p else 15000.0
        w[k] = peso
        Gk[k] = p.payload_original.get('grupo_informado', 'GENERICO') if p and p.payload_original else 'GENERICO'
        Pk[k] = 2
        tmin[k] = 1
        for t in T:
            c_espera[(k, t)] = (t - 1) * 1.5
        c_drop[k] = 100.0

    # 2. Topología Real
    pozos_qs = Instalacion.objects.filter(tipo='POZO')
    prensas_qs = Instalacion.objects.filter(tipo='PRENSA')
    J_pozos = [p.nombre for p in pozos_qs]
    J_prensas = [p.nombre for p in prensas_qs]
    Vmax = {inst.nombre: float(inst.cap_maxima) for inst in Instalacion.objects.all()}
    G = list(set(Gk.values()))

    # Capacidad agregada de bodega por grupo (230 cubas de 65,000 L repartidas entre 11 grupos)
    cap_bodega_grupo = {g: 1300000.0 for g in G} # 1.3 millones de litros por grupo

    print(f"Pozos ({len(J_pozos)}): {J_pozos}")
    print(f"Prensas ({len(J_prensas)}): {J_prensas}")
    print(f"Grupos activos ({len(G)}): {G}")

    # 3. Construir Modelo Pyomo Híbrido
    model = pyo.ConcreteModel()
    model.T = pyo.Set(initialize=T)
    model.K = pyo.Set(initialize=K)
    model.J_pozos = pyo.Set(initialize=J_pozos)
    model.J_prensas = pyo.Set(initialize=J_prensas)
    model.G = pyo.Set(initialize=G)
    model.Arcs = pyo.Set(dimen=2, initialize=[(p, pr) for p in J_pozos for pr in J_prensas])

    model.X = pyo.Var(model.K, model.J_pozos, model.T, domain=pyo.Binary)
    model.X_drop = pyo.Var(model.K, domain=pyo.Binary)
    model.W_pozo = pyo.Var(model.J_pozos, model.G, model.T, domain=pyo.Binary)
    model.S_pozo = pyo.Var(model.J_pozos, model.G, model.T, domain=pyo.NonNegativeReals)

    model.W_prensa = pyo.Var(model.J_prensas, model.G, model.T, domain=pyo.Binary)
    model.F = pyo.Var(model.Arcs, model.G, model.T, domain=pyo.NonNegativeReals)
    model.S_bodega = pyo.Var(model.G, model.T, domain=pyo.NonNegativeReals)

    # Restricciones
    # A. Indivisibilidad
    def indivisibilidad_rule(model, k):
        return sum(model.X[k, j, t] for j in model.J_pozos for t in model.T) + model.X_drop[k] == 1
    model.C_indivisibilidad = pyo.Constraint(model.K, rule=indivisibilidad_rule)

    # B. Bloqueo de pozos
    def bloqueo_rule(model, j, t):
        ocupacion = sum(
            model.X[k, j, tau]
            for k in model.K
            for tau in range(max(1, t - Pk[k] + 1), t + 1)
            if tau in model.T
        )
        return ocupacion <= 1
    model.C_bloqueo = pyo.Constraint(model.J_pozos, model.T, rule=bloqueo_rule)

    # C. Pureza en pozos
    def un_grupo_pozo_rule(model, j, t):
        return sum(model.W_pozo[j, g, t] for g in model.G) <= 1
    model.C_un_grupo_pozo = pyo.Constraint(model.J_pozos, model.T, rule=un_grupo_pozo_rule)

    def coincidencia_mezcla_rule(model, k, j, t):
        return model.X[k, j, t] <= model.W_pozo[j, Gk[k], t]
    model.C_coincidencia = pyo.Constraint(model.K, model.J_pozos, model.T, rule=coincidencia_mezcla_rule)

    # D. Balance en pozos
    def balance_pozo_rule(model, j, g, t):
        S_prev = 0 if t == 1 else model.S_pozo[j, g, t - 1]
        truck_in = sum(w[k] * model.X[k, j, t] for k in model.K if Gk[k] == g)
        pipe_out = sum(model.F[j, pr, g, t] for pr in model.J_prensas)
        return model.S_pozo[j, g, t] == S_prev + truck_in - pipe_out
    model.C_balance_pozo = pyo.Constraint(model.J_pozos, model.G, model.T, rule=balance_pozo_rule)

    def cap_max_pozo_rule(model, j, g, t):
        return model.S_pozo[j, g, t] <= (Vmax[j] * 1000) * model.W_pozo[j, g, t]
    model.C_cap_max_pozo = pyo.Constraint(model.J_pozos, model.G, model.T, rule=cap_max_pozo_rule)

    # E. Prensas dinámicas
    def un_grupo_prensa_rule(model, pr, t):
        return sum(model.W_prensa[pr, g, t] for g in model.G) <= 1
    model.C_un_grupo_prensa = pyo.Constraint(model.J_prensas, model.T, rule=un_grupo_prensa_rule)

    def coincidencia_prensa_rule(model, pr, g, t):
        flow_in = sum(model.F[p, pr, g, t] for p in model.J_pozos)
        return flow_in <= (Vmax[pr] * 1000) * model.W_prensa[pr, g, t]
    model.C_coinc_prensa = pyo.Constraint(model.J_prensas, model.G, model.T, rule=coincidencia_prensa_rule)

    # F. Balance de Bodega de Fermentación (Litros)
    rho_rendimiento = 0.6536 * 0.94 # Rendimiento de uva sólida a mosto fermentable
    def balance_bodega_rule(model, g, t):
        S_prev = 0 if t == 1 else model.S_bodega[g, t - 1]
        liquido_generado = sum(model.F[p, pr, g, t] * rho_rendimiento for p in model.J_pozos for pr in model.J_prensas)
        return model.S_bodega[g, t] == S_prev + liquido_generado
    model.C_balance_bodega = pyo.Constraint(model.G, model.T, rule=balance_bodega_rule)

    def cap_max_bodega_rule(model, g, t):
        return model.S_bodega[g, t] <= cap_bodega_grupo[g]
    model.C_cap_max_bodega = pyo.Constraint(model.G, model.T, rule=cap_max_bodega_rule)

    # G. Función Objetivo Normalizada
    total_w = sum(w.values()) if w else 1.0
    max_espera = max(c_espera.values()) if c_espera else 1.0
    max_drop = max(c_drop.values()) if c_drop else 1.0
    alpha_1, alpha_2, alpha_3 = 0.6, 0.1, 0.3
    C_wip = 0.05

    def funcion_objetivo_rule(model):
        ganancia_masa = sum((w[k]/total_w) * model.X[k, j, t] for k in model.K for j in model.J_pozos for t in model.T)
        penal_espera = sum((c_espera[(k, t)]/max_espera) * model.X[k, j, t] for k in model.K for j in model.J_pozos for t in model.T)
        penal_drop = sum((c_drop[k]/max_drop) * model.X_drop[k] for k in model.K)
        wip_pozos = sum(C_wip * model.W_pozo[j, g, t] for j in model.J_pozos for g in model.G for t in model.T)
        wip_prensas = sum(C_wip * model.W_prensa[pr, g, t] for pr in model.J_prensas for g in model.G for t in model.T)
        return (alpha_3 * ganancia_masa) - (alpha_1 * penal_espera) - (alpha_1 * penal_drop) - (alpha_2 * (wip_pozos + wip_prensas))

    model.Z = pyo.Objective(rule=funcion_objetivo_rule, sense=pyo.maximize)

    # 4. Resolver con HiGHS
    print("\n4. Resolviendo con HiGHS...")
    solver = pyo.SolverFactory('appsi_highs')
    solver.highs_options['time_limit'] = 15.0
    solver.highs_options['mip_rel_gap'] = 0.05

    t0 = time.time()
    res = solver.solve(model, tee=False)
    t_solve = time.time() - t0

    print(f"Tiempo de resolución: {t_solve:.3f} segundos")
    print(f"Estado: {res.solver.termination_condition}")
    print(f"Objetivo Z: {pyo.value(model.Z):.4f}")

    # 5. Análisis de Resultados
    drops = sum(1 for k in K if pyo.value(model.X_drop[k]) > 0.5)
    asignados = len(K) - drops
    print(f"\nCamiones asignados: {asignados} de {len(K)}")
    print(f"Camiones en Drop: {drops}")

    print("\nAsignaciones:")
    for k in K:
        if pyo.value(model.X_drop[k]) < 0.5:
            for j in J_pozos:
                for t in T:
                    if pyo.value(model.X[k, j, t]) > 0.5:
                        print(f" - Camión {k} ({Gk[k]}, {w[k]:,.0f} kg) -> {j} en T={t}")

    # Verificar mosto generado
    print("\nMosto generado acumulado por grupo en Bodega (Litros):")
    for g in G:
        mosto_final = pyo.value(model.S_bodega[g, 24])
        if mosto_final > 1.0:
            print(f" - {g}: {mosto_final:,.1f} L (Capacidad disponible: {cap_bodega_grupo[g]:,.0f} L)")

if __name__ == '__main__':
    test_modelo()
