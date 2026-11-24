"""Remitos 1 a N en el gestor: los préstamos inter-sede de una misma ruta se agrupan en un único remito."""
import pytest
from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.enum import EstadoEjemplar
from models.remito import Creado, Empaquetado, Despachado, Recibido
from models.excepciones import TransicionInvalidaError


@pytest.fixture
def red():
    """Red mínima: 3 sedes, 4 socios y 4 ejemplares en la sede A (un título, tres copias + otro título)."""
    gestor = GestorBiblioteca()
    gestor.reiniciar_para_tests("test_biblioteca.db")
    sede_a = gestor.agregar_sede(Sede(nombre="A", activa=True))
    sede_b = gestor.agregar_sede(Sede(nombre="B", activa=True))
    sede_c = gestor.agregar_sede(Sede(nombre="C", activa=True))
    socios = [
        gestor.agregar_socio(Socio(nombre=f"Socio{i}", apellido="Test", dni=f"1000000{i}", email=f"s{i}@t.com"))
        for i in range(4)
    ]
    libro = gestor.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="Herbert"))
    ejemplares = [gestor.agregar_ejemplar(Ejemplar(libro=libro, sede=sede_a)) for _ in range(4)]
    return gestor, sede_a, sede_b, sede_c, socios, ejemplares


def prestar(gestor, socio, ejemplar, origen, destino):
    return gestor.crear_prestamo(
        id_socio=socio.id_socio, id_ejemplar=ejemplar.id_ejemplar,
        id_sede_origen=origen.id_sede, id_sede_destino=destino.id_sede,
    )


def test_prestamos_de_la_misma_ruta_comparten_un_unico_remito(red):
    gestor, a, b, c, socios, ejs = red

    prestar(gestor, socios[0], ejs[0], a, b)
    prestar(gestor, socios[1], ejs[1], a, b)
    prestar(gestor, socios[2], ejs[2], a, b)

    assert len(gestor.remitos) == 1
    remito = gestor.remitos[0]
    assert remito.cantidad_ejemplares == 3
    assert [e.id_ejemplar for e in remito.ejemplares] == [e.id_ejemplar for e in ejs[:3]]
    assert isinstance(remito.estado_actual, Creado)


def test_rutas_distintas_generan_remitos_distintos(red):
    gestor, a, b, c, socios, ejs = red

    prestar(gestor, socios[0], ejs[0], a, b)
    prestar(gestor, socios[1], ejs[1], a, c)   # mismo origen, otro destino
    prestar(gestor, socios[2], ejs[2], a, b)

    assert len(gestor.remitos) == 2
    por_ruta = {(r.sede_origen.id_sede, r.sede_destino.id_sede): r for r in gestor.remitos}
    assert por_ruta[(a.id_sede, b.id_sede)].cantidad_ejemplares == 2
    assert por_ruta[(a.id_sede, c.id_sede)].cantidad_ejemplares == 1


def test_prestamo_local_no_genera_remito(red):
    gestor, a, b, c, socios, ejs = red
    prestar(gestor, socios[0], ejs[0], a, a)
    assert gestor.remitos == []


def test_remito_empaquetado_se_cierra_y_el_siguiente_prestamo_abre_otro(red):
    gestor, a, b, c, socios, ejs = red
    prestar(gestor, socios[0], ejs[0], a, b)
    primero = gestor.remitos[0]
    gestor.empaquetar_remito(primero.id_remito)

    prestar(gestor, socios[1], ejs[1], a, b)

    assert len(gestor.remitos) == 2
    assert primero.cantidad_ejemplares == 1           # el remito cerrado no recibió el nuevo ejemplar
    assert isinstance(gestor.remitos[1].estado_actual, Creado)
    assert gestor.remitos[1].cantidad_ejemplares == 1
    assert gestor.remitos[1].id_remito != primero.id_remito


def test_ciclo_completo_mueve_todos_los_ejemplares_del_remito(red):
    gestor, a, b, c, socios, ejs = red
    prestar(gestor, socios[0], ejs[0], a, b)
    prestar(gestor, socios[1], ejs[1], a, b)
    remito = gestor.remitos[0]
    en_el_remito = ejs[:2]

    gestor.empaquetar_remito(remito.id_remito)
    assert all(e.estado_ejemplar == EstadoEjemplar.EN_PREPARACION for e in en_el_remito)

    gestor.despachar_remito(remito.id_remito)
    assert all(e.estado_ejemplar == EstadoEjemplar.EN_TRANSITO for e in en_el_remito)
    assert ejs[2].estado_ejemplar == EstadoEjemplar.DISPONIBLE       # los que no están en el remito no se tocan

    gestor.recibir_remito(remito.id_remito)
    assert all(e.sede.id_sede == b.id_sede for e in en_el_remito)
    assert all(e.estado_ejemplar == EstadoEjemplar.PRESTADO for e in en_el_remito)
    assert ejs[2].sede.id_sede == a.id_sede
    assert isinstance(remito.estado_actual, Recibido)
    # un solo ciclo de trazabilidad para todo el grupo: Creado, Empaquetado, Despachado, Recibido
    assert [h["estado"] for h in remito.historial_trazabilidad] == ["Creado", "Empaquetado", "Despachado", "Recibido"]


def test_remito_en_curso_de_un_ejemplar(red):
    gestor, a, b, c, socios, ejs = red
    prestar(gestor, socios[0], ejs[0], a, b)
    prestar(gestor, socios[1], ejs[1], a, b)

    assert gestor.remito_en_curso_de(ejs[1].id_ejemplar) is gestor.remitos[0]
    assert gestor.remito_en_curso_de(ejs[3].id_ejemplar) is None


def test_ids_de_remito_correlativos(red):
    gestor, a, b, c, socios, ejs = red
    prestar(gestor, socios[0], ejs[0], a, b)
    prestar(gestor, socios[1], ejs[1], a, c)
    assert [r.id_remito for r in gestor.remitos] == ["REM-001", "REM-002"]


def test_agrupacion_y_estados_se_persisten_y_se_recargan_desde_la_bd(red):
    gestor, a, b, c, socios, ejs = red
    prestar(gestor, socios[0], ejs[0], a, b)
    prestar(gestor, socios[1], ejs[1], a, b)
    gestor.empaquetar_remito(gestor.remitos[0].id_remito)

    gestor._cargar_desde_bd()   # simula reiniciar la aplicación

    assert len(gestor.remitos) == 1
    remito = gestor.remitos[0]
    assert remito.cantidad_ejemplares == 2
    assert isinstance(remito.estado_actual, Empaquetado)
    assert [h["estado"] for h in remito.historial_trazabilidad] == ["Creado", "Empaquetado"]
    # y los ejemplares recargados son los mismos objetos que maneja el gestor
    assert all(e is gestor.ejemplares[e.id_ejemplar] for e in remito.ejemplares)


def test_no_se_puede_sumar_ejemplares_a_un_remito_despachado(red):
    gestor, a, b, c, socios, ejs = red
    prestar(gestor, socios[0], ejs[0], a, b)
    remito = gestor.remitos[0]
    gestor.empaquetar_remito(remito.id_remito)
    gestor.despachar_remito(remito.id_remito)

    assert isinstance(remito.estado_actual, Despachado)
    with pytest.raises(TransicionInvalidaError):
        remito.agregar_ejemplar(ejs[3])
