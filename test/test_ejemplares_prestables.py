"""Ejemplares que ofrece el formulario de préstamo: solo los que realmente se pueden prestar, ordenados y agrupados."""
import pytest

from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.enum import EstadoEjemplar

HORARIO = "Lun a Vie 09:00 - 18:00"


@pytest.fixture
def red():
    gestor = GestorBiblioteca()
    gestor.reiniciar_para_tests("test_biblioteca.db")
    norte = gestor.agregar_sede(Sede(nombre="Norte", horarios=HORARIO))
    centro = gestor.agregar_sede(Sede(nombre="Centro", horarios=HORARIO))
    sur = gestor.agregar_sede(Sede(nombre="Sur", horarios=HORARIO))
    socio = gestor.agregar_socio(Socio(nombre="Ana", apellido="Paz", dni="111", email="a@t.com"))
    dune = gestor.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="Herbert"))
    arte = gestor.agregar_libro(Libro(isbn="978-2", titulo="arte de la guerra", autor="Sun Tzu"))   # minúscula a propósito
    return gestor, norte, centro, sur, socio, dune, arte


def ids(ejemplares):
    return [e.id_ejemplar for e in ejemplares]


def test_solo_ofrece_ejemplares_disponibles(red):
    gestor, norte, centro, sur, socio, dune, arte = red
    libre = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    prestado = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    en_transito = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    en_prep = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    reservado = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    prestado.estado_ejemplar = EstadoEjemplar.PRESTADO
    en_transito.estado_ejemplar = EstadoEjemplar.EN_TRANSITO
    en_prep.estado_ejemplar = EstadoEjemplar.EN_PREPARACION
    reservado.estado_ejemplar = EstadoEjemplar.RESERVADO

    assert ids(gestor.ejemplares_prestables()) == [libre.id_ejemplar]


def test_no_ofrece_ejemplares_de_una_sede_dada_de_baja(red):
    gestor, norte, centro, sur, socio, dune, arte = red
    en_norte = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    en_sur = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=sur))
    gestor.cambiar_estado_sede(sur.id_sede, False, "Obras")

    assert ids(gestor.ejemplares_prestables()) == [en_norte.id_ejemplar]
    gestor.cambiar_estado_sede(sur.id_sede, True)                                   # al reactivarla vuelve a aparecer
    assert set(ids(gestor.ejemplares_prestables())) == {en_norte.id_ejemplar, en_sur.id_ejemplar}


def test_orden_por_titulo_luego_sede_luego_id(red):
    gestor, norte, centro, sur, socio, dune, arte = red
    d_norte = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    d_centro = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=centro))
    d_norte2 = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    a_sur = gestor.agregar_ejemplar(Ejemplar(libro=arte, sede=sur))

    # 'arte de la guerra' va antes que 'Dune' aunque empiece en minúscula; dentro de Dune: Centro, Norte (por ID)
    assert ids(gestor.ejemplares_prestables()) == [
        a_sur.id_ejemplar, d_centro.id_ejemplar, d_norte.id_ejemplar, d_norte2.id_ejemplar]


def test_sin_ejemplares_prestables_devuelve_lista_vacia(red):
    gestor, norte, centro, sur, socio, dune, arte = red
    prestado = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    gestor.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=prestado.id_ejemplar, id_sede_origen=norte.id_sede)

    assert gestor.ejemplares_prestables() == []


def test_el_ejemplar_prestado_deja_de_ofrecerse_y_vuelve_al_devolverlo(red):
    from datetime import date
    from models.enum import Estado
    gestor, norte, centro, sur, socio, dune, arte = red
    e = gestor.agregar_ejemplar(Ejemplar(libro=dune, sede=norte))
    p = gestor.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=e.id_ejemplar, id_sede_origen=norte.id_sede)
    assert gestor.ejemplares_prestables() == []
    gestor.registrar_devolucion(p.id_prestamo, date.today(), Estado.BUENO)
    assert ids(gestor.ejemplares_prestables()) == [e.id_ejemplar]
