"""
Estado Cancelado del remito: se llega desde cualquier estado no final (Creado, Empaquetado, Despachado), es final,
y al cancelar los ejemplares se liberan y los préstamos que esperaban ese envío quedan cancelados.
"""
import sqlite3
from datetime import date, datetime, time, timedelta

import pytest

from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.enum import Estado, EstadoEjemplar
from models.remito import Remito, Creado, Empaquetado, Despachado, Recibido, Cancelado
from models.reportes import Reportes
from models.excepciones import BibliotecaExcepcion, TransicionInvalidaError
from dao.database import inicializar_bd

HORARIO = "Lun a Vie 09:00 - 18:00"
HOY = date.today()
MOTIVO = "Se cayó la sede de destino"


def hace(dias, hora=9):
    return datetime.combine(HOY - timedelta(days=dias), time(hora, 0))


# ---------------------------------------------------------------------------
# 1. El patrón State (sin base de datos)
# ---------------------------------------------------------------------------
class _Sede:
    def __init__(self, nombre):
        self.nombre = nombre


class _Ejemplar:
    def __init__(self, id_ejemplar):
        self.id_ejemplar = id_ejemplar


def remito_en(estado):
    """Remito de un ejemplar llevado al estado pedido ('Creado', 'Empaquetado', 'Despachado', 'Recibido')."""
    r = Remito("REM-X", _Sede("A"), _Sede("B"), [_Ejemplar("EJ-1")])
    pasos = {"Creado": [], "Empaquetado": ["empaquetar"], "Despachado": ["empaquetar", "despachar"],
             "Recibido": ["empaquetar", "despachar", "recibir"]}[estado]
    for paso in pasos:
        getattr(r, paso)()
    return r


@pytest.mark.parametrize("estado", ["Creado", "Empaquetado", "Despachado"])
def test_se_puede_cancelar_desde_cualquier_estado_no_final(estado):
    r = remito_en(estado)
    eventos_antes = len(r.historial_trazabilidad)

    r.cancelar(MOTIVO)

    assert isinstance(r.estado_actual, Cancelado) and r.esta_cancelado
    assert len(r.historial_trazabilidad) == eventos_antes + 1
    ultimo = r.historial_trazabilidad[-1]
    assert (ultimo["estado"], ultimo["observacion"]) == ("Cancelado", MOTIVO)
    assert r.motivo_cancelacion == MOTIVO


def test_no_se_puede_cancelar_un_remito_ya_recibido():
    r = remito_en("Recibido")
    with pytest.raises(TransicionInvalidaError, match="ya fue recibido"):
        r.cancelar(MOTIVO)
    assert isinstance(r.estado_actual, Recibido) and not r.esta_cancelado and r.motivo_cancelacion is None


def test_cancelado_es_un_estado_final_no_se_cancela_dos_veces():
    r = remito_en("Empaquetado")
    r.cancelar(MOTIVO)
    with pytest.raises(TransicionInvalidaError, match="ya fue cancelado"):
        r.cancelar("otro motivo")
    assert r.motivo_cancelacion == MOTIVO and len(r.historial_trazabilidad) == 3


@pytest.mark.parametrize("operacion,args,fragmento", [
    ("empaquetar", (), "empaquetar un remito cancelado"),
    ("despachar", (), "despachar un remito cancelado"),
    ("recibir", (), "recibir un remito cancelado"),
    ("agregar_ejemplar", (_Ejemplar("EJ-2"),), "agregar ejemplares a un remito cancelado"),
])
def test_un_remito_cancelado_no_admite_ninguna_otra_operacion(operacion, args, fragmento):
    r = remito_en("Creado")
    r.cancelar(MOTIVO)
    with pytest.raises(TransicionInvalidaError, match=fragmento):
        getattr(r, operacion)(*args)
    assert isinstance(r.estado_actual, Cancelado) and r.cantidad_ejemplares == 1


@pytest.mark.parametrize("motivo", ["", "   ", None])
def test_el_motivo_de_la_cancelacion_es_obligatorio(motivo):
    r = remito_en("Despachado")
    with pytest.raises(BibliotecaExcepcion, match="motivo"):
        r.cancelar(motivo)
    assert isinstance(r.estado_actual, Despachado) and len(r.historial_trazabilidad) == 3


def test_fue_despachado_distingue_cancelado_antes_de_salir_y_en_transito():
    sin_salir = remito_en("Empaquetado")
    sin_salir.cancelar(MOTIVO)
    en_transito = remito_en("Despachado")
    en_transito.cancelar(MOTIVO)
    assert (sin_salir.fue_despachado, en_transito.fue_despachado) == (False, True)
    assert remito_en("Creado").motivo_cancelacion is None


# ---------------------------------------------------------------------------
# 2. Consecuencias en el sistema (gestor + base de datos)
# ---------------------------------------------------------------------------
@pytest.fixture
def red():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    a = g.agregar_sede(Sede(nombre="A", horarios=HORARIO))
    b = g.agregar_sede(Sede(nombre="B", horarios=HORARIO))
    c = g.agregar_sede(Sede(nombre="C", horarios=HORARIO))
    socios = [g.agregar_socio(Socio(nombre=f"S{i}", apellido="T", dni=f"30{i}", email=f"s{i}@t.com")) for i in range(4)]
    libro = g.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="H"))
    ejs = [g.agregar_ejemplar(Ejemplar(libro=libro, sede=a)) for _ in range(4)]
    return g, a, b, c, socios, ejs


def prestar(g, socio, ejemplar, origen, destino, **kw):
    return g.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=ejemplar.id_ejemplar,
                            id_sede_origen=origen.id_sede, id_sede_destino=destino.id_sede, **kw)


def estado_de(g, id_remito):
    return str(g.obtener_remito(id_remito).estado_actual)


@pytest.mark.parametrize("llevar_a,estado_ejemplar_antes", [
    ([], EstadoEjemplar.PRESTADO),
    (["empaquetar_remito"], EstadoEjemplar.EN_PREPARACION),
    (["empaquetar_remito", "despachar_remito"], EstadoEjemplar.EN_TRANSITO),
])
def test_cancelar_libera_los_ejemplares_y_cancela_los_prestamos(red, llevar_a, estado_ejemplar_antes):
    g, a, b, c, socios, ejs = red
    p1 = prestar(g, socios[0], ejs[0], a, b)
    p2 = prestar(g, socios[1], ejs[1], a, b)                       # los dos viajan en REM-001
    for paso in llevar_a:
        getattr(g, paso)("REM-001")
    assert ejs[0].estado_ejemplar == ejs[1].estado_ejemplar == estado_ejemplar_antes

    resumen = g.cancelar_remito("REM-001", MOTIVO)

    assert estado_de(g, "REM-001") == "Cancelado"
    assert g.obtener_remito("REM-001").motivo_cancelacion == MOTIVO
    assert {e.id_ejemplar for e in resumen["ejemplares"]} == {ejs[0].id_ejemplar, ejs[1].id_ejemplar}
    assert {p.id_prestamo for p in resumen["prestamos"]} == {p1.id_prestamo, p2.id_prestamo}
    for e in ejs[:2]:
        assert e.estado_ejemplar == EstadoEjemplar.DISPONIBLE and e.sede is a      # vuelve (sigue) en la sede de origen
    for p in (p1, p2):
        assert p.cancelado and not p.esta_abierto and "REM-001" in p.motivo_cancelacion and MOTIVO in p.motivo_cancelacion
        assert p.fecha_devolucion is None


def test_cancelar_no_sanciona_ni_deja_el_prestamo_vencido(red):
    g, a, b, c, socios, ejs = red
    p = prestar(g, socios[0], ejs[0], a, b, fecha_inicio=HOY - timedelta(days=30), dias_prestamo=7)   # ya estaría vencido
    assert p.esta_vencido(HOY)

    g.cancelar_remito("REM-001", MOTIVO)

    assert not p.esta_vencido(HOY) and not p.esta_vencido(HOY + timedelta(days=500))
    assert socios[0].penalizado_hasta is None and socios[0].esta_habilitado(HOY)


def test_un_prestamo_cancelado_no_se_puede_devolver(red):
    g, a, b, c, socios, ejs = red
    p = prestar(g, socios[0], ejs[0], a, b)
    g.cancelar_remito("REM-001", MOTIVO)
    with pytest.raises(BibliotecaExcepcion, match="cancelado"):
        g.registrar_devolucion(p.id_prestamo, HOY, Estado.BUENO)
    assert p.fecha_devolucion is None and ejs[0].estado_ejemplar == EstadoEjemplar.DISPONIBLE


def test_el_ejemplar_cancelado_se_puede_volver_a_prestar_y_abre_un_remito_nuevo(red):
    g, a, b, c, socios, ejs = red
    prestar(g, socios[0], ejs[0], a, b)
    g.cancelar_remito("REM-001", MOTIVO)
    assert g.remito_en_curso_de(ejs[0].id_ejemplar) is None        # el cancelado ya no cuenta como vigente
    assert g.buscar_remito_abierto(a.id_sede, b.id_sede) is None   # y no es "abierto": no admite más ejemplares
    assert ejs[0] in g.ejemplares_prestables()                     # el ejemplar vuelve a ofrecerse en el formulario

    nuevo = prestar(g, socios[0], ejs[0], a, b)                    # el mismo socio puede volver a pedirlo
    assert nuevo.esta_abierto and [r.id_remito for r in g.remitos] == ["REM-001", "REM-002"]
    assert g.remito_en_curso_de(ejs[0].id_ejemplar).id_remito == "REM-002"
    assert ejs[0].estado_ejemplar == EstadoEjemplar.PRESTADO


def test_cancelar_solo_afecta_a_los_prestamos_de_ese_remito(red):
    g, a, b, c, socios, ejs = red
    p_ab = prestar(g, socios[0], ejs[0], a, b)
    p_ac = prestar(g, socios[1], ejs[1], a, c)                     # otra ruta: REM-002
    p_local = prestar(g, socios[2], ejs[2], a, a)                  # local: sin remito

    g.cancelar_remito("REM-001", MOTIVO)

    assert p_ab.cancelado
    assert not p_ac.cancelado and p_ac.esta_abierto and ejs[1].estado_ejemplar == EstadoEjemplar.PRESTADO
    assert not p_local.cancelado and estado_de(g, "REM-002") == "Creado"


def test_prestamos_de_remito_informa_que_se_cancelaria(red):
    g, a, b, c, socios, ejs = red
    p1 = prestar(g, socios[0], ejs[0], a, b)
    p2 = prestar(g, socios[1], ejs[1], a, b)
    assert [p.id_prestamo for p in g.prestamos_de_remito(g.obtener_remito("REM-001"))] == [p1.id_prestamo, p2.id_prestamo]
    g.cancelar_remito("REM-001", MOTIVO)
    assert g.prestamos_de_remito(g.obtener_remito("REM-001")) == []   # ya no hay nada vigente


def test_no_se_cancela_un_remito_ya_recibido_y_no_cambia_nada(red):
    g, a, b, c, socios, ejs = red
    p = prestar(g, socios[0], ejs[0], a, b)
    for paso in ("empaquetar_remito", "despachar_remito", "recibir_remito"):
        getattr(g, paso)("REM-001")

    with pytest.raises(TransicionInvalidaError):
        g.cancelar_remito("REM-001", MOTIVO)

    assert estado_de(g, "REM-001") == "Recibido" and p.esta_abierto
    assert ejs[0].estado_ejemplar == EstadoEjemplar.PRESTADO and ejs[0].sede is b


def test_no_se_cancela_dos_veces_y_el_motivo_es_obligatorio_sin_cambiar_nada(red):
    g, a, b, c, socios, ejs = red
    p = prestar(g, socios[0], ejs[0], a, b)

    for motivo in ("", "   ", None):
        with pytest.raises(BibliotecaExcepcion, match="motivo"):
            g.cancelar_remito("REM-001", motivo)
    assert estado_de(g, "REM-001") == "Creado" and p.esta_abierto            # nada cambió

    g.cancelar_remito("REM-001", MOTIVO)
    with pytest.raises(TransicionInvalidaError, match="ya fue cancelado"):
        g.cancelar_remito("REM-001", "otra vez")
    with pytest.raises(BibliotecaExcepcion, match="no encontrado"):
        g.cancelar_remito("REM-999", MOTIVO)


def test_un_ejemplar_retenido_por_otro_prestamo_vigente_no_se_libera(red):
    # Devolución anticipada: el ejemplar volvió antes de recibirse el remito y se prestó de nuevo por otra ruta.
    g, a, b, c, socios, ejs = red
    p1 = prestar(g, socios[0], ejs[0], a, b)                       # REM-001 (A -> B)
    g.registrar_devolucion(p1.id_prestamo, HOY, Estado.BUENO)      # el ejemplar queda radicado en B
    p2 = prestar(g, socios[1], ejs[0], b, c)                       # nuevo préstamo vigente (B -> C), REM-002
    assert ejs[0].estado_ejemplar == EstadoEjemplar.PRESTADO

    resumen = g.cancelar_remito("REM-001", MOTIVO)

    assert resumen["ejemplares"] == [] and resumen["prestamos"] == []
    assert ejs[0].estado_ejemplar == EstadoEjemplar.PRESTADO and p2.esta_abierto
    assert not p1.cancelado and p1.fecha_devolucion == HOY                   # el ya devuelto tampoco se toca


def test_todo_queda_guardado_en_la_base_de_datos(red):
    g, a, b, c, socios, ejs = red
    p1 = prestar(g, socios[0], ejs[0], a, b)
    prestar(g, socios[1], ejs[1], a, b)
    g.empaquetar_remito("REM-001")
    g.despachar_remito("REM-001")
    g.cancelar_remito("REM-001", MOTIVO)

    g._cargar_desde_bd()                                            # como al reiniciar la app

    remito = g.obtener_remito("REM-001")
    assert isinstance(remito.estado_actual, Cancelado) and remito.motivo_cancelacion == MOTIVO and remito.fue_despachado
    assert [e["estado"] for e in remito.historial_trazabilidad] == ["Creado", "Empaquetado", "Despachado", "Cancelado"]
    prestamos = {p.id_prestamo: p for p in g.prestamos}
    assert all(p.cancelado and not p.esta_abierto and MOTIVO in p.motivo_cancelacion for p in prestamos.values())
    assert prestamos[p1.id_prestamo].socio.penalizado_hasta is None
    assert all(g.ejemplares[e.id_ejemplar].estado_ejemplar == EstadoEjemplar.DISPONIBLE for e in ejs[:2])
    with sqlite3.connect(g.db_path) as cx:
        assert cx.execute("SELECT estado_actual FROM remitos WHERE id_remito = 'REM-001'").fetchone() == ("Cancelado",)
        assert cx.execute("SELECT COUNT(*) FROM prestamos WHERE cancelado = 1").fetchone() == (2,)


def test_migracion_agrega_las_columnas_de_cancelacion_sin_perder_prestamos(tmp_path):
    db = str(tmp_path / "vieja.db")
    inicializar_bd(db)
    with sqlite3.connect(db) as cx:                                  # dejamos la tabla como era antes de la cancelación
        cx.execute("DROP TABLE prestamos")
        cx.execute("""CREATE TABLE prestamos (id_prestamo TEXT PRIMARY KEY, id_socio TEXT NOT NULL, id_ejemplar TEXT NOT NULL,
                      id_sede_origen TEXT NOT NULL, id_sede_destino TEXT NOT NULL, fecha_inicio TEXT NOT NULL,
                      fecha_vencimiento TEXT NOT NULL, fecha_devolucion TEXT, estado_devuelto TEXT)""")
        cx.execute("INSERT INTO prestamos VALUES ('P-1', 'S', 'E', 'A', 'B', '2026-01-01', '2026-01-15', NULL, NULL)")

    inicializar_bd(db)
    inicializar_bd(db)                                               # idempotente

    with sqlite3.connect(db) as cx:
        columnas = [f[1] for f in cx.execute("PRAGMA table_info(prestamos)")]
        assert "cancelado" in columnas and "motivo_cancelacion" in columnas
        assert cx.execute("SELECT id_prestamo, cancelado, motivo_cancelacion FROM prestamos").fetchall() == [("P-1", 0, "")]


# ---------------------------------------------------------------------------
# 3. Reportes: un remito/préstamo cancelado no se cuenta como activo, vencido ni movimiento
# ---------------------------------------------------------------------------
@pytest.fixture
def escenario_reportes(red):
    """
    REM-001 A->B: despachado y CANCELADO en tránsito (su préstamo vencería hace 6 días si siguiera vigente).
    REM-002 A->B: CANCELADO antes de salir (cancelado hace 4 días: estaría "estancado" si se contara como en curso).
    REM-003 A->B: recibido a tiempo (tránsito de 21 h).
    """
    g, a, b, c, socios, ejs = red
    prestar(g, socios[0], ejs[0], a, b, fecha_inicio=HOY - timedelta(days=20), dias_prestamo=14)
    g.empaquetar_remito("REM-001", hace(19, 10))
    g.despachar_remito("REM-001", hace(18, 9))
    g.cancelar_remito("REM-001", "Falló el transporte", hace(17, 12))

    prestar(g, socios[1], ejs[1], a, b, fecha_inicio=HOY - timedelta(days=5))
    g.cancelar_remito("REM-002", "Pedido anulado", hace(4, 10))

    prestar(g, socios[2], ejs[2], a, b, fecha_inicio=HOY - timedelta(days=10))
    g.empaquetar_remito("REM-003", hace(9, 10))
    g.despachar_remito("REM-003", hace(9, 15))
    g.recibir_remito("REM-003", hace(8, 12))
    return Reportes(g), g


def test_reporte_1_y_2_ignoran_los_prestamos_cancelados(escenario_reportes):
    rep, g = escenario_reportes
    activos = rep.prestamos_activos_y_transito(HOY)
    assert activos["total_activos"] == 1                                       # solo el del remito recibido
    assert [d["prestamo"].fecha_inicio for d in activos["detalle"]] == [HOY - timedelta(days=10)]
    etapas = {e["estado"]: e["remitos"] for e in activos["etapas_logisticas"]}
    assert etapas == {"Creado": 0, "Empaquetado": 0, "Despachado": 0}          # los cancelados no están en el pipeline
    assert activos["ejemplares_en_transito"] == 0 and activos["envios_en_transito"] == []

    morosidad = rep.morosidad_y_sanciones(HOY)
    assert morosidad["total_vencidos"] == 0                                    # el cancelado habría estado vencido hace 6 días
    assert morosidad["total_resueltos"] == 0


def test_reporte_3_las_solicitudes_canceladas_siguen_contando_como_demanda(escenario_reportes):
    rep, g = escenario_reportes
    demanda = rep.demanda_intersedes()
    assert demanda["total_intersede"] == 3 and demanda["ranking"][0]["solicitudes"] == 3


def test_reporte_5_cancelado_antes_de_salir_no_es_falla_y_en_transito_si(escenario_reportes):
    rep, g = escenario_reportes
    r = rep.efectividad_logistica(HOY)
    assert (r["total_remitos"], r["remitos_evaluados"]) == (3, 2)             # REM-002 nunca salió: no se evalúa
    assert (r["recibidos"], r["en_curso"], r["estancados"]) == (1, 0, 0)       # y el cancelado no figura como "estancado"
    assert (r["cancelados"], r["cancelados_sin_salir"], r["cancelados_en_transito"]) == (2, 1, 1)
    assert [(i["tipo"], i["remito"].id_remito) for i in r["incidencias"]] == [("Cancelado en tránsito", "REM-001")]
    assert "Falló el transporte" in r["incidencias"][0]["detalle"]
    # éxito = 1 a tiempo / (1 recibido + 1 cancelado en tránsito); entrega = 1 recibido / 2 evaluados
    assert (r["entregados_a_tiempo"], r["tasa_exito"], r["tasa_entrega"]) == (1, 50.0, 50.0)
    assert (r["ejemplares_enviados"], r["envios_evitados"]) == (2, 0)           # REM-002 no cuenta para el agrupamiento
    assert r["remitos_por_estado"] == {"Creado": 0, "Empaquetado": 0, "Despachado": 0, "Recibido": 1, "Cancelado": 2}


def test_reporte_6_un_remito_cancelado_no_es_movimiento(escenario_reportes):
    rep, g = escenario_reportes
    m = rep.movimiento_entre_sedes()
    assert (m["total_remitos"], m["total_ejemplares"], m["rutas_activas"]) == (1, 1, 1)
    assert m["rutas"][0]["entregados"] == 1


def test_los_pdf_se_generan_con_remitos_cancelados(escenario_reportes):
    import reportes_pdf
    rep, g = escenario_reportes
    assert reportes_pdf.pdf_todos_los_reportes(rep.todos(HOY)).getvalue().startswith(b"%PDF")
    assert reportes_pdf.pdf_efectividad_logistica(rep.efectividad_logistica(HOY)).getvalue().startswith(b"%PDF")
