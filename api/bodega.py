from api.models import GrupoMezcla, Instalacion

GRUPOS_MEZCLA = [f'BLOQUE-{i}' for i in range(1, 12)]

TOPOLOGIA_LONTE = {
    'POZO': 4,
    'PRENSA': 12,
    'CUBA_PF': 24,
    'FLOTACION': 4,
    'CUBA_F': 230,
}


def asegurar_grupos_mezcla():
    grupos = []
    for codigo in GRUPOS_MEZCLA:
        grupo, _ = GrupoMezcla.objects.get_or_create(
            codigo_material=codigo,
            defaults={'descripcion': f'Grupo de mezcla {codigo}'},
        )
        grupos.append(grupo)
    return grupos


def _get_or_create_inst(nombre, tipo, cap_maxima):
    inst, created = Instalacion.objects.get_or_create(
        nombre=nombre,
        defaults={'tipo': tipo, 'cap_maxima': cap_maxima, 'esta_activa': True},
    )
    if not created:
        dirty = False
        if inst.tipo != tipo:
            inst.tipo = tipo
            dirty = True
        if inst.cap_maxima != cap_maxima:
            inst.cap_maxima = cap_maxima
            dirty = True
        if not inst.esta_activa:
            inst.esta_activa = True
            dirty = True
        if dirty:
            inst.save()
    return inst


def asegurar_topologia_lontue():
    """Bodega uva blanca: 4 pozos → 12 prensas → 24 CubaPF → 4 flotación → 230 CubaF."""
    for i in range(1, TOPOLOGIA_LONTE['POZO'] + 1):
        _get_or_create_inst(f'P_{i:02d}', 'POZO', 50)
    for i in range(1, TOPOLOGIA_LONTE['PRENSA'] + 1):
        _get_or_create_inst(f'PR_{i:02d}', 'PRENSA', 100)
    for i in range(1, TOPOLOGIA_LONTE['CUBA_PF'] + 1):
        _get_or_create_inst(f'CubaPF_{i:02d}', 'CUBA', 50000)
    for i in range(1, TOPOLOGIA_LONTE['FLOTACION'] + 1):
        _get_or_create_inst(f'FLT_{i:02d}', 'CUBA', 50000)
    for i in range(1, TOPOLOGIA_LONTE['CUBA_F'] + 1):
        _get_or_create_inst(f'CubaF_{i:03d}', 'CUBA', 50000)


def clasificar_instalaciones(instalaciones):
    J, J_pozos, J_prensas, J_cubas_pf, J_flt, J_cubas_f = [], [], [], [], [], []
    Vmin, Vmax = {}, {}
    for inst in instalaciones:
        j_id = inst.nombre
        J.append(j_id)
        Vmin[j_id] = float(inst.cap_minima)
        Vmax[j_id] = float(inst.cap_maxima)
        if j_id.startswith('P_'):
            J_pozos.append(j_id)
        elif j_id.startswith('PR_'):
            J_prensas.append(j_id)
        elif j_id.startswith('CubaPF_'):
            J_cubas_pf.append(j_id)
        elif j_id.startswith('FLT_'):
            J_flt.append(j_id)
        elif j_id.startswith('CubaF_'):
            J_cubas_f.append(j_id)
    return {
        'J': J,
        'J_pozos': J_pozos,
        'J_prensas': J_prensas,
        'J_cubas_pf': J_cubas_pf,
        'J_flt': J_flt,
        'J_cubas_f': J_cubas_f,
        'Vmin': Vmin,
        'Vmax': Vmax,
    }
