from datetime import date, datetime, time
from models.enum import EstadoEjemplar, Estado
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.operaciones import Prestamo, Reserva
from models.remito import Remito, Creado, Recibido
from models.excepciones import (
    BibliotecaExcepcion,
    EjemplarNoDisponibleError,
    SocioInhabilitadoError,
    SedeDadaDeBajaError,
    TransicionInvalidaError
)
from dao import (
    inicializar_bd,
    vaciar_bd,
    DB_PATH_DEFAULT,
    SedeDAO,
    SocioDAO,
    LibroDAO,
    EjemplarDAO,
    PrestamoDAO,
    ReservaDAO,
    RemitoDAO
)


class GestorBiblioteca:
    _instancia = None

    def __new__(cls, db_path: str = DB_PATH_DEFAULT):
        # Patrón Singleton
        if cls._instancia is None:
            cls._instancia = super(GestorBiblioteca, cls).__new__(cls)
            cls._instancia.db_path = db_path
            cls._instancia._configurar_daos()
            cls._instancia._cargar_desde_bd()
        return cls._instancia

    def _configurar_daos(self):
        inicializar_bd(self.db_path)
        self.sede_dao = SedeDAO(self.db_path)
        self.socio_dao = SocioDAO(self.db_path)
        self.libro_dao = LibroDAO(self.db_path)
        self.ejemplar_dao = EjemplarDAO(self.db_path)
        self.prestamo_dao = PrestamoDAO(self.db_path)
        self.reserva_dao = ReservaDAO(self.db_path)
        self.remito_dao = RemitoDAO(self.db_path)

    def _cargar_desde_bd(self):
        sedes_lista = self.sede_dao.listar()
        self.sedes = {s.id_sede: s for s in sedes_lista}

        socios_lista = self.socio_dao.listar()
        self.socios = {s.id_socio: s for s in socios_lista}

        libros_lista = self.libro_dao.listar()
        self.libros = {l.isbn: l for l in libros_lista}

        ejemplares_lista = self.ejemplar_dao.listar(libros_dict=self.libros, sedes_dict=self.sedes)
        self.ejemplares = {e.id_ejemplar: e for e in ejemplares_lista}

        self.prestamos = self.prestamo_dao.listar(
            socios_dict=self.socios,
            ejemplares_dict=self.ejemplares,
            sedes_dict=self.sedes
        )

        self.reservas = self.reserva_dao.listar(
            socios_dict=self.socios,
            libros_dict=self.libros,
            sedes_dict=self.sedes
        )

        self.remitos = self.remito_dao.listar(
            ejemplares_dict=self.ejemplares,
            sedes_dict=self.sedes
        )

    def reiniciar_para_tests(self, db_path: str = "test_biblioteca.db"):
        """Permite cambiar la base de datos a una de pruebas y resetear el estado."""
        self.db_path = db_path
        self._configurar_daos()
        self._inicializar_datos()

    def _inicializar_datos(self):
        """Reinicia la base de datos y la memoria interna (útil para tests)."""
        vaciar_bd(self.db_path)
        self.sedes = {}
        self.socios = {}
        self.libros = {}
        self.ejemplares = {}
        self.prestamos = []
        self.reservas = []
        self.remitos = []

    # --- Generadores automáticos de identificadores únicos ---
    def generar_id_sede(self) -> str:
        max_id = 0
        for sid in self.sedes.keys():
            if sid.startswith("SED-"):
                try:
                    num = int(sid.split("-")[1])
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    pass
        return f"SED-{max_id + 1:02d}"

    def generar_id_socio(self) -> str:
        max_id = 0
        for sid in self.socios.keys():
            if sid.startswith("SOC-"):
                try:
                    num = int(sid.split("-")[1])
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    pass
        return f"SOC-{max_id + 1:02d}"

    def generar_id_ejemplar(self) -> str:
        max_id = 0
        for eid in self.ejemplares.keys():
            if eid.startswith("EJ-"):
                try:
                    num = int(eid.split("-")[1])
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    pass
        return f"EJ-{max_id + 1:02d}"

    def generar_id_prestamo(self) -> str:
        max_id = 100
        for p in self.prestamos:
            if p.id_prestamo and p.id_prestamo.startswith("PREST-"):
                try:
                    num = int(p.id_prestamo.split("-")[1])
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    pass
        return f"PREST-{max_id + 1:03d}"

    def generar_id_reserva(self) -> str:
        max_id = 0
        for r in self.reservas:
            if r.id_reserva and r.id_reserva.startswith("RES-"):
                try:
                    num = int(r.id_reserva.split("-")[1])
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    pass
        return f"RES-{max_id + 1:02d}"

    def generar_id_remito(self) -> str:
        max_id = 0
        for r in self.remitos:
            if r.id_remito and r.id_remito.startswith("REM-"):
                try:
                    num = int(r.id_remito.split("-")[1])
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    # IDs viejos con formato REM-PREST-xxx (1 remito por préstamo) no entran en la numeración
                    pass
        return f"REM-{max_id + 1:03d}"

    def generar_isbn(self) -> str:
        max_id = 0
        for isbn in self.libros.keys():
            if isbn.startswith("978-AUTO-"):
                try:
                    num = int(isbn.replace("978-AUTO-", ""))
                    if num > max_id:
                        max_id = num
                except (ValueError, IndexError):
                    pass
        return f"978-AUTO-{max_id + 1:04d}"

    # --- 1. Administrar Sedes ---
    def agregar_sede(self, sede: Sede) -> Sede:
        if not sede.id_sede:
            sede.id_sede = self.generar_id_sede()
        if sede.id_sede in self.sedes:
            raise BibliotecaExcepcion(f"La sede con ID '{sede.id_sede}' ya existe.")
        self.sede_dao.crear(sede)
        self.sedes[sede.id_sede] = sede
        return sede

    def obtener_sede(self, id_sede: str) -> Sede:
        sede = self.sedes.get(id_sede)
        if not sede:
            raise BibliotecaExcepcion(f"Sede '{id_sede}' no encontrada.")
        return sede

    def cambiar_estado_sede(self, id_sede: str, activa: bool):
        sede = self.obtener_sede(id_sede)
        sede.activa = activa
        self.sede_dao.actualizar_estado(id_sede, activa)

    # --- 2. Administrar Socios ---
    def agregar_socio(self, socio: Socio) -> Socio:
        if not socio.id_socio:
            socio.id_socio = self.generar_id_socio()
        if socio.id_socio in self.socios:
            raise BibliotecaExcepcion(f"El socio con ID '{socio.id_socio}' ya existe.")
        if any(s.dni == socio.dni for s in self.socios.values()):
            raise BibliotecaExcepcion(f"Ya existe un socio con DNI '{socio.dni}'.")
        self.socio_dao.crear(socio)
        self.socios[socio.id_socio] = socio
        return socio

    def obtener_socio(self, id_socio: str) -> Socio:
        socio = self.socios.get(id_socio)
        if not socio:
            raise BibliotecaExcepcion(f"Socio '{id_socio}' no encontrado.")
        return socio

    # --- 3. Administrar Catálogo de Libros y Ejemplares ---
    def agregar_libro(self, libro: Libro) -> Libro:
        if not libro.isbn:
            libro.isbn = self.generar_isbn()
        if libro.isbn in self.libros:
            raise BibliotecaExcepcion(f"El libro con ISBN '{libro.isbn}' ya existe en el catálogo.")
        self.libro_dao.crear(libro)
        self.libros[libro.isbn] = libro
        return libro

    def agregar_ejemplar(self, ejemplar: Ejemplar) -> Ejemplar:
        if not ejemplar.id_ejemplar:
            ejemplar.id_ejemplar = self.generar_id_ejemplar()
        if ejemplar.id_ejemplar in self.ejemplares:
            raise BibliotecaExcepcion(f"El ejemplar '{ejemplar.id_ejemplar}' ya está registrado.")
        self.ejemplar_dao.crear(ejemplar)
        self.ejemplares[ejemplar.id_ejemplar] = ejemplar
        return ejemplar

    def obtener_ejemplar(self, id_ejemplar: str) -> Ejemplar:
        ejemplar = self.ejemplares.get(id_ejemplar)
        if not ejemplar:
            raise BibliotecaExcepcion(f"Ejemplar '{id_ejemplar}' no encontrado.")
        return ejemplar

    # --- 4. Préstamos locales e interbibliotecarios ---
    def crear_prestamo(
        self,
        id_prestamo: str = None,
        id_socio: str = None,
        id_ejemplar: str = None,
        id_sede_origen: str = None,
        id_sede_destino: str = None,
        dias_prestamo: int = 14,
        fecha_inicio: date = None
    ) -> Prestamo:
        if not id_prestamo:
            id_prestamo = self.generar_id_prestamo()

        socio = self.obtener_socio(id_socio)
        ejemplar = self.obtener_ejemplar(id_ejemplar)
        sede_origen = self.obtener_sede(id_sede_origen)
        sede_destino = self.obtener_sede(id_sede_destino) if id_sede_destino else sede_origen

        prestamo = Prestamo(
            id_prestamo=id_prestamo,
            socio=socio,
            ejemplar=ejemplar,
            sede_origen=sede_origen,
            sede_destino=sede_destino,
            dias_prestamo=dias_prestamo,
            fecha_inicio=fecha_inicio
        )
        self.prestamo_dao.crear(prestamo)
        self.ejemplar_dao.actualizar(ejemplar)
        self.prestamos.append(prestamo)

        # Si es interbibliotecario, el ejemplar viaja en un remito (Trazabilidad), agrupado con otros de la misma ruta
        if prestamo.es_interbibliotecario:
            # Si el préstamo se carga con una fecha de inicio pasada, el remito nace ese mismo día (09:00)
            fecha_remito = datetime.combine(fecha_inicio, time(9, 0)) if fecha_inicio else None
            self._asignar_a_remito(ejemplar, sede_origen, sede_destino, fecha_remito)

        return prestamo

    def registrar_devolucion(self, id_prestamo: str, fecha_devolucion: date, estado_fisico: Estado):
        prestamo = next((p for p in self.prestamos if p.id_prestamo == id_prestamo), None)
        if not prestamo:
            raise BibliotecaExcepcion(f"Préstamo '{id_prestamo}' no encontrado.")
        prestamo.registrar_devolucion(fecha_devolucion, estado_fisico)
        self.prestamo_dao.actualizar_devolucion(id_prestamo, fecha_devolucion, estado_fisico)
        self.ejemplar_dao.actualizar(prestamo.ejemplar)
        if prestamo.socio.penalizado_hasta:
            self.socio_dao.actualizar_penalizacion(prestamo.socio.id_socio, prestamo.socio.penalizado_hasta)

    # --- 5. Trazabilidad de Remitos (Patrón State) ---
    # Un remito agrupa N ejemplares que viajan juntos de una sede origen a una sede destino (relación 1 a N).
    def obtener_remito(self, id_remito: str) -> Remito:
        remito = next((r for r in self.remitos if r.id_remito == id_remito), None)
        if not remito:
            raise BibliotecaExcepcion(f"Remito '{id_remito}' no encontrado.")
        return remito

    def buscar_remito_abierto(self, id_sede_origen: str, id_sede_destino: str):
        """Remito todavía en estado Creado (sin empaquetar) para esa ruta, o None si no hay ninguno."""
        return next(
            (
                r for r in self.remitos
                if isinstance(r.estado_actual, Creado)
                and r.sede_origen.id_sede == id_sede_origen
                and r.sede_destino.id_sede == id_sede_destino
            ),
            None
        )

    def remito_en_curso_de(self, id_ejemplar: str):
        """Remito aún no recibido en el que viaja el ejemplar, o None si no está en ninguno."""
        return next(
            (
                r for r in reversed(self.remitos)
                if not isinstance(r.estado_actual, Recibido)
                and any(e.id_ejemplar == id_ejemplar for e in r.ejemplares)
            ),
            None
        )

    def _asignar_a_remito(
        self, ejemplar: Ejemplar, sede_origen: Sede, sede_destino: Sede, fecha_hora: datetime = None
    ) -> Remito:
        """
        Agrupa los envíos: si ya hay un remito abierto (Creado) para la misma ruta, suma el ejemplar a ese remito;
        si no, abre uno nuevo. El remito deja de aceptar ejemplares recién cuando se empaqueta.
        fecha_hora (opcional) es la fecha de creación si hay que abrir un remito nuevo; por defecto, ahora.
        """
        remito = self.buscar_remito_abierto(sede_origen.id_sede, sede_destino.id_sede)
        if remito:
            remito.agregar_ejemplar(ejemplar)
            self.remito_dao.agregar_ejemplar(remito.id_remito, ejemplar.id_ejemplar)
        else:
            remito = Remito(self.generar_id_remito(), sede_origen, sede_destino, [ejemplar])
            if fecha_hora:
                remito.trazabilidad[0]["fecha_hora"] = fecha_hora
            self.remito_dao.crear(remito)
            self.remitos.append(remito)
        return remito

    def _persistir_ultimo_evento(self, remito: Remito, fecha_hora: datetime = None):
        """Guarda en la BD el último evento de trazabilidad del remito (con la misma fecha que en memoria)."""
        evento = remito.trazabilidad[-1]
        if fecha_hora:
            evento["fecha_hora"] = fecha_hora
        self.remito_dao.agregar_trazabilidad(
            remito.id_remito, evento["estado"], evento["fecha_hora"], evento["observacion"]
        )

    # fecha_hora es opcional: por defecto el evento queda con la hora actual. Sirve para cargar historial/tests.
    def empaquetar_remito(self, id_remito: str, fecha_hora: datetime = None):
        remito = self.obtener_remito(id_remito)
        remito.empaquetar()
        for ejemplar in remito.ejemplares:
            ejemplar.estado_ejemplar = EstadoEjemplar.EN_PREPARACION
            self.ejemplar_dao.actualizar(ejemplar)
        self._persistir_ultimo_evento(remito, fecha_hora)

    def despachar_remito(self, id_remito: str, fecha_hora: datetime = None):
        remito = self.obtener_remito(id_remito)
        remito.despachar()
        for ejemplar in remito.ejemplares:
            ejemplar.estado_ejemplar = EstadoEjemplar.EN_TRANSITO
            self.ejemplar_dao.actualizar(ejemplar)
        self._persistir_ultimo_evento(remito, fecha_hora)

    def recibir_remito(self, id_remito: str, fecha_hora: datetime = None):
        remito = self.obtener_remito(id_remito)
        remito.recibir()
        for ejemplar in remito.ejemplares:
            ejemplar.sede = remito.sede_destino
            ejemplar.estado_ejemplar = EstadoEjemplar.PRESTADO
            self.ejemplar_dao.actualizar(ejemplar)
        self._persistir_ultimo_evento(remito, fecha_hora)

    # --- 6. Consultar Disponibilidad ---
    def consultar_disponibilidad(self, isbn: str, id_sede: str = None):
        disponibles = [
            e for e in self.ejemplares.values() 
            if e.libro.isbn == isbn and e.esta_disponible()
        ]
        if id_sede:
            disponibles = [e for e in disponibles if e.sede.id_sede == id_sede]
        return disponibles

    # --- 7. Gestionar Reservas ---
    def crear_reserva(
        self,
        id_socio: str = None,
        isbn: str = None,
        id_sede: str = None,
        id_reserva: str = None
    ) -> Reserva:
        # Compatibilidad si se llamó positional con id_reserva primero
        if id_socio and id_socio.startswith("RES-"):
            id_reserva, id_socio, isbn, id_sede = id_socio, isbn, id_sede, id_reserva

        if not id_reserva:
            id_reserva = self.generar_id_reserva()

        socio = self.obtener_socio(id_socio)
        sede = self.obtener_sede(id_sede)
        libro = self.libros.get(isbn)
        if not libro:
            raise BibliotecaExcepcion(f"Libro con ISBN '{isbn}' no encontrado.")
        
        reserva = Reserva(id_reserva, socio, libro, sede)
        self.reserva_dao.crear(reserva)
        self.reservas.append(reserva)
        return reserva

    def cancelar_reserva(self, id_reserva: str):
        reserva = next((r for r in self.reservas if r.id_reserva == id_reserva), None)
        if not reserva:
            raise BibliotecaExcepcion(f"Reserva '{id_reserva}' no encontrada.")
        reserva.cancelar()
        self.reserva_dao.actualizar_activa(id_reserva, False)
        return reserva
