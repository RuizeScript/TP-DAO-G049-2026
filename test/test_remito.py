# tests/test_remito.py
import pytest
from models.remito import Remito, Creado, Empaquetado, Despachado, Recibido
from models.excepciones import TransicionInvalidaError

# --- Preparación de datos falsos (Mocks) para la prueba ---
class SedeMock:
    def __init__(self, nombre):
        self.nombre = nombre

class EjemplarMock:
    def __init__(self, id_ejemplar):
        self.id_ejemplar = id_ejemplar

def remito_con_un_ejemplar(id_remito):
    return Remito(id_remito, SedeMock("A"), SedeMock("B"), [EjemplarMock("EJ-1")])

# --- PRUEBAS DEL PATRÓN STATE ---

def test_estado_inicial_es_creado():
    origen = SedeMock("Sede A")
    destino = SedeMock("Sede B")
    ejemplar = EjemplarMock("EJ-1")

    remito = Remito("REM-001", origen, destino, [ejemplar])

    assert isinstance(remito.estado_actual, Creado)
    assert len(remito.historial_trazabilidad) == 1

def test_transicion_valida_creado_a_empaquetado():
    remito = remito_con_un_ejemplar("REM-002")
    remito.empaquetar()

    assert isinstance(remito.estado_actual, Empaquetado)
    assert len(remito.historial_trazabilidad) == 2

def test_transicion_invalida_despachar_sin_empaquetar():
    remito = remito_con_un_ejemplar("REM-003")

    with pytest.raises(TransicionInvalidaError, match="No se puede despachar un remito que no está empaquetado"):
        remito.despachar()

def test_ciclo_de_vida_completo_y_trazabilidad():
    remito = remito_con_un_ejemplar("REM-004")

    remito.empaquetar()
    remito.despachar()
    remito.recibir()

    assert isinstance(remito.estado_actual, Recibido)
    assert len(remito.historial_trazabilidad) == 4

def test_transicion_invalida_recibido_no_puede_modificarse():
    remito = remito_con_un_ejemplar("REM-005")
    remito.empaquetar()
    remito.despachar()
    remito.recibir()

    with pytest.raises(TransicionInvalidaError):
        remito.empaquetar()


# --- PRUEBAS DE LA RELACIÓN 1 A N (un remito lleva varios ejemplares) ---

def test_remito_admite_varios_ejemplares_mientras_esta_creado():
    remito = Remito("REM-010", SedeMock("A"), SedeMock("B"))
    assert remito.cantidad_ejemplares == 0

    remito.agregar_ejemplar(EjemplarMock("EJ-1"))
    remito.agregar_ejemplar(EjemplarMock("EJ-2"))
    remito.agregar_ejemplar(EjemplarMock("EJ-3"))

    assert remito.cantidad_ejemplares == 3
    assert [e.id_ejemplar for e in remito.ejemplares] == ["EJ-1", "EJ-2", "EJ-3"]

def test_remito_rechaza_ejemplar_duplicado():
    remito = remito_con_un_ejemplar("REM-011")

    with pytest.raises(TransicionInvalidaError, match="ya está incluido"):
        remito.agregar_ejemplar(EjemplarMock("EJ-1"))
    assert remito.cantidad_ejemplares == 1

@pytest.mark.parametrize("avanzar", [
    lambda r: r.empaquetar(),
    lambda r: (r.empaquetar(), r.despachar()),
    lambda r: (r.empaquetar(), r.despachar(), r.recibir()),
])
def test_remito_cerrado_no_admite_mas_ejemplares(avanzar):
    remito = remito_con_un_ejemplar("REM-012")
    avanzar(remito)

    with pytest.raises(TransicionInvalidaError, match="No se pueden agregar ejemplares"):
        remito.agregar_ejemplar(EjemplarMock("EJ-9"))
    assert remito.cantidad_ejemplares == 1

def test_no_se_puede_empaquetar_un_remito_vacio():
    remito = Remito("REM-013", SedeMock("A"), SedeMock("B"))

    with pytest.raises(TransicionInvalidaError, match="sin ejemplares"):
        remito.empaquetar()
    assert isinstance(remito.estado_actual, Creado)
