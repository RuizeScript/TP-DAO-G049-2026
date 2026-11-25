"""Sedes: formato obligatorio de horarios y baja/reactivación con motivo (columna 'comentarios')."""
import sqlite3
import pytest

from models.gestor import GestorBiblioteca
from models.entidades import Sede, Socio, Libro, Ejemplar
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


# --- Editar sedes ---

def test_editar_sede_cambia_los_datos_y_persiste_sin_tocar_el_estado(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", direccion="Calle 1", contacto="a@r.org", horarios=HORARIO))
    id_original = sede.id_sede

    editada = gestor.editar_sede(id_original, "  Norte Nueva ", "Calle 2", "b@r.org", "lun a sab 8:00 - 12:00")

    assert editada is sede
    assert (sede.id_sede, sede.nombre, sede.direccion, sede.contacto) == (id_original, "Norte Nueva", "Calle 2", "b@r.org")
    assert (sede.horarios, sede.activa, sede.comentarios) == ("Lun a Sáb 08:00 - 12:00", True, "")   # horario normalizado
    gestor._cargar_desde_bd()
    recargada = gestor.sedes[id_original]
    assert (recargada.nombre, recargada.direccion, recargada.contacto, recargada.horarios) == (
        "Norte Nueva", "Calle 2", "b@r.org", "Lun a Sáb 08:00 - 12:00")


def test_editar_sede_con_datos_invalidos_no_cambia_nada(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", direccion="Calle 1", contacto="a@r.org", horarios=HORARIO))
    with pytest.raises(HorarioInvalidoError):
        gestor.editar_sede(sede.id_sede, "Otro nombre", "Calle 2", "b@r.org", "Cerrada")
    for nombre, direccion, contacto in [("", "Calle 2", "b@r.org"), ("N", "  ", "b@r.org"), ("N", "Calle 2", "")]:
        with pytest.raises(BibliotecaExcepcion, match="obligatorios"):
            gestor.editar_sede(sede.id_sede, nombre, direccion, contacto, HORARIO)
    assert (sede.nombre, sede.direccion, sede.contacto, sede.horarios) == ("Norte", "Calle 1", "a@r.org", HORARIO)
    gestor._cargar_desde_bd()
    assert gestor.sedes[sede.id_sede].nombre == "Norte"


def test_editar_sede_inexistente_falla(gestor):
    with pytest.raises(BibliotecaExcepcion, match="no encontrada"):
        gestor.editar_sede("SED-99", "N", "D", "C", HORARIO)


def test_editar_sede_inactiva_permite_corregir_el_motivo_pero_no_dejarlo_vacio(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Sur", direccion="D", contacto="C", horarios=HORARIO, activa=False, comentarios="Obras"))
    gestor.editar_sede(sede.id_sede, "Sur", "D", "C", HORARIO, comentarios="  Obras hasta marzo ")
    assert (sede.activa, sede.comentarios) == (False, "Obras hasta marzo")

    gestor.editar_sede(sede.id_sede, "Sur 2", "D", "C", HORARIO)                 # sin tocar el motivo: se conserva
    assert sede.comentarios == "Obras hasta marzo"

    with pytest.raises(BibliotecaExcepcion, match="motivo"):
        gestor.editar_sede(sede.id_sede, "Sur 3", "D", "C", HORARIO, comentarios="   ")
    assert (sede.nombre, sede.comentarios) == ("Sur 2", "Obras hasta marzo")
    gestor._cargar_desde_bd()
    assert gestor.sedes[sede.id_sede].comentarios == "Obras hasta marzo"


def test_editar_sede_activa_ignora_comentarios(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", direccion="D", contacto="C", horarios=HORARIO))
    gestor.editar_sede(sede.id_sede, "Norte", "D", "C", HORARIO, comentarios="algo suelto")
    assert sede.comentarios == ""


def test_editar_sede_se_ve_en_los_ejemplares_que_la_usan(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", direccion="D", contacto="C", horarios=HORARIO))
    libro = gestor.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="H"))
    ejemplar = gestor.agregar_ejemplar(Ejemplar(libro=libro, sede=sede))
    gestor.editar_sede(sede.id_sede, "Norte Renovada", "D", "C", HORARIO)
    assert ejemplar.sede.nombre == "Norte Renovada"          # mismo objeto Sede: no quedan copias desactualizadas


# --- Eliminar sedes ---

def test_eliminar_sede_sin_registros_la_borra_de_memoria_y_de_la_base(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Norte", direccion="D", contacto="C", horarios=HORARIO))
    otra = gestor.agregar_sede(Sede(nombre="Sur", direccion="D", contacto="C", horarios=HORARIO))
    assert gestor.referencias_de_sede(sede.id_sede) == []

    borrada = gestor.eliminar_sede(sede.id_sede)

    assert borrada is sede
    assert list(gestor.sedes) == [otra.id_sede]
    with sqlite3.connect(gestor.db_path) as cx:
        assert [f[0] for f in cx.execute("SELECT id_sede FROM sedes")] == [otra.id_sede]
    gestor._cargar_desde_bd()
    assert list(gestor.sedes) == [otra.id_sede]


def test_eliminar_sede_inexistente_falla(gestor):
    with pytest.raises(BibliotecaExcepcion, match="no encontrada"):
        gestor.eliminar_sede("SED-99")


def test_eliminar_sede_inactiva_tambien_se_puede(gestor):
    sede = gestor.agregar_sede(Sede(nombre="Sur", direccion="D", contacto="C", horarios=HORARIO, activa=False, comentarios="Obras"))
    gestor.eliminar_sede(sede.id_sede)
    assert gestor.sedes == {}


@pytest.fixture
def red_minima(gestor):
    a = gestor.agregar_sede(Sede(nombre="A", direccion="D", contacto="C", horarios=HORARIO))
    b = gestor.agregar_sede(Sede(nombre="B", direccion="D", contacto="C", horarios=HORARIO))
    libro = gestor.agregar_libro(Libro(isbn="978-1", titulo="Dune", autor="H"))
    socio = gestor.agregar_socio(Socio(nombre="Ana", apellido="Paz", dni="111", email="a@t.com"))
    return gestor, a, b, libro, socio


def test_no_se_elimina_una_sede_con_ejemplares(red_minima):
    gestor, a, b, libro, socio = red_minima
    gestor.agregar_ejemplar(Ejemplar(libro=libro, sede=a))
    gestor.agregar_ejemplar(Ejemplar(libro=libro, sede=a))

    assert gestor.referencias_de_sede(a.id_sede) == ["2 ejemplares"]
    with pytest.raises(BibliotecaExcepcion, match="2 ejemplares"):
        gestor.eliminar_sede(a.id_sede)
    assert a.id_sede in gestor.sedes
    gestor._cargar_desde_bd()                                  # sigue en la base y la carga no se rompe
    assert a.id_sede in gestor.sedes
    assert gestor.eliminar_sede(b.id_sede).id_sede == b.id_sede      # la otra, sin registros, sí se puede


def test_no_se_elimina_una_sede_con_reservas(red_minima):
    gestor, a, b, libro, socio = red_minima
    gestor.crear_reserva(id_socio=socio.id_socio, isbn=libro.isbn, id_sede=b.id_sede)

    assert gestor.referencias_de_sede(b.id_sede) == ["1 reserva"]
    with pytest.raises(BibliotecaExcepcion, match="1 reserva"):
        gestor.eliminar_sede(b.id_sede)


def test_no_se_elimina_una_sede_con_prestamos_ni_remitos_ni_siendo_destino(red_minima):
    gestor, a, b, libro, socio = red_minima
    ejemplar = gestor.agregar_ejemplar(Ejemplar(libro=libro, sede=a))
    gestor.crear_prestamo(id_socio=socio.id_socio, id_ejemplar=ejemplar.id_ejemplar,
                          id_sede_origen=a.id_sede, id_sede_destino=b.id_sede)

    # B no tiene ejemplares propios, pero es destino de un préstamo y de un remito
    assert gestor.referencias_de_sede(b.id_sede) == ["1 préstamo", "1 remito"]
    with pytest.raises(BibliotecaExcepcion, match="1 préstamo, 1 remito"):
        gestor.eliminar_sede(b.id_sede)
    assert gestor.referencias_de_sede(a.id_sede) == ["1 ejemplar", "1 préstamo", "1 remito"]
    with pytest.raises(BibliotecaExcepcion, match="Inhabilitala"):
        gestor.eliminar_sede(a.id_sede)
    assert set(gestor.sedes) == {a.id_sede, b.id_sede}


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
