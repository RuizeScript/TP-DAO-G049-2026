"""
Reportes de gestión: se verifican con un escenario chico y controlado (fechas fijas), con los valores esperados
calculados a mano, y con los datos demo para asegurar que cargan y que los reportes funcionan sobre ellos.
"""
import pytest
from datetime import date, datetime, time, timedelta

from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.enum import Estado
from models.datos_demo import cargar_datos_iniciales
from models.reportes import Reportes, formatear_duracion
import reportes_pdf

HOY = date(2026, 6, 15)


def hace(dias, hora=9):
    return datetime.combine(HOY - timedelta(days=dias), time(hora, 0))


def dias_atras(n):
    return HOY - timedelta(days=n)


@pytest.fixture
def escenario():
    """
    Red de 4 sedes (A, B, C sin stock, D inactiva), 6 ejemplares de 2 títulos y 7 préstamos:
      P1 local vencido (6 d) | P2 A->B recibido (a tiempo, por vencer) | P3 A->B despachado hace 4 d (estancado)
      P4 y P7 B->A en el MISMO remito abierto (2 ejemplares) | P5 devuelto tarde | P6 devuelto en término
    """
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    a = g.agregar_sede(Sede(nombre="A", horarios="Lun a Vie 09:00 - 18:00", activa=True))
    b = g.agregar_sede(Sede(nombre="B", horarios="Lun a Vie 09:00 - 18:00", activa=True))
    g.agregar_sede(Sede(nombre="C", horarios="Lun a Vie 09:00 - 18:00", activa=True))
    g.agregar_sede(Sede(nombre="D", horarios="Lun a Vie 09:00 - 18:00", activa=False, comentarios="En refacción"))
    s = [g.agregar_socio(Socio(nombre=f"S{i}", apellido="Test", dni=f"2000000{i}", email=f"s{i}@t.com")) for i in range(4)]
    l1 = g.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="Herbert"))
    l2 = g.agregar_libro(Libro(isbn="978-2", titulo="Neuromante", autor="Gibson"))
    a1, a2, a3, a4 = (g.agregar_ejemplar(Ejemplar(libro=l1, sede=a)) for _ in range(4))
    b1, b2 = (g.agregar_ejemplar(Ejemplar(libro=l2, sede=b)) for _ in range(2))

    def prestar(id_p, socio, ej, origen, destino, plazo, inicio):
        g.crear_prestamo(id_prestamo=id_p, id_socio=socio.id_socio, id_ejemplar=ej.id_ejemplar,
                         id_sede_origen=origen.id_sede, id_sede_destino=destino.id_sede,
                         dias_prestamo=plazo, fecha_inicio=dias_atras(inicio))

    # Historial ya resuelto
    prestar("P5", s[1], a4, a, a, 7, 30)
    g.registrar_devolucion("P5", dias_atras(20), Estado.BUENO)      # vencía hace 23 d -> 3 días tarde
    prestar("P6", s[2], a4, a, a, 7, 15)
    g.registrar_devolucion("P6", dias_atras(10), Estado.OPTIMO)     # vencía hace 8 d -> en término

    prestar("P1", s[0], a1, a, a, 14, 20)                           # vencido hace 6 días, local
    prestar("P2", s[1], a2, a, b, 12, 10)                           # vence en 2 días
    g.empaquetar_remito("REM-001", hace(10, 15))
    g.despachar_remito("REM-001", hace(9, 9))
    g.recibir_remito("REM-001", hace(7, 9))                         # tránsito de exactamente 2 días
    prestar("P3", s[2], a3, a, b, 14, 5)                            # remito nuevo (REM-001 ya está cerrado)
    g.empaquetar_remito("REM-002", hace(5, 12))
    g.despachar_remito("REM-002", hace(4, 9))                       # sigue despachado hace 4 días
    prestar("P4", s[3], b1, b, a, 14, 1)
    prestar("P7", s[2], b2, b, a, 14, 1)                            # se suma al remito abierto de P4

    g.crear_reserva(id_socio=s[2].id_socio, isbn="978-2", id_sede=a.id_sede)
    return Reportes(g), g


def test_remito_abierto_agrupa_p4_y_p7(escenario):
    _, g = escenario
    assert [r.id_remito for r in g.remitos] == ["REM-001", "REM-002", "REM-003"]
    assert g.remitos[2].cantidad_ejemplares == 2


def test_reporte_1_semaforo_y_pipeline_logistico(escenario):
    rep, _ = escenario
    r = rep.prestamos_activos_y_transito(HOY)
    assert (r["total_activos"], r["locales"], r["interbibliotecarios"]) == (5, 1, 4)
    # P1 vencido; P2 vence en 2 días (por vencer); P3 en 9 días, P4 y P7 en 13 días (en plazo)
    assert (r["en_plazo"], r["por_vencer"], r["vencidos"]) == (3, 1, 1)
    assert r["pct_vencidos"] == 20.0
    assert r["pct_coleccion_prestada"] == 83.3                      # 5 de 6 ejemplares
    assert r["detalle"][0]["prestamo"].id_prestamo == "P1"          # el más urgente va primero
    assert r["detalle"][0]["dias_restantes"] == -6
    etapas = {e["estado"]: (e["remitos"], e["ejemplares"]) for e in r["etapas_logisticas"]}
    assert etapas == {"Creado": (1, 2), "Empaquetado": (0, 0), "Despachado": (1, 1)}
    assert r["ejemplares_en_transito"] == 1
    assert r["envios_en_transito"][0]["dias_en_transito"] == 4


def test_reporte_2_morosidad_sanciones_e_incumplimiento(escenario):
    rep, _ = escenario
    r = rep.morosidad_y_sanciones(HOY)
    assert r["total_vencidos"] == 1
    d = r["detalle"][0]
    assert (d["prestamo"].id_prestamo, d["dias_retraso"], d["gravedad"]) == ("P1", 6, "Leve")
    assert d["sancion_dias"] == 12 and d["sancion_hasta"] == HOY + timedelta(days=12)   # 2 días por día de mora
    assert (r["mora_promedio"], r["mora_maxima"]) == (6.0, 6)
    assert d["extiende_sancion"] and d["sancion_vigente_hasta"] is None            # el socio no tenía ninguna sanción
    assert (r["socios_a_sancionar"], r["sancion_proyectada_max_dias"], r["socios_sin_efecto"]) == (1, 12, 0)
    assert r["por_gravedad"] == {"Leve": 1, "Moderada": 0, "Grave": 0}
    assert r["por_socio"][0]["mora_acumulada"] == 6
    # resueltos: P5 (tarde) + P6 (en término) + P1 (vencido) -> incumplen 2 de 3
    assert (r["devueltos_tarde"], r["total_resueltos"], r["tasa_incumplimiento"]) == (1, 3, 66.7)
    assert r["sancionados"] == []      # la sanción de P5 (hasta 14 días atrás) ya venció


@pytest.mark.parametrize("mora,gravedad", [(1, "Leve"), (7, "Leve"), (8, "Moderada"), (14, "Moderada"), (15, "Grave")])
def test_reporte_2_limites_de_gravedad(mora, gravedad):
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    sede = g.agregar_sede(Sede(nombre="A", horarios="Lun a Vie 09:00 - 18:00", activa=True))
    socio = g.agregar_socio(Socio(nombre="S", apellido="T", dni="1", email="s@t.com"))
    libro = g.agregar_libro(Libro(isbn="978-9", titulo="X", autor="Y"))
    ej = g.agregar_ejemplar(Ejemplar(libro=libro, sede=sede))
    g.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=ej.id_ejemplar, id_sede_origen=sede.id_sede,
                     dias_prestamo=10, fecha_inicio=HOY - timedelta(days=10 + mora))
    assert Reportes(g).morosidad_y_sanciones(HOY)["detalle"][0]["gravedad"] == gravedad


def test_reporte_2_sancion_vigente_aparece_como_sancionado():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    socio = g.agregar_socio(Socio(nombre="Carlos", apellido="Tevez", dni="1", email="c@t.com"))
    socio.penalizado_hasta = HOY + timedelta(days=9)
    r = Reportes(g).morosidad_y_sanciones(HOY)
    assert [(f["socio"].apellido, f["dias_restantes"]) for f in r["sancionados"]] == [("Tevez", 9)]
    assert r["pct_socios_sancionados"] == 100.0


def test_reporte_3_demanda_intersedes_contrastada_con_la_oferta(escenario):
    rep, _ = escenario
    r = rep.demanda_intersedes()
    assert (r["total_intersede"], r["total_prestamos"], r["pct_intersede"]) == (4, 7, 57.1)
    assert (r["titulos_distintos"], r["concentracion_top3"], r["titulos_demanda_alta"]) == (2, 100.0, 1)
    dune, neuro = r["ranking"]                                       # empatan en 2 solicitudes: desempata el título
    assert (dune["libro"].titulo, dune["solicitudes"], dune["pct_del_total"]) == ("Dune", 2, 50.0)
    assert (dune["ejemplares_red"], dune["solicitudes_por_ejemplar"], dune["nivel_demanda"]) == (4, 0.5, "Media")
    assert dune["ruta_principal"] == "A → B"
    assert (neuro["ejemplares_red"], neuro["solicitudes_por_ejemplar"], neuro["nivel_demanda"]) == (2, 1.0, "Alta")
    assert (neuro["reservas_activas"], neuro["ruta_principal"]) == (1, "B → A")
    assert [f["posicion"] for f in r["ranking"]] == [1, 2]


def test_reporte_4_disponibilidad_por_sede(escenario):
    rep, _ = escenario
    r = rep.disponibilidad_por_sede()
    assert (r["total_ejemplares"], r["disponibles_red"], r["tasa_red"]) == (6, 1, 16.7)
    assert [t.titulo for t in r["titulos_agotados_red"]] == ["Neuromante"]
    assert r["sedes_criticas"] == 1
    por_sede = {s["sede"].nombre: s for s in r["sedes"]}
    assert (por_sede["A"]["total"], por_sede["A"]["disponibles"], por_sede["A"]["situacion"]) == (3, 1, "Ajustada")
    assert por_sede["A"]["tasa_disponibilidad"] == 33.3 and por_sede["A"]["cobertura_catalogo"] == 50.0
    assert (por_sede["B"]["total"], por_sede["B"]["tasa_disponibilidad"], por_sede["B"]["situacion"]) == (3, 0.0, "Crítica")
    assert por_sede["B"]["titulos_agotados"] == 2
    assert por_sede["C"]["situacion"] == "Sin stock" and por_sede["D"]["situacion"] == "Inactiva"
    # la más comprometida primero; las inactivas / sin stock, al final
    assert [s["sede"].nombre for s in r["sedes"]] == ["B", "A", "C", "D"]
    assert all(sum(s["por_estado"].values()) == s["total"] for s in r["sedes"])


def test_reporte_5_efectividad_logistica(escenario):
    rep, _ = escenario
    r = rep.efectividad_logistica(HOY)
    assert (r["total_remitos"], r["recibidos"], r["en_curso"]) == (3, 1, 2)
    assert (r["entregados_a_tiempo"], r["entregas_tardias"], r["estancados"]) == (1, 0, 1)
    assert (r["tasa_entrega"], r["tasa_exito"]) == (33.3, 50.0)      # éxito = 1 a tiempo / (1 recibido + 1 estancado)
    assert [(i["tipo"], i["remito"].id_remito) for i in r["incidencias"]] == [("Estancado", "REM-002")]
    # el agrupamiento: 4 ejemplares viajaron en 3 remitos -> se evitó 1 envío
    assert (r["ejemplares_enviados"], r["ejemplares_por_remito"]) == (4, 1.33)
    assert (r["envios_evitados"], r["pct_envios_evitados"]) == (1, 25.0)
    t = {x["etapa"].split(" ")[0]: formatear_duracion(x["promedio_s"]) for x in r["tiempos_por_etapa"]}
    assert t == {"Espera": "4 h 30 min", "Preparación": "19 h 30 min", "Tránsito": "2 d", "Ciclo": "3 d"}
    assert r["remitos_por_estado"] == {"Creado": 1, "Empaquetado": 0, "Despachado": 1, "Recibido": 1, "Cancelado": 0}
    assert (r["cancelados"], r["cancelados_sin_salir"], r["cancelados_en_transito"], r["remitos_evaluados"]) == (0, 0, 0, 3)


def test_reporte_5_entrega_tardia_supera_el_sla():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    a = g.agregar_sede(Sede(nombre="A", horarios="Lun a Vie 09:00 - 18:00", activa=True))
    b = g.agregar_sede(Sede(nombre="B", horarios="Lun a Vie 09:00 - 18:00", activa=True))
    socio = g.agregar_socio(Socio(nombre="S", apellido="T", dni="1", email="s@t.com"))
    libro = g.agregar_libro(Libro(isbn="978-9", titulo="X", autor="Y"))
    ej = g.agregar_ejemplar(Ejemplar(libro=libro, sede=a))
    g.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=ej.id_ejemplar, id_sede_origen=a.id_sede,
                     id_sede_destino=b.id_sede, fecha_inicio=dias_atras(10))
    g.empaquetar_remito("REM-001", hace(10, 12))
    g.despachar_remito("REM-001", hace(9, 9))
    g.recibir_remito("REM-001", hace(5, 9))                          # 4 días de tránsito > SLA de 3
    r = Reportes(g).efectividad_logistica(HOY)
    assert (r["entregados_a_tiempo"], r["entregas_tardias"], r["tasa_exito"]) == (0, 1, 0.0)
    assert r["incidencias"][0]["tipo"] == "Entrega tardía" and r["incidencias"][0]["dias"] == 4.0


def test_reporte_6_movimiento_y_balance_entre_sedes(escenario):
    rep, _ = escenario
    r = rep.movimiento_entre_sedes()
    assert (r["total_remitos"], r["total_ejemplares"], r["rutas_activas"]) == (3, 4, 2)
    ab, ba = r["rutas"]                                              # empatan en 2 ejemplares: desempata por nombre
    assert (ab["origen"].nombre, ab["destino"].nombre, ab["remitos"], ab["ejemplares"], ab["entregados"]) == ("A", "B", 2, 2, 1)
    assert ab["transito_promedio_s"] == 2 * 86400
    assert (ba["origen"].nombre, ba["remitos"], ba["ejemplares"], ba["ejemplares_por_remito"]) == ("B", 1, 2, 2.0)
    assert ba["transito_promedio_s"] is None                         # todavía no se entregó
    balance = {f["sede"].nombre: (f["enviados"], f["recibidos"], f["saldo"], f["por_salir"], f["perfil"]) for f in r["balance_sedes"]}
    assert balance == {"A": (2, 0, -2, 0, "Emisora neta"), "B": (0, 1, 1, 2, "Receptora neta")}
    assert (r["sede_mas_emisora"]["sede"].nombre, r["sede_mas_receptora"]["sede"].nombre) == ("A", "B")
    assert r["transito_promedio_s"] == 2 * 86400


def test_reportes_sin_datos_no_fallan():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    todos = Reportes(g).todos(HOY)
    assert todos["activos"]["total_activos"] == 0 and todos["morosidad"]["tasa_incumplimiento"] == 0.0
    assert todos["demanda"]["ranking"] == [] and todos["disponibilidad"]["sedes"] == []
    assert todos["logistica"]["tasa_exito"] == 0.0 and todos["logistica"]["ejemplares_por_remito"] == 0.0
    assert todos["movimiento"]["ruta_principal"] is None and todos["movimiento"]["transito_promedio_s"] is None
    assert reportes_pdf.pdf_todos_los_reportes(todos).getvalue().startswith(b"%PDF")   # los PDF también soportan "vacío"


@pytest.mark.parametrize("segundos,texto", [
    (None, "—"), (30, "30 s"), (45 * 60, "45 min"), (3 * 3600, "3 h"), (3 * 3600 + 20 * 60, "3 h 20 min"),
    (86400, "1 d"), (2 * 86400 + 7 * 3600, "2 d 7 h"),
])
def test_formatear_duracion(segundos, texto):
    assert formatear_duracion(segundos) == texto


def test_pdfs_de_cada_reporte_se_generan(escenario):
    rep, _ = escenario
    todos = rep.todos(HOY)
    pdfs = [
        reportes_pdf.pdf_prestamos_activos_transito(todos["activos"]),
        reportes_pdf.pdf_morosidad_y_sanciones(todos["morosidad"]),
        reportes_pdf.pdf_demanda_intersedes(todos["demanda"]),
        reportes_pdf.pdf_disponibilidad_por_sede(todos["disponibilidad"]),
        reportes_pdf.pdf_efectividad_logistica(todos["logistica"]),
        reportes_pdf.pdf_movimiento_entre_sedes(todos["movimiento"]),
        reportes_pdf.pdf_todos_los_reportes(todos),
    ]
    assert all(p.getvalue().startswith(b"%PDF") for p in pdfs)


# --- Datos demo: deben cargar sin violar ninguna validación y alimentar todos los reportes ---

def test_datos_demo_cargan_y_muestran_remitos_con_varios_ejemplares():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    cargar_datos_iniciales(g)

    por_id = {r.id_remito: r for r in g.remitos}
    assert {k: (str(r.estado_actual), r.cantidad_ejemplares) for k, r in por_id.items()} == {
        "REM-001": ("Recibido", 2), "REM-002": ("Recibido", 1), "REM-003": ("Empaquetado", 1),
        "REM-004": ("Creado", 2), "REM-005": ("Despachado", 2), "REM-006": ("Empaquetado", 1),
        "REM-007": ("Cancelado", 1), "REM-008": ("Cancelado", 1),
    }
    # todo lo cargado en memoria coincide con lo persistido
    snapshot = [(r.id_remito, str(r.estado_actual), [e.id_ejemplar for e in r.ejemplares]) for r in g.remitos]
    g._cargar_desde_bd()
    assert snapshot == [(r.id_remito, str(r.estado_actual), [e.id_ejemplar for e in r.ejemplares]) for r in g.remitos]

    # los reportes (calculados contra la fecha de hoy, igual que los datos demo) dan lo esperado
    todos = Reportes(g).todos(date.today())
    assert todos["activos"]["vencidos"] == 3 and todos["activos"]["por_vencer"] == 1
    assert todos["morosidad"]["por_gravedad"] == {"Leve": 1, "Moderada": 1, "Grave": 1}
    assert todos["logistica"]["entregados_a_tiempo"] == 1 and todos["logistica"]["entregas_tardias"] == 1
    assert todos["logistica"]["estancados"] == 1 and todos["logistica"]["envios_evitados"] == 3
    # los dos remitos cancelados de la demo: uno nunca salió (no cuenta en las tasas) y otro se canceló en tránsito (incidencia)
    log = todos["logistica"]
    assert (log["cancelados"], log["cancelados_sin_salir"], log["cancelados_en_transito"]) == (2, 1, 1)
    assert log["total_incidencias"] == 3 and log["total_remitos"] == 8 and log["remitos_evaluados"] == 7
    assert todos["movimiento"]["total_remitos"] == 6               # los cancelados no son movimiento
    for id_prestamo in ("PREST-116", "PREST-117"):
        p = next(p for p in g.prestamos if p.id_prestamo == id_prestamo)
        assert p.cancelado and p.ejemplar.esta_disponible()
    assert reportes_pdf.pdf_todos_los_reportes(todos).getvalue().startswith(b"%PDF")
