import pyomo.environ as pyo


def build_dss_model(datos):
    """
    STN híbrido para uva blanca:
    - Pozos: micro-scheduling X[k,j,t]
    - Prensas / CubaPF / Flotación / CubaF: inventario macro, un grupo por máquina
    GPS no puede usar los intervalos inmediatos; nadie descarga antes de tmin (ETA o romana).
    """
    model = pyo.ConcreteModel()

    model.T = pyo.Set(initialize=datos['T'])
    model.K = pyo.Set(initialize=datos['K'])
    model.J = pyo.Set(initialize=datos['J'])
    model.J_pozos = pyo.Set(within=model.J, initialize=datos.get('J_pozos', []))
    model.J_prensas = pyo.Set(within=model.J, initialize=datos.get('J_prensas', []))
    model.J_cubas_pf = pyo.Set(within=model.J, initialize=datos.get('J_cubas_pf', []))
    model.J_flt = pyo.Set(within=model.J, initialize=datos.get('J_flt', []))
    model.J_cubas_f = pyo.Set(within=model.J, initialize=datos.get('J_cubas_f', []))
    model.G = pyo.Set(initialize=datos['G'])

    w = datos['w']
    Gk = datos['Gk']
    Pk = datos['Pk']
    Vmax = datos['Vmax']
    c_espera = datos['c_espera']
    tmin = datos.get('tmin', {})
    K_gps = set(datos.get('K_gps', []))
    T_commit = int(datos.get('T_commit', 2))

    alpha_1, alpha_2, alpha_3 = 0.6, 0.1, 0.3
    C_wip = 10

    def arcs_fast_init(model):
        return [(p, pr) for p in model.J_pozos for pr in model.J_prensas]

    def arcs_slow_init(model):
        arcs = []
        for pr in model.J_prensas:
            for cpf in model.J_cubas_pf:
                arcs.append((pr, cpf))
        for cpf in model.J_cubas_pf:
            for flt in model.J_flt:
                arcs.append((cpf, flt))
        for flt in model.J_flt:
            for cf in model.J_cubas_f:
                arcs.append((flt, cf))
        return arcs

    model.Arcs_fast = pyo.Set(dimen=2, initialize=arcs_fast_init)
    model.Arcs_slow = pyo.Set(dimen=2, initialize=arcs_slow_init)
    model.Arcs = model.Arcs_fast | model.Arcs_slow

    model.X = pyo.Var(model.K, model.J_pozos, model.T, domain=pyo.Binary)
    model.W_pozo = pyo.Var(model.J_pozos, model.G, model.T, domain=pyo.Binary)
    model.S_pozo = pyo.Var(model.J_pozos, model.G, model.T, domain=pyo.NonNegativeReals)

    lentas = list(model.J_prensas) + list(model.J_cubas_pf) + list(model.J_flt) + list(model.J_cubas_f)
    model.J_lentas = pyo.Set(within=model.J, initialize=lentas)

    model.W_maq = pyo.Var(model.J_lentas, model.G, domain=pyo.Binary)
    model.S_maq = pyo.Var(model.J_lentas, model.G, domain=pyo.NonNegativeReals)
    model.Q_in = pyo.Var(model.J_lentas, model.G, domain=pyo.NonNegativeReals)
    model.F = pyo.Var(model.Arcs_fast, model.G, model.T, domain=pyo.NonNegativeReals)
    model.F_slow = pyo.Var(model.Arcs_slow, model.G, domain=pyo.NonNegativeReals)

    def indivisibilidad_rule(model, k):
        return sum(model.X[k, j, t] for j in model.J_pozos for t in model.T) <= 1
    model.C_indivisibilidad = pyo.Constraint(model.K, rule=indivisibilidad_rule)

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

    def llegada_rule(model, k, j, t):
        t0 = tmin.get(k, 1)
        if t < t0:
            return model.X[k, j, t] == 0
        if k in K_gps and t <= T_commit:
            return model.X[k, j, t] == 0
        return pyo.Constraint.Skip
    model.C_llegada = pyo.Constraint(model.K, model.J_pozos, model.T, rule=llegada_rule)

    frozen_assignments = set(datos.get('frozen_assignments', []))
    def freeze_rule(model, k, j, t):
        if (k, j, t) in frozen_assignments:
            # Check feasibility: if a machine is blocked by a physical discharge delay, don't force freeze
            if t <= model.bloqueo_inicial[j]:
                return pyo.Constraint.Skip
            return model.X[k, j, t] == 1
        return pyo.Constraint.Skip
    model.C_freeze = pyo.Constraint(model.K, model.J_pozos, model.T, rule=freeze_rule)

    def un_grupo_pozo_rule(model, j, t):
        return sum(model.W_pozo[j, g, t] for g in model.G) <= 1
    model.C_un_grupo_pozo = pyo.Constraint(model.J_pozos, model.T, rule=un_grupo_pozo_rule)

    def un_grupo_maq_rule(model, j):
        return sum(model.W_maq[j, g] for g in model.G) <= 1
    model.C_un_grupo_maq = pyo.Constraint(model.J_lentas, rule=un_grupo_maq_rule)

    def coincidencia_mezcla_rule(model, k, j, t):
        return model.X[k, j, t] <= model.W_pozo[j, Gk[k], t]
    model.C_coincidencia = pyo.Constraint(model.K, model.J_pozos, model.T, rule=coincidencia_mezcla_rule)

    def balance_pozo_rule(model, j, g, t):
        S_prev = 0 if t == 1 else model.S_pozo[j, g, t - 1]
        truck_in = sum(w[k] * model.X[k, j, t] for k in model.K if Gk[k] == g)
        pipe_out = sum(model.F[j, j_out, g, t] for j_out in model.J_prensas if (j, j_out) in model.Arcs_fast)
        return model.S_pozo[j, g, t] == S_prev + truck_in - pipe_out
    model.C_balance_pozo = pyo.Constraint(model.J_pozos, model.G, model.T, rule=balance_pozo_rule)

    def q_in_rule(model, j, g):
        pipe_in = 0
        for j_in in model.J:
            if (j_in, j) in model.Arcs_fast:
                rho = 0.96 if j_in in model.J_pozos else 1.0
                pipe_in += sum(model.F[j_in, j, g, t] * rho for t in model.T)
            elif (j_in, j) in model.Arcs_slow:
                rho = 1.0
                if j_in in model.J_prensas:
                    rho = 0.6536
                elif j_in in model.J_flt:
                    rho = 0.94
                pipe_in += model.F_slow[j_in, j, g] * rho
        return model.Q_in[j, g] == pipe_in
    model.C_q_in = pyo.Constraint(model.J_lentas, model.G, rule=q_in_rule)

    def balance_lentas_rule(model, j, g):
        pipe_out = sum(model.F_slow[j, j_out, g] for j_out in model.J if (j, j_out) in model.Arcs_slow)
        return model.S_maq[j, g] == model.Q_in[j, g] - pipe_out
    model.C_balance_lentas = pyo.Constraint(model.J_lentas, model.G, rule=balance_lentas_rule)

    def transito_rule(model, j, g):
        if j not in model.J_cubas_f:
            return model.S_maq[j, g] == 0
        return pyo.Constraint.Skip
    model.C_transito = pyo.Constraint(model.J_lentas, model.G, rule=transito_rule)

    def cap_max_pozo_rule(model, j, g, t):
        return model.S_pozo[j, g, t] <= (Vmax[j] * 1000) * model.W_pozo[j, g, t]
    model.C_cap_max_pozo = pyo.Constraint(model.J_pozos, model.G, model.T, rule=cap_max_pozo_rule)

    def cap_max_maq_rule(model, j, g):
        return model.Q_in[j, g] <= (Vmax[j] * 1000) * model.W_maq[j, g]
    model.C_cap_max_maq = pyo.Constraint(model.J_lentas, model.G, rule=cap_max_maq_rule)

    def coincidencia_prensa_rule(model, j_in, j_out, g, t):
        if j_out not in model.J_prensas:
            return pyo.Constraint.Skip
        return model.F[j_in, j_out, g, t] <= (Vmax[j_out] * 1000) * model.W_maq[j_out, g]
    model.C_coinc_prensa = pyo.Constraint(model.Arcs_fast, model.G, model.T, rule=coincidencia_prensa_rule)

    def coincidencia_slow_rule(model, j_in, j_out, g):
        return model.F_slow[j_in, j_out, g] <= (Vmax[j_out] * 1000) * model.W_maq[j_out, g]
    model.C_coinc_slow = pyo.Constraint(model.Arcs_slow, model.G, rule=coincidencia_slow_rule)

    def funcion_objetivo_rule(model):
        ganancia_masa = sum(w[k] * model.X[k, j, t] for k in model.K for j in model.J_pozos for t in model.T)
        penalizacion_espera = sum(c_espera[(k, t)] * model.X[k, j, t] for k in model.K for j in model.J_pozos for t in model.T)
        costo_wip_pozos = sum(C_wip * model.W_pozo[j, g, t] for j in model.J_pozos for g in model.G for t in model.T)
        costo_wip_lentas = sum(C_wip * model.W_maq[j, g] for j in model.J_lentas for g in model.G)
        return (alpha_3 * 100 * ganancia_masa) - (alpha_1 * penalizacion_espera) - (alpha_2 * (costo_wip_pozos + costo_wip_lentas))

    model.Z = pyo.Objective(rule=funcion_objetivo_rule, sense=pyo.maximize)
    return model
