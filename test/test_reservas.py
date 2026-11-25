"""
Reservas: una reserva activa se CUMPLE cuando se le registra al mismo socio un préstamo de ese título.
Estados de la reserva: Activa (pendiente), Cumplida y Cancelada.
"""
import sqlite3
from datetime import date

import pytest

from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.reportes import Reportes
from models.datos_demo import cargar_datos_iniciales
from models.excepciones import BibliotecaExcepcion
from dao.database import inicializar_bd

HORARIO = "Lun a Vie 09:00 - 18:00"


@pytest.fixture
def red():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    a = g.agregar_sede(Sede(nombre="A", horarios=HORARIO))
    b = g.agregar_sede(Sede(nombre="B", horarios=HORARIO))
    socios = [g.agregar_socio(Socio(nombre=f"S{i}", apellido="T", dni=f"50{i}", email=f"s{i}@t.com")) for i in range(3)]
    dune = g.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="H"))
    otro = g.agregar_libro(Libro(isbn="978-2", titulo="Neuromante", autor="G"))
    ej_dune = [g.agregar_ejemplar(Ejemplar(libro=dune, sede=a)) for _ in range(3)]
    ej_otro = g.agregar_ejemplar(Ejemplar(libro=otro, sede=a))
    return g, a, b, socios, dune, otro, ej_dune, ej_otro


def reservar(g, socio, libro, sede):
    return g.crear_reserva(id_socio=socio.id_socio, isbn=libro.isbn, id_sede=sede.id_sede)


def prestar(g, socio, ejemplar, origen, destino=None):
    return g.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=ejemplar.id_ejemplar, id_sede_origen=origen.id_sede,
                            id_sede_destino=destino.id_sede if destino else None)


def test_una_reserva_nueva_esta_activa(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)
    assert (r.estado, r.activa, r.cumplida) == ("Activa", True, False)


def test_el_prestamo_del_mismo_socio_y_titulo_cumple_la_reserva(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)

    prestar(g, socios[0], ej_dune[1], a)                           # cualquier copia del título sirve

    assert (r.estado, r.activa, r.cumplida) == ("Cumplida", False, True)


def test_tambien_se_cumple_con_un_prestamo_entre_sedes(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, b)                            # reservó para retirar en B
    prestar(g, socios[0], ej_dune[0], a, b)
    assert r.cumplida


def test_no_se_cumple_si_el_prestamo_es_de_otro_socio(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)
    prestar(g, socios[1], ej_dune[0], a)
    assert (r.estado, r.activa) == ("Activa", True)


def test_no_se_cumple_si_el_prestamo_es_de_otro_titulo(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)
    prestar(g, socios[0], ej_otro, a)
    assert r.estado == "Activa"


def test_una_reserva_cancelada_no_se_cumple(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)
    g.cancelar_reserva(r.id_reserva)
    prestar(g, socios[0], ej_dune[0], a)
    assert (r.estado, r.cumplida) == ("Cancelada", False)


def test_con_varias_reservas_del_mismo_titulo_se_cumple_solo_la_mas_antigua(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    primera = reservar(g, socios[0], dune, a)
    segunda = reservar(g, socios[0], dune, b)

    prestar(g, socios[0], ej_dune[0], a)
    assert (primera.estado, segunda.estado) == ("Cumplida", "Activa")

    prestar(g, socios[0], ej_dune[1], a)                           # el siguiente préstamo cumple la que quedaba
    assert segunda.estado == "Cumplida"


def test_un_prestamo_rechazado_no_cumple_la_reserva(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)
    prestar(g, socios[1], ej_dune[0], a)                           # la copia ya está prestada a otro
    with pytest.raises(BibliotecaExcepcion):
        prestar(g, socios[0], ej_dune[0], a)                       # se rechaza: no disponible
    assert r.estado == "Activa"


def test_una_reserva_hecha_despues_del_prestamo_no_se_cumple_retroactivamente(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    prestar(g, socios[0], ej_dune[0], a)
    r = reservar(g, socios[0], dune, a)
    assert r.estado == "Activa"


def test_una_reserva_cumplida_no_se_puede_cancelar_ni_volver_a_cumplir(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)
    prestar(g, socios[0], ej_dune[0], a)

    with pytest.raises(BibliotecaExcepcion, match="ya fue cumplida"):
        g.cancelar_reserva(r.id_reserva)
    with pytest.raises(BibliotecaExcepcion, match="no está activa"):
        r.cumplir()
    assert r.estado == "Cumplida"


def test_cancelar_sigue_funcionando_para_las_activas(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    r = reservar(g, socios[0], dune, a)
    g.cancelar_reserva(r.id_reserva)
    assert (r.estado, r.activa, r.cumplida) == ("Cancelada", False, False)


def test_el_estado_de_la_reserva_queda_guardado_en_la_base(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    cumplida = reservar(g, socios[0], dune, a)
    cancelada = reservar(g, socios[1], dune, a)
    activa = reservar(g, socios[2], dune, a)
    g.cancelar_reserva(cancelada.id_reserva)
    prestar(g, socios[0], ej_dune[0], a)

    g._cargar_desde_bd()                                           # como al reiniciar la app

    estados = {r.id_reserva: r.estado for r in g.reservas}
    assert estados == {cumplida.id_reserva: "Cumplida", cancelada.id_reserva: "Cancelada", activa.id_reserva: "Activa"}
    with sqlite3.connect(g.db_path) as cx:
        assert cx.execute("SELECT activa, cumplida FROM reservas WHERE id_reserva = ?", (cumplida.id_reserva,)).fetchone() == (0, 1)


def test_el_reporte_de_demanda_cuenta_solo_las_reservas_activas(red):
    g, a, b, socios, dune, otro, ej_dune, ej_otro = red
    reservar(g, socios[0], dune, b)
    reservar(g, socios[1], dune, b)
    prestar(g, socios[2], ej_dune[0], a, b)                        # para que el título aparezca en el ranking inter-sede
    assert Reportes(g).demanda_intersedes()["ranking"][0]["reservas_activas"] == 2

    prestar(g, socios[0], ej_dune[1], a, b)                        # cumple la reserva del socio 0
    assert Reportes(g).demanda_intersedes()["ranking"][0]["reservas_activas"] == 1


def test_migracion_agrega_la_columna_cumplida_sin_perder_reservas(tmp_path):
    db = str(tmp_path / "vieja.db")
    inicializar_bd(db)
    with sqlite3.connect(db) as cx:                                  # la tabla como era antes de "cumplida"
        cx.execute("DROP TABLE reservas")
        cx.execute("""CREATE TABLE reservas (id_reserva TEXT PRIMARY KEY, id_socio TEXT NOT NULL, isbn TEXT NOT NULL,
                      id_sede TEXT NOT NULL, fecha_solicitud TEXT NOT NULL, activa INTEGER NOT NULL DEFAULT 1)""")
        cx.execute("INSERT INTO reservas VALUES ('RES-1', 'S', '978-1', 'A', '2026-01-01', 1)")
        cx.execute("INSERT INTO reservas VALUES ('RES-2', 'S', '978-1', 'A', '2026-01-02', 0)")

    inicializar_bd(db)
    inicializar_bd(db)                                               # idempotente

    with sqlite3.connect(db) as cx:
        assert "cumplida" in [f[1] for f in cx.execute("PRAGMA table_info(reservas)")]
        assert cx.execute("SELECT id_reserva, activa, cumplida FROM reservas ORDER BY 1").fetchall() == [
            ("RES-1", 1, 0), ("RES-2", 0, 0)]


def test_datos_demo_incluyen_una_reserva_cumplida_y_dos_activas():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    cargar_datos_iniciales(g)
    assert {r.id_reserva: r.estado for r in g.reservas} == {"RES-01": "Activa", "RES-02": "Activa", "RES-03": "Cumplida"}
    p = next(p for p in g.prestamos if p.id_prestamo == "PREST-118")
    assert (p.socio.id_socio, p.ejemplar.libro.isbn) == ("SOC-05", "978-0441013593")
