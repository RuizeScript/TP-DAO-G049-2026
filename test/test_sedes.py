"""Sedes: formato obligatorio de horarios y baja/reactivación con motivo (columna 'comentarios')."""
import sqlite3
import pytest

from models.gestor import GestorBiblioteca
from models.entidades import Sede
from models.datos_demo import cargar_datos_iniciales
from models.horarios import normalizar_horarios
from models.excepciones import BibliotecaExcepcion, HorarioInvalidoError
from dao.database import inicializar_bd

HORARIO = "Lun a Vie 09:00 - 18:00"


@pytest.fixture
def gestor():
    g = GestorBiblioteca()
    g.reiniciar_para_tests("test_biblioteca.db")
    return g


# --- Formato de horarios ---

@pytest.mark.parametrize("escrito,canonico", [
    ("Lun a Vie 09:00 - 18:00", "Lun a Vie 09:00 - 18:00"),
    ("lun a vie 9:00 - 18:00", "Lun a Vie 09:00 - 18:00"),                      # minúsculas y hora sin cero
    ("LUN A VIE 9:00-18:00", "Lun a Vie 09:00 - 18:00"),                         # sin espacios alrededor del guion
    ("Lun a Vie 8:00 - 20:00, Sáb 9:00 - 13:00", "Lun a Vie 08:00 - 20:00, Sáb 09:00 - 13:00"),
    ("mie 10:00 – 12:00", "Mié 10:00 - 12:00"),                                  # sin acento y con guion largo
    ("sab 09:00 - 13:00", "Sáb 09:00 - 13:00"),
    ("Dom 00:00 - 23:59", "Dom 00:00 - 23:59"),
    ("Lun a Vie 09:00 - 13:00, Lun a Vie 15:00 - 19:00", "Lun a Vie 09:00 - 13:00, Lun a Vie 15:00 - 19:00"),  # corte de mediodía
    ("  Lun 09:00 - 18:00  ", "Lun 09:00 - 18:00"),
])
def test_horarios_validos_se_guardan_en_formato_canonico(escrito, canonico):
    assert normalizar_horarios(escrito) == canonico
    assert normalizar_horarios(canonico) == canonico       # normalizar dos veces no cambia nada


@pytest.mark.parametrize("escrito,fragmento_del_error", [
    ("", "obligatorios"),
    ("   ", "obligatorios"),
    (None, "obligatorios"),
    ("Cerrada temporalmente por obras", "formato"),
    ("9-18", "formato"),
    ("Lun a Vie", "formato"),                                  # faltan las horas
    ("09:00 - 18:00", "formato"),                              # faltan los días
    ("Lun a Vie 09:00", "formato"),                            # falta el cierre
    ("Lun a Vie 9:5 - 18:00", "formato"),                      # minutos de un dígito
    ("Lun a Vie 09:00 - 18:00,", "vacía"),                     # coma de más
    ("Xyz 09:00 - 18:00", "día válido"),
    ("Lun a Xyz 09:00 - 18:00", "día válido"),
    ("Vie a Lun 09:00 - 18:00", "orden de semana"),            # no se admite cruzar el fin de semana
    ("Lun a Lun 09:00 - 18:00", "orden de semana"),
    ("Lun a Vie 18:00 - 09:00", "posterior"),                  # cierra antes de abrir
    ("Lun a Vie 09:00 - 09:00", "posterior"),
    ("Lun a Vie 25:00 - 26:00", "no es válida"),
    ("Lun a Vie 09:00 - 18:60", "no es válida"),
    ("Lun a Vie 09:00 - 18:00, Mié 10:00 - 12:00", "se superponen"),
])
def test_horarios_invalidos_se_rechazan_con_un_mensaje_claro(escrito, fragmento_del_error):
    with pytest.raises(HorarioInvalidoError, match=fragmento_del_error):
        normalizar_horarios(escrito)


def test_se_detecta_superposicion_entre_rangos_de_dias():
    # 'Lun a Vie' y 'Vie a Sáb' son rangos válidos por separado, pero coinciden el viernes entre las 12:00 y las 13:00
    with pytest.raises(HorarioInvalidoError, match="Vie se superponen"):
        normalizar_horarios("Lun a Vie 09:00 - 13:00, Vie a Sáb 12:00 - 14:00")
    # en cambio, el mismo viernes en horarios que no se pisan está bien
    assert normalizar_horarios("Lun a Vie 09:00 - 13:00, Vie a Sáb 13:00 - 14:00") == "Lun a Vie 09:00 - 13:00, Vie a Sáb 13:00 - 14:00"


def test_error_de_horario_explica_el_formato_esperado():
    with pytest.raises(HorarioInvalidoError) as e:
        normalizar_horarios("de nueve a seis")
    assert "Ejemplo: Lun a Vie 09:00 - 18:00, Sáb 09:00 - 13:00" in str(e.value)


# --- Alta de sedes ---

def test_agregar_sede_guarda_el_horario_normalizado_y_se_recarga_igual(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Belgrano", horarios="lun a vie 9:00 - 18:00"))
    assert sede.horarios == "Lun a Vie 09:00 - 18:00"
    gestor._cargar_desde_bd()
    assert gestor.sedes[sede.id_sede].horarios == "Lun a Vie 09:00 - 18:00"


def test_agregar_sede_con_horario_invalido_no_guarda_nada(gestor):
    with pytest.raises(HorarioInvalidoError):
        gestor.agregar_sede(Sede(nombre="Belgrano", horarios="Cerrada temporalmente"))
    assert gestor.sedes == {}
    gestor._cargar_desde_bd()
    assert gestor.sedes == {}


def test_sede_creada_inactiva_exige_motivo(gestor):
    with pytest.raises(BibliotecaExcepcion, match="motivo"):
        gestor.agregar_sede(Sede(nombre="Clausurada", horarios=HORARIO, activa=False))
    assert gestor.sedes == {}
    sede = gestor.agregar_sede(Sede(nombre="Clausurada", horarios=HORARIO, activa=False, comentarios="  Obras  "))
    assert (sede.activa, sede.comentarios, sede.horarios) == (False, "Obras", HORARIO)


def test_sede_activa_no_conserva_comentarios(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", horarios=HORARIO, activa=True, comentarios="algo suelto"))
    assert sede.comentarios == ""


# --- Baja y reactivación ---

def test_inhabilitar_exige_motivo_y_no_cambia_nada_si_falta(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", horarios=HORARIO))
    for motivo in ("", "   ", None):
        with pytest.raises(BibliotecaExcepcion, match="motivo"):
            gestor.cambiar_estado_sede(sede.id_sede, False, motivo)
    assert sede.activa is True and sede.comentarios == ""
    gestor._cargar_desde_bd()
    assert gestor.sedes[sede.id_sede].activa is True


def test_inhabilitar_guarda_el_motivo_sin_tocar_el_horario(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", horarios="Lun a Sáb 09:00 - 18:00"))
    gestor.cambiar_estado_sede(sede.id_sede, False, "  Cerrada temporalmente por obras  ")

    assert (sede.activa, sede.comentarios, sede.horarios) == (False, "Cerrada temporalmente por obras", "Lun a Sáb 09:00 - 18:00")
    gestor._cargar_desde_bd()                                        # y queda persistido
    recargada = gestor.sedes[sede.id_sede]
    assert (recargada.activa, recargada.comentarios, recargada.horarios) == (False, "Cerrada temporalmente por obras", "Lun a Sáb 09:00 - 18:00")


def test_reactivar_borra_el_motivo_y_conserva_el_horario(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", horarios=HORARIO))
    gestor.cambiar_estado_sede(sede.id_sede, False, "Obras")
    gestor.cambiar_estado_sede(sede.id_sede, True)

    assert (sede.activa, sede.comentarios, sede.horarios) == (True, "", HORARIO)
    gestor._cargar_desde_bd()
    recargada = gestor.sedes[sede.id_sede]
    assert (recargada.activa, recargada.comentarios, recargada.horarios) == (True, "", HORARIO)


def test_dar_de_baja_otra_vez_pide_un_motivo_nuevo(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", horarios=HORARIO))
    gestor.cambiar_estado_sede(sede.id_sede, False, "Obras")
    gestor.cambiar_estado_sede(sede.id_sede, True)
    with pytest.raises(BibliotecaExcepcion):
        gestor.cambiar_estado_sede(sede.id_sede, False, "")
    gestor.cambiar_estado_sede(sede.id_sede, False, "Mudanza")
    assert sede.comentarios == "Mudanza"


# --- Bases existentes y datos demo ---

def test_migracion_agrega_la_columna_comentarios_sin_perder_sedes(tmp_path):
    db = str(tmp_path / "vieja.db")
    inicializar_bd(db)
    with sqlite3.connect(db) as cx:                                  # dejamos la tabla como era antes de 'comentarios'
        cx.execute("DROP TABLE sedes")
        cx.execute("""CREATE TABLE sedes (id_sede TEXT PRIMARY KEY, nombre TEXT NOT NULL, direccion TEXT,
                      contacto TEXT, horarios TEXT, activa INTEGER NOT NULL DEFAULT 1)""")
        cx.execute("INSERT INTO sedes VALUES ('SED-01', 'Central', 'Dir', 'c', 'Lun a Vie 09:00 - 18:00', 1)")
        cx.execute("INSERT INTO sedes VALUES ('SED-04', 'Sede Sur (En refacción)', 'Dir', 'c', 'Cerrada temporalmente por obras', 0)")

    inicializar_bd(db)                                               # <- agrega la columna
    inicializar_bd(db)                                               # idempotente

    with sqlite3.connect(db) as cx:
        assert "comentarios" in [f[1] for f in cx.execute("PRAGMA table_info(sedes)")]
        assert cx.execute("SELECT id_sede, nombre, activa, comentarios FROM sedes ORDER BY id_sede").fetchall() == [
            ("SED-01", "Central", 1, ""), ("SED-04", "Sede Sur (En refacción)", 0, ""),
        ]


def test_datos_demo_sede_sur_tiene_motivo_en_comentarios_y_horario_valido(gestor):
    cargar_datos_iniciales(gestor)
    sur = gestor.sedes["SED-04"]
    assert sur.nombre == "Sede Sur"                                  # sin '(En refacción)' en el nombre
    assert sur.activa is False
    assert sur.comentarios == "Cerrada temporalmente por obras de refacción"
    assert sur.horarios == "Lun a Vie 09:00 - 18:00"                 # el horario sigue siendo un horario
    for sede in gestor.sedes.values():
        assert normalizar_horarios(sede.horarios) == sede.horarios   # todos los horarios demo están en formato canónico
        assert (sede.comentarios != "") == (not sede.activa)         # solo las inactivas tienen motivo
