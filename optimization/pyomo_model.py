import pyomo.environ as pyo


def build_dss_model(datos):
    """
    Modelo MILP Híbrido Desacoplado para Bodega Lontué (Uva Blanca):
    - Pozos (4): Micro-scheduling binario X[k, j, t] y exclusividad W_pozo[j, g, t].
    - Prensas (12): Secuenciación temporal de prensado W_prensa[pr, g, t] (Cota: 80 Ton).
    - Bodega (230 Cubas F): Balance de almacenamiento acumulado de mosto (L) sin explosión combinatoria.
    - Cero colapso: Desacopla la dinámica rápida (patio/prensas) de la dinámica lenta (bodega).
    """
    model = pyo.ConcreteModel()

    model.T = pyo.Set(initialize=datos['T'])
    model.K = pyo.Set(initialize=datos['K'])
    model.J_pozos = pyo.Set(initialize=datos['J_pozos'])
    model.J_prensas = pyo.Set(initialize=datos['J_prensas'])
    model.G = pyo.Set(initialize=datos['G'])
    model.Arcs = pyo.Set(dimen=2, initialize=[(p, pr) for p in datos['J_pozos'] for pr in datos['J_prensas']])

    w = datos['w']
    Gk = datos['Gk']
    Pk = datos['Pk']
    Vmax = datos['Vmax']
    c_espera = datos['c_espera']
    c_drop = datos.get('c_drop', {})
    
    # Parámetros de normalización
    total_w = datos.get('total_w', 1.0)
    max_espera = datos.get('max_espera', 1.0)
    max_drop = datos.get('max_drop', 1.0)
    tmin = datos.get('tmin', {})
    K_gps = set(datos.get('K_gps', []))
    T_commit = int(datos.get('T_commit', 2))
    cap_bodega_grupo = datos.get('cap_bodega_grupo', {g: 1300000.0 for g in datos['G']})

    alpha_1, alpha_2, alpha_3 = 0.6, 0.1, 0.3
    C_wip = 0.05

    # -------------------------------------------------------------
    # VARIABLES DE DECISIÓN
    # -------------------------------------------------------------
    # 1. Pozos y Asignación de Camiones
    model.X = pyo.Var(model.K, model.J_pozos, model.T, domain=pyo.Binary)
    model.X_drop = pyo.Var(model.K, domain=pyo.Binary)
    model.W_pozo = pyo.Var(model.J_pozos, model.G, model.T, domain=pyo.Binary)
    model.S_pozo = pyo.Var(model.J_pozos, model.G, model.T, domain=pyo.NonNegativeReals)

    # 2. Prensas Industriales (Secuenciación Temporal)
    model.W_prensa = pyo.Var(model.J_prensas, model.G, model.T, domain=pyo.Binary)
    model.F = pyo.Var(model.Arcs, model.G, model.T, domain=pyo.NonNegativeReals)

    # 3. Bodega de Fermentación (Balance Volumétrico en Litros)
    model.S_bodega = pyo.Var(model.G, model.T, domain=pyo.NonNegativeReals)

    # -------------------------------------------------------------
    # RESTRICCIONES DE RECEPCIÓN Y POZOS
    # -------------------------------------------------------------
    # Indivisibilidad (o descarga en un pozo o va a Nodo Futuro)
    def indivisibilidad_rule(model, k):
        return sum(model.X[k, j, t] for j in model.J_pozos for t in model.T) + model.X_drop[k] == 1
    model.C_indivisibilidad = pyo.Constraint(model.K, rule=indivisibilidad_rule)

    # Bloqueo y Ocupación de Pozos
    model.bloqueo_inicial = pyo.Param(model.J_pozos, initialize=datos.get('bloqueo_inicial', {}), default=0)
    def bloqueo_rule(model, j, t):
        ocupacion = sum(
            model.X[k, j, tau]
            for k in model.K
            for tau in range(max(1, t - Pk[k] + 1), t + 1)
            if tau in model.T
        )
        if t <= model.bloqueo_inicial[j]:
            return ocupacion == 0
        return ocupacion <= 1
    model.C_bloqueo = pyo.Constraint(model.J_pozos, model.T, rule=bloqueo_rule)

    # Llegada y ETA
    def llegada_rule(model, k, j, t):
        t0 = tmin.get(k, 1)
        if t < t0:
            return model.X[k, j, t] == 0
        if k in K_gps and t <= T_commit:
            return model.X[k, j, t] == 0
        return pyo.Constraint.Skip
    model.C_llegada = pyo.Constraint(model.K, model.J_pozos, model.T, rule=llegada_rule)

    # Asignaciones Congeladas / Override Manual
    frozen_assignments = set(datos.get('frozen_assignments', []))
    def freeze_rule(model, k, j, t):
        if (k, j, t) in frozen_assignments:
            if t <= model.bloqueo_inicial[j]:
                return pyo.Constraint.Skip
            return model.X[k, j, t] == 1
        return pyo.Constraint.Skip
    model.C_freeze = pyo.Constraint(model.K, model.J_pozos, model.T, rule=freeze_rule)

    # Pureza en Pozo
    def un_grupo_pozo_rule(model, j, t):
        return sum(model.W_pozo[j, g, t] for g in model.G) <= 1
    model.C_un_grupo_pozo = pyo.Constraint(model.J_pozos, model.T, rule=un_grupo_pozo_rule)

    def coincidencia_mezcla_rule(model, k, j, t):
        return model.X[k, j, t] <= model.W_pozo[j, Gk[k], t]
    model.C_coincidencia = pyo.Constraint(model.K, model.J_pozos, model.T, rule=coincidencia_mezcla_rule)

    # Balance de Masa en Pozo (kg)
    def balance_pozo_rule(model, j, g, t):
        S_prev = 0 if t == 1 else model.S_pozo[j, g, t - 1]
        truck_in = sum(w[k] * model.X[k, j, t] for k in model.K if Gk[k] == g)
        pipe_out = sum(model.F[j, pr, g, t] for pr in model.J_prensas)
        return model.S_pozo[j, g, t] == S_prev + truck_in - pipe_out
    model.C_balance_pozo = pyo.Constraint(model.J_pozos, model.G, model.T, rule=balance_pozo_rule)

    def cap_max_pozo_rule(model, j, g, t):
        return model.S_pozo[j, g, t] <= (Vmax[j] * 1000) * model.W_pozo[j, g, t]
    model.C_cap_max_pozo = pyo.Constraint(model.J_pozos, model.G, model.T, rule=cap_max_pozo_rule)

    # -------------------------------------------------------------
    # RESTRICCIONES DE PRENSAS DINÁMICAS (12 PRENSAS REALES)
    # -------------------------------------------------------------
    # Exclusividad de grupo por intervalo en cada prensa
    def un_grupo_prensa_rule(model, pr, t):
        return sum(model.W_prensa[pr, g, t] for g in model.G) <= 1
    model.C_un_grupo_prensa = pyo.Constraint(model.J_prensas, model.T, rule=un_grupo_prensa_rule)

    # Coincidencia y Cota de Prensa (80 Ton = 80.000 kg)
    def coincidencia_prensa_rule(model, pr, g, t):
        flow_in = sum(model.F[p, pr, g, t] for p in model.J_pozos)
        return flow_in <= (Vmax[pr] * 1000) * model.W_prensa[pr, g, t]
    model.C_coinc_prensa = pyo.Constraint(model.J_prensas, model.G, model.T, rule=coincidencia_prensa_rule)

    # -------------------------------------------------------------
    # BODEGA DE FERMENTACIÓN (BALANCE VOLUMÉTRICO EN LITROS)
    # -------------------------------------------------------------
    rho_rendimiento = 0.6536 * 0.94 # Rendimiento efectivo uva sólida a mosto clarificado
    def balance_bodega_rule(model, g, t):
        S_prev = 0 if t == 1 else model.S_bodega[g, t - 1]
        liquido_generado = sum(model.F[p, pr, g, t] * rho_rendimiento for p in model.J_pozos for pr in model.J_prensas)
        return model.S_bodega[g, t] == S_prev + liquido_generado
    model.C_balance_bodega = pyo.Constraint(model.G, model.T, rule=balance_bodega_rule)

    def cap_max_bodega_rule(model, g, t):
        return model.S_bodega[g, t] <= cap_bodega_grupo[g]
    model.C_cap_max_bodega = pyo.Constraint(model.G, model.T, rule=cap_max_bodega_rule)

    # -------------------------------------------------------------
    # FUNCIÓN OBJETIVO NORMALIZADA ESTRICTA [0, 1]
    # -------------------------------------------------------------
    def funcion_objetivo_rule(model):
        ganancia_masa = sum((w[k]/total_w) * model.X[k, j, t] for k in model.K for j in model.J_pozos for t in model.T)
        penal_espera = sum((c_espera[(k, t)]/max_espera) * model.X[k, j, t] for k in model.K for j in model.J_pozos for t in model.T)
        penal_drop = sum((c_drop[k]/max_drop) * model.X_drop[k] for k in model.K)
        wip_pozos = sum(C_wip * model.W_pozo[j, g, t] for j in model.J_pozos for g in model.G for t in model.T)
        wip_prensas = sum(C_wip * model.W_prensa[pr, g, t] for pr in model.J_prensas for g in model.G for t in model.T)
        return (alpha_3 * ganancia_masa) - (alpha_1 * penal_espera) - (alpha_1 * penal_drop) - (alpha_2 * (wip_pozos + wip_prensas))

    model.Z = pyo.Objective(rule=funcion_objetivo_rule, sense=pyo.maximize)
    return model
