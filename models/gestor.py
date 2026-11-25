from datetime import date, datetime, time
from models.enum import EstadoEjemplar, Estado
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.operaciones import Prestamo, Reserva
from models.horarios import normalizar_horarios
from models.remito import Remito, Creado, Recibido, Cancelado
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
        # El horario debe cumplir el formato (y se guarda siempre escrito igual)
        sede.horarios = normalizar_horarios(sede.horarios)
        # 'comentarios' es el motivo de la baja: una sede inactiva debe tenerlo; una activa no
        sede.comentarios = (sede.comentarios or "").strip()
        if sede.activa:
            sede.comentarios = ""
        elif not sede.comentarios:
            raise BibliotecaExcepcion("Una sede dada de baja necesita un motivo (comentarios).")

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

    def cambiar_estado_sede(self, id_sede: str, activa: bool, comentarios: str = ""):
        """Da de baja (exige el motivo, que queda en 'comentarios') o reactiva (borra el motivo) una sede."""
        sede = self.obtener_sede(id_sede)
        if activa:
            sede.reactivar()
        else:
            sede.dar_de_baja(comentarios)
        self.sede_dao.actualizar_estado(id_sede, sede.activa, sede.comentarios)

    def editar_sede(self, id_sede: str, nombre: str, direccion: str, contacto: str, horarios: str,
                    comentarios: str = None) -> Sede:
        """
        Modifica los datos de una sede (el ID no se cambia). Valida todo antes de tocar nada.
        'comentarios' es el motivo de la baja: solo se puede editar si la sede está inactiva, y no puede quedar vacío.
        """
        sede = self.obtener_sede(id_sede)
        nombre, direccion, contacto = (nombre or "").strip(), (direccion or "").strip(), (contacto or "").strip()
        if not nombre or not direccion or not contacto:
            raise BibliotecaExcepcion("Nombre, dirección y contacto son obligatorios.")
        horarios = normalizar_horarios(horarios)

        if sede.activa:
            motivo = ""
        else:
            motivo = (comentarios if comentarios is not None else sede.comentarios or "").strip()
            if not motivo:
                raise BibliotecaExcepcion("Una sede dada de baja necesita un motivo (comentarios).")

        sede.nombre, sede.direccion, sede.contacto, sede.horarios, sede.comentarios = (
            nombre, direccion, contacto, horarios, motivo
        )
        self.sede_dao.actualizar(sede)
        return sede

    def referencias_de_sede(self, id_sede: str) -> list:
        """Qué registros usan la sede (p. ej. ['3 ejemplares', '1 préstamo']); lista vacía si no la usa nadie."""
        usos = (
            ("ejemplar", "ejemplares", sum(1 for e in self.ejemplares.values() if e.sede.id_sede == id_sede)),
            ("préstamo", "préstamos", sum(
                1 for p in self.prestamos if id_sede in (p.sede_origen.id_sede, p.sede_destino.id_sede))),
            ("reserva", "reservas", sum(1 for r in self.reservas if r.sede.id_sede == id_sede)),
            ("remito", "remitos", sum(
                1 for r in self.remitos if id_sede in (r.sede_origen.id_sede, r.sede_destino.id_sede))),
        )
        return [f"{n} {singular if n == 1 else plural}" for singular, plural, n in usos if n]

    def eliminar_sede(self, id_sede: str) -> Sede:
        """
        Borra la sede definitivamente de la base. Si algún ejemplar, préstamo, reserva o remito la usa se rechaza
        (borrarla dejaría esos registros apuntando a una sede inexistente): en ese caso corresponde inhabilitarla.
        """
        sede = self.obtener_sede(id_sede)
        usos = self.referencias_de_sede(id_sede)
        if usos:
            raise BibliotecaExcepcion(
                f"No se puede eliminar la sede '{sede.nombre}': tiene {', '.join(usos)} asociados. "
                "Inhabilitala para conservar el historial."
            )
        self.sede_dao.eliminar(id_sede)
        del self.sedes[id_sede]
        return sede

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

        # Si el socio había reservado este título, retirarlo (el préstamo) concreta la reserva
        reserva = self.reserva_activa_de(socio.id_socio, ejemplar.libro.isbn)
        if reserva is not None:
            reserva.cumplir()
            self.reserva_dao.actualizar_cumplida(reserva.id_reserva)

        return prestamo

    def prestamos_recientes(self) -> list:
        """Préstamos del más nuevo al más viejo: por fecha de inicio y, a igual fecha, el último registrado primero."""
        # sorted() es estable: partiendo de la lista invertida, los de la misma fecha conservan "último registrado primero"
        return sorted(reversed(self.prestamos), key=lambda p: p.fecha_inicio, reverse=True)

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
        """Remito todavía vigente (ni recibido ni cancelado) en el que viaja el ejemplar, o None si no está en ninguno."""
        return next(
            (
                r for r in reversed(self.remitos)
                if not isinstance(r.estado_actual, (Recibido, Cancelado))
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

    def _prestamo_abierto_de(self, ejemplar: Ejemplar):
        """Préstamo vigente (ni devuelto ni cancelado) de ese ejemplar, o None."""
        return next((p for p in self.prestamos if p.ejemplar is ejemplar and p.esta_abierto), None)

    def _prestamo_vigente_del_envio(self, ejemplar: Ejemplar, remito: Remito):
        """Préstamo vigente que está esperando este ejemplar en este remito (misma ruta de origen y destino), o None."""
        prestamo = self._prestamo_abierto_de(ejemplar)
        if (
            prestamo is not None
            and prestamo.sede_origen.id_sede == remito.sede_origen.id_sede
            and prestamo.sede_destino.id_sede == remito.sede_destino.id_sede
        ):
            return prestamo
        return None

    def prestamos_de_remito(self, remito: Remito) -> list:
        """Préstamos vigentes que esperan este envío (los que se cancelarían si el remito se cancela)."""
        return [p for p in (self._prestamo_vigente_del_envio(e, remito) for e in remito.ejemplares) if p]

    def cancelar_remito(self, id_remito: str, motivo: str, fecha_hora: datetime = None) -> dict:
        """
        Cancela el remito: pasa a Cancelado, un estado FINAL al que se llega desde Creado, Empaquetado o Despachado
        (un remito ya Recibido o ya Cancelado no se puede cancelar). Consecuencias:
          - el motivo (obligatorio) queda en la trazabilidad;
          - los ejemplares vuelven a estar Disponibles en su sede de origen (la sede de un ejemplar solo cambia al recibirlo);
          - los préstamos inter-sede que esperaban ese envío se cancelan: no vencen ni sancionan al socio.
        Devuelve un resumen ({"ejemplares": [...], "prestamos": [...]}) para informar a quien lo cancela.
        """
        remito = self.obtener_remito(id_remito)
        remito.cancelar(motivo)          # valida el motivo y que el remito no esté ya en un estado final
        motivo = remito.motivo_cancelacion

        ejemplares_liberados, prestamos_cancelados = [], []
        for ejemplar in remito.ejemplares:
            prestamo_del_envio = self._prestamo_vigente_del_envio(ejemplar, remito)
            if prestamo_del_envio is not None:
                prestamo_del_envio.cancelar(f"Remito {remito.id_remito} cancelado: {motivo}")
                self.prestamo_dao.actualizar_cancelacion(prestamo_del_envio.id_prestamo, prestamo_del_envio.motivo_cancelacion)
                prestamos_cancelados.append(prestamo_del_envio)
                liberar = True
            else:
                # Sin préstamo vigente solo se libera si el estado lo puso este envío (en preparación / en tránsito).
                # Si lo retiene otro préstamo vigente (p. ej. uno nuevo después de una devolución anticipada), no se toca.
                liberar = self._prestamo_abierto_de(ejemplar) is None and ejemplar.estado_ejemplar in (
                    EstadoEjemplar.EN_PREPARACION, EstadoEjemplar.EN_TRANSITO
                )
            if liberar:
                ejemplar.estado_ejemplar = EstadoEjemplar.DISPONIBLE
                self.ejemplar_dao.actualizar(ejemplar)
                ejemplares_liberados.append(ejemplar)

        self._persistir_ultimo_evento(remito, fecha_hora)
        return {"ejemplares": ejemplares_liberados, "prestamos": prestamos_cancelados}

    # --- 6. Consultar Disponibilidad ---
    def consultar_disponibilidad(self, isbn: str, id_sede: str = None):
        disponibles = [
            e for e in self.ejemplares.values() 
            if e.libro.isbn == isbn and e.esta_disponible()
        ]
        if id_sede:
            disponibles = [e for e in disponibles if e.sede.id_sede == id_sede]
        return disponibles

    def ejemplares_prestables(self) -> list:
        """Ejemplares que hoy se pueden prestar: disponibles y en una sede activa. Orden: título, sede e ID."""
        return sorted(
            (e for e in self.ejemplares.values() if e.esta_disponible() and e.sede.activa),
            key=lambda e: (e.libro.titulo.lower(), e.libro.isbn, e.sede.nombre.lower(), e.id_ejemplar)
        )

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

    def reserva_activa_de(self, id_socio: str, isbn: str):
        """Reserva activa (pendiente) más antigua de ese socio para ese título, o None si no tiene ninguna."""
        return next(
            (r for r in self.reservas if r.activa and r.socio.id_socio == id_socio and r.libro.isbn == isbn),
            None
        )

    def cancelar_reserva(self, id_reserva: str):
        reserva = next((r for r in self.reservas if r.id_reserva == id_reserva), None)
        if not reserva:
            raise BibliotecaExcepcion(f"Reserva '{id_reserva}' no encontrada.")
        reserva.cancelar()
        self.reserva_dao.actualizar_activa(id_reserva, False)
        return reserva
