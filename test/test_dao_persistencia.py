import os
import tempfile
import pytest
from datetime import date, datetime, timedelta
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.enum import Estado, EstadoEjemplar
from models.operaciones import Prestamo, Reserva
from models.remito import Remito
from dao.database import inicializar_bd, vaciar_bd
from dao.sede_dao import SedeDAO
from dao.socio_dao import SocioDAO
from dao.libro_dao import LibroDAO
from dao.ejemplar_dao import EjemplarDAO
from dao.prestamo_dao import PrestamoDAO
from dao.reserva_dao import ReservaDAO
from dao.remito_dao import RemitoDAO
from models.gestor import GestorBiblioteca


@pytest.fixture
def temp_db():
    import gc
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    inicializar_bd(path)
    yield path
    gc.collect()
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def test_sede_dao_crud(temp_db):
    dao = SedeDAO(temp_db)
    sede = Sede(id_sede="SED-01", nombre="Central", direccion="Corrientes 100", contacto="c@red.org", horarios="Lun a Vie 08:00 - 20:00", activa=True)
    dao.crear(sede)

    obtenida = dao.obtener_por_id("SED-01")
    assert obtenida is not None
    assert obtenida.nombre == "Central"
    assert obtenida.activa is True

    dao.actualizar_estado("SED-01", False, "Obras de refacción")
    actualizada = dao.obtener_por_id("SED-01")
    assert actualizada.activa is False
    assert actualizada.comentarios == "Obras de refacción"

    dao.actualizar_estado("SED-01", True)   # al reactivarla el motivo de la baja se borra
    reactivada = dao.obtener_por_id("SED-01")
    assert reactivada.activa is True and reactivada.comentarios == ""

    sedes = dao.listar()
    assert len(sedes) == 1


def test_socio_dao_crud(temp_db):
    dao = SocioDAO(temp_db)
    socio = Socio(id_socio="SOC-01", nombre="Juan", apellido="Perez", dni="12345678", email="juan@test.com")
    dao.crear(socio)

    obtenido = dao.obtener_por_dni("12345678")
    assert obtenido is not None
    assert obtenido.id_socio == "SOC-01"

    fecha_penal = date.today() + timedelta(days=5)
    dao.actualizar_penalizacion("SOC-01", fecha_penal)
    actualizado = dao.obtener_por_id("SOC-01")
    assert actualizado.penalizado_hasta == fecha_penal


def test_libro_y_ejemplar_dao_crud(temp_db):
    sede_dao = SedeDAO(temp_db)
    sede = Sede(id_sede="SED-01", nombre="Central", activa=True)
    sede_dao.crear(sede)

    libro_dao = LibroDAO(temp_db)
    libro = Libro(isbn="978-01", titulo="Fundación", autor="Isaac Asimov", categoria="Sci-Fi", editorial="DeBolsillo")
    libro_dao.crear(libro)

    ej_dao = EjemplarDAO(temp_db)
    ejemplar = Ejemplar(id_ejemplar="EJ-01", libro=libro, sede=sede)
    ej_dao.crear(ejemplar)

    ejemplares = ej_dao.listar(libros_dict={"978-01": libro}, sedes_dict={"SED-01": sede})
    assert len(ejemplares) == 1
    assert ejemplares[0].libro.titulo == "Fundación"

    ejemplares[0].estado_ejemplar = EstadoEjemplar.PRESTADO
    ej_dao.actualizar(ejemplares[0])
    ej_actualizado = ej_dao.obtener_por_id("EJ-01", libros_dict={"978-01": libro}, sedes_dict={"SED-01": sede})
    assert ej_actualizado.estado_ejemplar == EstadoEjemplar.PRESTADO


def test_prestamo_reserva_remito_dao(temp_db):
    # Setup base data
    sede_dao = SedeDAO(temp_db)
    sede1 = Sede("SED-01", "Central", activa=True)
    sede2 = Sede("SED-02", "Norte", activa=True)
    sede_dao.crear(sede1)
    sede_dao.crear(sede2)

    socio_dao = SocioDAO(temp_db)
    socio = Socio("SOC-01", "Ana", "Gomez", "20111222", "ana@test.com")
    socio_dao.crear(socio)

    libro_dao = LibroDAO(temp_db)
    libro = Libro("978-02", "1984", "George Orwell", "Ficción", "Penguin")
    libro_dao.crear(libro)

    ej_dao = EjemplarDAO(temp_db)
    ej = Ejemplar("EJ-02", libro=libro, sede=sede1)
    ej_dao.crear(ej)

    # PrestamoDAO
    prestamo_dao = PrestamoDAO(temp_db)
    prestamo = Prestamo("PREST-001", socio, ej, sede1, sede2, dias_prestamo=14, fecha_inicio=date.today())
    prestamo_dao.crear(prestamo)

    prestamos = prestamo_dao.listar({"SOC-01": socio}, {"EJ-02": ej}, {"SED-01": sede1, "SED-02": sede2})
    assert len(prestamos) == 1
    assert prestamos[0].es_interbibliotecario is True

    # ReservaDAO
    reserva_dao = ReservaDAO(temp_db)
    reserva = Reserva("RES-001", socio, libro, sede1)
    reserva_dao.crear(reserva)
    reservas = reserva_dao.listar({"SOC-01": socio}, {"978-02": libro}, {"SED-01": sede1})
    assert len(reservas) == 1
    assert reservas[0].activa is True

    reserva_dao.actualizar_activa("RES-001", False)
    res_actualizada = reserva_dao.obtener_por_id("RES-001", {"SOC-01": socio}, {"978-02": libro}, {"SED-01": sede1})
    assert res_actualizada.activa is False

    # RemitoDAO
    remito_dao = RemitoDAO(temp_db)
    remito = Remito("REM-001", sede1, sede2, [ej])
    remito_dao.crear(remito)
    remito_dao.agregar_trazabilidad("REM-001", "Empaquetado", datetime.now(), "Empaquetado para despacho")

    traz = remito_dao.obtener_trazabilidad("REM-001")
    assert len(traz) == 2
    assert traz[1]["estado"] == "Empaquetado"


def test_remito_dao_guarda_y_recupera_varios_ejemplares(temp_db):
    sede_dao, libro_dao, ej_dao = SedeDAO(temp_db), LibroDAO(temp_db), EjemplarDAO(temp_db)
    sede1, sede2 = Sede("SED-01", "Central", activa=True), Sede("SED-02", "Norte", activa=True)
    sede_dao.crear(sede1)
    sede_dao.crear(sede2)
    libro = Libro("978-03", "Dune", "Frank Herbert", "Sci-Fi", "Ace")
    libro_dao.crear(libro)
    ejemplares = [Ejemplar(f"EJ-0{i}", libro=libro, sede=sede1) for i in range(1, 4)]
    for e in ejemplares:
        ej_dao.crear(e)

    remito_dao = RemitoDAO(temp_db)
    remito = Remito("REM-001", sede1, sede2, ejemplares[:2])
    remito_dao.crear(remito)
    # El tercer ejemplar se suma después, con el remito todavía Creado
    remito_dao.agregar_ejemplar("REM-001", "EJ-03")

    assert remito_dao.obtener_ids_ejemplares("REM-001") == ["EJ-01", "EJ-02", "EJ-03"]

    recuperado = remito_dao.obtener_por_id(
        "REM-001",
        ejemplares_dict={e.id_ejemplar: e for e in ejemplares},
        sedes_dict={"SED-01": sede1, "SED-02": sede2},
    )
    assert recuperado.cantidad_ejemplares == 3
    assert recuperado.sede_origen.id_sede == "SED-01"
    assert recuperado.sede_destino.id_sede == "SED-02"


def test_migracion_esquema_viejo_de_remitos_conserva_datos(tmp_path):
    """Una BD creada con 'remitos.id_ejemplar' (1 remito = 1 ejemplar) pasa al esquema 1 a N sin perder nada."""
    import sqlite3
    db = str(tmp_path / "vieja.db")
    inicializar_bd(db)  # crea todo con el esquema nuevo...
    with sqlite3.connect(db) as cx:  # ...y lo reemplazamos por el esquema viejo
        cx.execute("PRAGMA foreign_keys = OFF;")
        cx.execute("DROP TABLE remito_ejemplares")
        cx.execute("DROP TABLE remitos")
        cx.execute("""
            CREATE TABLE remitos (
                id_remito TEXT PRIMARY KEY,
                id_ejemplar TEXT NOT NULL,
                id_sede_origen TEXT NOT NULL,
                id_sede_destino TEXT NOT NULL,
                estado_actual TEXT NOT NULL,
                FOREIGN KEY (id_ejemplar) REFERENCES ejemplares (id_ejemplar),
                FOREIGN KEY (id_sede_origen) REFERENCES sedes (id_sede),
                FOREIGN KEY (id_sede_destino) REFERENCES sedes (id_sede)
            )
        """)
        cx.execute("INSERT INTO sedes (id_sede, nombre) VALUES ('SED-01', 'Central'), ('SED-02', 'Norte')")
        cx.execute("INSERT INTO libros (isbn, titulo, autor) VALUES ('978-X', 'Dune', 'Herbert')")
        cx.execute("""INSERT INTO ejemplares (id_ejemplar, isbn, id_sede, estado_ejemplar, estado)
                      VALUES ('EJ-01', '978-X', 'SED-01', 'PRESTADO', 'OPTIMO')""")
        cx.execute("INSERT INTO remitos VALUES ('REM-PREST-102', 'EJ-01', 'SED-01', 'SED-02', 'Despachado')")
        cx.execute("""INSERT INTO remito_trazabilidad (id_remito, estado, fecha_hora, observacion)
                      VALUES ('REM-PREST-102', 'Creado', '2026-01-01T10:00:00', 'Creado')""")

    inicializar_bd(db)  # <- dispara la migración

    with sqlite3.connect(db) as cx:
        columnas = [f[1] for f in cx.execute("PRAGMA table_info(remitos)")]
        assert "id_ejemplar" not in columnas
        assert cx.execute("SELECT id_remito, id_sede_origen, id_sede_destino, estado_actual FROM remitos").fetchall() \
            == [("REM-PREST-102", "SED-01", "SED-02", "Despachado")]
        assert cx.execute("SELECT id_remito, id_ejemplar FROM remito_ejemplares").fetchall() \
            == [("REM-PREST-102", "EJ-01")]
        assert cx.execute("SELECT COUNT(*) FROM remito_trazabilidad").fetchone()[0] == 1
        # Las FK de la trazabilidad siguen apuntando a la tabla 'remitos' y no quedó ninguna fila huérfana
        assert [f[2] for f in cx.execute("PRAGMA foreign_key_list(remito_trazabilidad)")] == ["remitos"]
        assert cx.execute("PRAGMA foreign_key_check").fetchall() == []

    inicializar_bd(db)  # idempotente: correrla de nuevo no rompe ni duplica nada
    with sqlite3.connect(db) as cx:
        assert cx.execute("SELECT COUNT(*) FROM remito_ejemplares").fetchone()[0] == 1


def test_persistencia_recarga_en_gestor():
    # Usar el gestor y verificar persistencia
    gestor = GestorBiblioteca()
    gestor.reiniciar_para_tests("test_biblioteca.db")

    s = gestor.agregar_sede(Sede(nombre="Sede Prueba Persistencia", horarios="Lun a Vie 09:00 - 18:00", activa=True))
    soc = gestor.agregar_socio(Socio(nombre="Mario", apellido="Bros", dni="99887766", email="m@bros.com"))
    lib = gestor.agregar_libro(Libro(titulo="El Aleph", autor="Jorge Luis Borges"))
    ej = gestor.agregar_ejemplar(Ejemplar(libro=lib, sede=s))

    # Recargar datos desde la BD SQLite simulando reinicio
    gestor._cargar_desde_bd()

    assert s.id_sede in gestor.sedes
    assert gestor.sedes[s.id_sede].nombre == "Sede Prueba Persistencia"
    assert soc.id_socio in gestor.socios
    assert gestor.socios[soc.id_socio].dni == "99887766"
    assert lib.isbn in gestor.libros
    assert ej.id_ejemplar in gestor.ejemplares
