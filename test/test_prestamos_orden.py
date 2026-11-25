"""Historial de préstamos: se muestran del más nuevo al más viejo."""
from datetime import date, timedelta

import pytest

from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar

HOY = date.today()


@pytest.fixture
def red():
    gestor = GestorBiblioteca()
    gestor.reiniciar_para_tests("test_biblioteca.db")
    sede = gestor.agregar_sede(Sede(nombre="A", horarios="Lun a Vie 09:00 - 18:00"))
    socios = [gestor.agregar_socio(Socio(nombre=f"S{i}", apellido="T", dni=f"20{i}", email=f"s{i}@t.com")) for i in range(5)]
    libro = gestor.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="H"))
    ejemplares = [gestor.agregar_ejemplar(Ejemplar(libro=libro, sede=sede)) for _ in range(5)]
    return gestor, sede, socios, ejemplares


def prestar(gestor, sede, socio, ejemplar, fecha_inicio=None):
    return gestor.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=ejemplar.id_ejemplar,
                                 id_sede_origen=sede.id_sede, fecha_inicio=fecha_inicio).id_prestamo


def test_el_prestamo_recien_creado_aparece_primero(red):
    gestor, sede, socios, ejs = red
    p1 = prestar(gestor, sede, socios[0], ejs[0])
    p2 = prestar(gestor, sede, socios[1], ejs[1])
    p3 = prestar(gestor, sede, socios[2], ejs[2])

    assert [p.id_prestamo for p in gestor.prestamos_recientes()] == [p3, p2, p1]
    assert [p.id_prestamo for p in gestor.prestamos] == [p1, p2, p3]        # la lista original no se toca


def test_se_ordena_por_fecha_de_inicio_aunque_se_hayan_cargado_en_otro_orden(red):
    gestor, sede, socios, ejs = red
    reciente = prestar(gestor, sede, socios[0], ejs[0], HOY - timedelta(days=2))
    viejo = prestar(gestor, sede, socios[1], ejs[1], HOY - timedelta(days=30))     # cargado después, pero es más viejo
    medio = prestar(gestor, sede, socios[2], ejs[2], HOY - timedelta(days=10))

    assert [p.id_prestamo for p in gestor.prestamos_recientes()] == [reciente, medio, viejo]


def test_a_igual_fecha_el_ultimo_registrado_va_primero_y_se_mantiene_al_recargar(red):
    gestor, sede, socios, ejs = red
    ayer = prestar(gestor, sede, socios[0], ejs[0], HOY - timedelta(days=1))
    a = prestar(gestor, sede, socios[1], ejs[1])
    b = prestar(gestor, sede, socios[2], ejs[2])
    c = prestar(gestor, sede, socios[3], ejs[3])

    esperado = [c, b, a, ayer]
    assert [p.id_prestamo for p in gestor.prestamos_recientes()] == esperado
    gestor._cargar_desde_bd()                                                        # como al reiniciar la app
    assert [p.id_prestamo for p in gestor.prestamos_recientes()] == esperado


def test_sin_prestamos_devuelve_lista_vacia(red):
    gestor, *_ = red
    assert gestor.prestamos_recientes() == []
