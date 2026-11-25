"""
Sanciones por mora: 2 días de inhabilitación por día de retraso, contados desde la devolución.
Si el socio ya está sancionado queda siempre la fecha que termina más tarde (no se pisa ni se acorta),
y el reporte de morosidad proyecta con esa misma regla.
"""
from datetime import date, timedelta

import pytest

from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.enum import Estado
from models.operaciones import FACTOR_SANCION_POR_MORA
from models.reportes import Reportes

HOY = date.today()
HORARIO = "Lun a Vie 09:00 - 18:00"


def dias(n):
    return HOY + timedelta(days=n)


@pytest.fixture
def red():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    sede = g.agregar_sede(Sede(nombre="A", horarios=HORARIO))
    socios = [g.agregar_socio(Socio(nombre=f"S{i}", apellido="T", dni=f"40{i}", email=f"s{i}@t.com")) for i in range(3)]
    libro = g.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="H"))
    ejs = [g.agregar_ejemplar(Ejemplar(libro=libro, sede=sede)) for _ in range(4)]
    return g, sede, socios, ejs


def prestar_con_mora(g, sede, socio, ejemplar, mora, id_prestamo):
    """Préstamo local que hoy lleva `mora` días vencido (plazo de 14 días)."""
    return g.crear_prestamo(id_prestamo=id_prestamo, id_socio=socio.id_socio, id_ejemplar=ejemplar.id_ejemplar,
                            id_sede_origen=sede.id_sede, dias_prestamo=14, fecha_inicio=dias(-(14 + mora)))


def test_la_sancion_es_el_doble_de_los_dias_de_mora_desde_la_devolucion(red):
    g, sede, socios, ejs = red
    p = prestar_con_mora(g, sede, socios[0], ejs[0], 5, "P1")
    g.registrar_devolucion("P1", HOY, Estado.BUENO)
    assert FACTOR_SANCION_POR_MORA == 2
    assert socios[0].penalizado_hasta == dias(10)                    # 5 días tarde x 2, desde hoy
    assert not socios[0].esta_habilitado(HOY) and not socios[0].esta_habilitado(dias(10))
    assert socios[0].esta_habilitado(dias(11))


def test_devolver_a_tiempo_no_sanciona(red):
    g, sede, socios, ejs = red
    g.crear_prestamo(id_prestamo="P1", id_socio=socios[0].id_socio, id_ejemplar=ejs[0].id_ejemplar,
                     id_sede_origen=sede.id_sede, dias_prestamo=14)
    g.registrar_devolucion("P1", HOY, Estado.OPTIMO)
    assert socios[0].penalizado_hasta is None


def test_una_devolucion_con_poca_mora_no_acorta_una_sancion_mayor(red):
    # El caso real: primero se devuelve el de 31 días de mora (62 de sanción) y después el de 11 (22): queda la de 62.
    g, sede, socios, ejs = red
    prestar_con_mora(g, sede, socios[0], ejs[0], 31, "P-LARGO")
    prestar_con_mora(g, sede, socios[0], ejs[1], 11, "P-CORTO")

    g.registrar_devolucion("P-LARGO", HOY, Estado.BUENO)
    assert socios[0].penalizado_hasta == dias(62)
    g.registrar_devolucion("P-CORTO", HOY, Estado.BUENO)

    assert socios[0].penalizado_hasta == dias(62)                    # no se pisó con dias(22)
    g._cargar_desde_bd()                                             # y lo guardado en la base es lo mismo
    assert g.socios[socios[0].id_socio].penalizado_hasta == dias(62)


def test_el_orden_de_las_devoluciones_no_cambia_el_resultado(red):
    g, sede, socios, ejs = red
    prestar_con_mora(g, sede, socios[0], ejs[0], 31, "P-LARGO")
    prestar_con_mora(g, sede, socios[0], ejs[1], 11, "P-CORTO")

    g.registrar_devolucion("P-CORTO", HOY, Estado.BUENO)
    assert socios[0].penalizado_hasta == dias(22)
    g.registrar_devolucion("P-LARGO", HOY, Estado.BUENO)             # la mayor sí amplía la anterior

    assert socios[0].penalizado_hasta == dias(62)


def test_una_sancion_ya_vencida_se_reemplaza_por_la_nueva(red):
    g, sede, socios, ejs = red
    prestar_con_mora(g, sede, socios[0], ejs[0], 3, "P1")
    socios[0].penalizado_hasta = dias(-5)                            # sanción vieja, ya cumplida
    g.registrar_devolucion("P1", HOY, Estado.BUENO)
    assert socios[0].penalizado_hasta == dias(6)


# --- El reporte proyecta con la misma regla ---

def reporte(g):
    return Reportes(g).morosidad_y_sanciones(HOY)


def fila(rep, id_prestamo):
    return next(d for d in rep["detalle"] if d["prestamo"].id_prestamo == id_prestamo)


def test_reporte_marca_sin_efecto_si_ya_tiene_una_sancion_mas_larga(red):
    g, sede, socios, ejs = red
    prestar_con_mora(g, sede, socios[0], ejs[0], 11, "P1")           # devolverlo hoy daría 22 días
    socios[0].penalizado_hasta = dias(62)                            # y ya está sancionado hasta dentro de 62 días

    rep = reporte(g)
    d = fila(rep, "P1")
    assert (d["sancion_dias"], d["sancion_hasta"]) == (22, dias(22))
    assert d["extiende_sancion"] is False and d["sancion_vigente_hasta"] == dias(62)
    assert (rep["socios_a_sancionar"], rep["sancion_proyectada_max_dias"], rep["socios_sin_efecto"]) == (0, 0, 1)

    # y es exactamente lo que pasaría al devolverlo: la sanción no cambia
    g.registrar_devolucion("P1", HOY, Estado.BUENO)
    assert socios[0].penalizado_hasta == dias(62)


def test_reporte_marca_que_amplia_la_sancion_vigente(red):
    g, sede, socios, ejs = red
    prestar_con_mora(g, sede, socios[0], ejs[0], 11, "P1")           # 22 días > 5 que le quedan
    socios[0].penalizado_hasta = dias(5)

    d = fila(reporte(g), "P1")
    assert d["extiende_sancion"] is True and d["sancion_vigente_hasta"] == dias(5) and d["sancion_hasta"] == dias(22)
    g.registrar_devolucion("P1", HOY, Estado.BUENO)
    assert socios[0].penalizado_hasta == dias(22)


def test_reporte_proyecta_por_socio_con_la_mas_larga_y_no_con_la_suma(red):
    g, sede, socios, ejs = red
    prestar_con_mora(g, sede, socios[0], ejs[0], 31, "P-LARGO")      # 62 días
    prestar_con_mora(g, sede, socios[0], ejs[1], 11, "P-CORTO")      # 22 días  (suma sería 84, pero la sanción real es 62)
    prestar_con_mora(g, sede, socios[1], ejs[2], 5, "P-OTRO")        # otro socio: 10 días

    rep = reporte(g)
    assert rep["total_vencidos"] == 3
    assert (rep["socios_a_sancionar"], rep["sancion_proyectada_max_dias"], rep["socios_sin_efecto"]) == (2, 62, 0)

    # comprobación contra la realidad: devolviendo todo hoy, las sanciones son las proyectadas
    for id_prestamo in ("P-CORTO", "P-LARGO", "P-OTRO"):
        g.registrar_devolucion(id_prestamo, HOY, Estado.BUENO)
    assert (socios[0].penalizado_hasta, socios[1].penalizado_hasta) == (dias(62), dias(10))


def test_reporte_sin_vencidos_no_proyecta_nada(red):
    g, *_ = red
    rep = reporte(g)
    assert (rep["socios_a_sancionar"], rep["sancion_proyectada_max_dias"], rep["socios_sin_efecto"]) == (0, 0, 0)


def test_los_pdf_se_generan_con_las_proyecciones_nuevas(red):
    import reportes_pdf
    g, sede, socios, ejs = red
    prestar_con_mora(g, sede, socios[0], ejs[0], 11, "P1")           # sin efecto
    prestar_con_mora(g, sede, socios[1], ejs[1], 5, "P2")            # extiende
    socios[0].penalizado_hasta = dias(62)
    rep = Reportes(g)
    assert reportes_pdf.pdf_morosidad_y_sanciones(rep.morosidad_y_sanciones(HOY)).getvalue().startswith(b"%PDF")
    assert reportes_pdf.pdf_todos_los_reportes(rep.todos(HOY)).getvalue().startswith(b"%PDF")
