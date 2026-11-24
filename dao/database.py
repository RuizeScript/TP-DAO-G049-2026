import os
import sqlite3

DB_PATH_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "biblioteca.db")

# Un remito agrupa N ejemplares (tabla remito_ejemplares), por eso ya no guarda un id_ejemplar propio.
# El DDL se comparte entre la creación normal y la migración del esquema viejo.
_DDL_REMITOS = """
    CREATE TABLE {nombre} (
        id_remito TEXT PRIMARY KEY,
        id_sede_origen TEXT NOT NULL,
        id_sede_destino TEXT NOT NULL,
        estado_actual TEXT NOT NULL,
        FOREIGN KEY (id_sede_origen) REFERENCES sedes (id_sede),
        FOREIGN KEY (id_sede_destino) REFERENCES sedes (id_sede)
    );
"""


def _migrar_remitos_a_multiples_ejemplares(db_path: str):
    """
    Migra bases creadas con el esquema anterior (remitos.id_ejemplar: 1 remito = 1 ejemplar)
    al esquema actual (remitos 1 a N ejemplares). Conserva todos los remitos, sus ejemplares y su trazabilidad.
    Es idempotente: si la tabla ya está en el esquema nuevo no hace nada.
    """
    # isolation_level=None -> autocommit: la transacción se maneja a mano para que la migración sea atómica.
    cx = sqlite3.connect(db_path, isolation_level=None)
    try:
        columnas = [fila[1] for fila in cx.execute("PRAGMA table_info(remitos)")]
        if "id_ejemplar" not in columnas:
            return

        # Procedimiento recomendado por SQLite para rehacer una tabla: con las FK apagadas durante el cambio.
        cx.execute("PRAGMA foreign_keys = OFF;")
        cx.execute("BEGIN")
        try:
            cx.execute("""
                INSERT OR IGNORE INTO remito_ejemplares (id_remito, id_ejemplar)
                SELECT id_remito, id_ejemplar FROM remitos
            """)
            cx.execute(_DDL_REMITOS.format(nombre="remitos_nueva"))
            cx.execute("""
                INSERT INTO remitos_nueva (id_remito, id_sede_origen, id_sede_destino, estado_actual)
                SELECT id_remito, id_sede_origen, id_sede_destino, estado_actual FROM remitos
            """)
            cx.execute("DROP TABLE remitos")
            cx.execute("ALTER TABLE remitos_nueva RENAME TO remitos")
            cx.execute("COMMIT")
        except Exception:
            cx.execute("ROLLBACK")
            raise
    finally:
        cx.close()


def inicializar_bd(db_path: str = DB_PATH_DEFAULT):
    """Crea las tablas de la base de datos SQLite si no existen."""
    with sqlite3.connect(db_path) as conexion:
        conexion.execute("PRAGMA foreign_keys = ON;")
        cursor = conexion.cursor()

        # Tabla Sedes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sedes (
                id_sede TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                direccion TEXT,
                contacto TEXT,
                horarios TEXT,
                activa INTEGER NOT NULL DEFAULT 1
            );
        """)

        # Tabla Socios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS socios (
                id_socio TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                apellido TEXT NOT NULL,
                dni TEXT NOT NULL UNIQUE,
                email TEXT,
                penalizado_hasta TEXT
            );
        """)

        # Tabla Libros
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS libros (
                isbn TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                autor TEXT NOT NULL,
                categoria TEXT,
                editorial TEXT
            );
        """)

        # Tabla Ejemplares
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ejemplares (
                id_ejemplar TEXT PRIMARY KEY,
                isbn TEXT NOT NULL,
                id_sede TEXT NOT NULL,
                estado_ejemplar TEXT NOT NULL,
                estado TEXT NOT NULL,
                FOREIGN KEY (isbn) REFERENCES libros (isbn),
                FOREIGN KEY (id_sede) REFERENCES sedes (id_sede)
            );
        """)

        # Tabla Prestamos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prestamos (
                id_prestamo TEXT PRIMARY KEY,
                id_socio TEXT NOT NULL,
                id_ejemplar TEXT NOT NULL,
                id_sede_origen TEXT NOT NULL,
                id_sede_destino TEXT NOT NULL,
                fecha_inicio TEXT NOT NULL,
                fecha_vencimiento TEXT NOT NULL,
                fecha_devolucion TEXT,
                estado_devuelto TEXT,
                FOREIGN KEY (id_socio) REFERENCES socios (id_socio),
                FOREIGN KEY (id_ejemplar) REFERENCES ejemplares (id_ejemplar),
                FOREIGN KEY (id_sede_origen) REFERENCES sedes (id_sede),
                FOREIGN KEY (id_sede_destino) REFERENCES sedes (id_sede)
            );
        """)

        # Tabla Reservas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reservas (
                id_reserva TEXT PRIMARY KEY,
                id_socio TEXT NOT NULL,
                isbn TEXT NOT NULL,
                id_sede TEXT NOT NULL,
                fecha_solicitud TEXT NOT NULL,
                activa INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (id_socio) REFERENCES socios (id_socio),
                FOREIGN KEY (isbn) REFERENCES libros (isbn),
                FOREIGN KEY (id_sede) REFERENCES sedes (id_sede)
            );
        """)

        # Tabla Remitos (si ya existía con el esquema viejo, el CREATE no hace nada y migra más abajo)
        cursor.execute(_DDL_REMITOS.format(nombre="IF NOT EXISTS remitos"))

        # Tabla intermedia Remito <-> Ejemplares (un remito lleva N ejemplares)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS remito_ejemplares (
                id_remito TEXT NOT NULL,
                id_ejemplar TEXT NOT NULL,
                PRIMARY KEY (id_remito, id_ejemplar),
                FOREIGN KEY (id_remito) REFERENCES remitos (id_remito),
                FOREIGN KEY (id_ejemplar) REFERENCES ejemplares (id_ejemplar)
            );
        """)

        # Tabla Trazabilidad de Remitos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS remito_trazabilidad (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_remito TEXT NOT NULL,
                estado TEXT NOT NULL,
                fecha_hora TEXT NOT NULL,
                observacion TEXT NOT NULL,
                FOREIGN KEY (id_remito) REFERENCES remitos (id_remito)
            );
        """)

        conexion.commit()

    _migrar_remitos_a_multiples_ejemplares(db_path)


def vaciar_bd(db_path: str = DB_PATH_DEFAULT):
    """Elimina todos los datos de las tablas (utilizado principalmente para tests)."""
    with sqlite3.connect(db_path) as conexion:
        conexion.execute("PRAGMA foreign_keys = OFF;")
        cursor = conexion.cursor()
        tablas = [
            "remito_trazabilidad",
            "remito_ejemplares",
            "remitos",
            "reservas",
            "prestamos",
            "ejemplares",
            "libros",
            "socios",
            "sedes"
        ]
        for t in tablas:
            cursor.execute(f"DELETE FROM {t};")
        conexion.commit()
        conexion.execute("PRAGMA foreign_keys = ON;")
