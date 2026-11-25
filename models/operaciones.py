from datetime import date, timedelta
from models.enum import EstadoEjemplar, Estado
from models.excepciones import (
    BibliotecaExcepcion,
    SocioInhabilitadoError,
    EjemplarNoDisponibleError,
    SedeDadaDeBajaError,
)
from models.entidades import Socio, Libro, Ejemplar, Sede

# Regla de sanción: por cada día de retraso en la devolución, el socio queda inhabilitado este múltiplo de días.
# (se define acá para que la use tanto la devolución como el reporte de morosidad)
FACTOR_SANCION_POR_MORA = 2


class Prestamo:
    def __init__(
        self,
        id_prestamo: str,
        socio: Socio,
        ejemplar: Ejemplar,
        sede_origen: Sede,
        sede_destino: Sede = None,
        dias_prestamo: int = 14,
        fecha_inicio: date = None
    ):
        fecha_ref = fecha_inicio if fecha_inicio else date.today()

        # 1. Validar que el socio esté habilitado (sin penalizaciones activas)
        if not socio.esta_habilitado(fecha_ref):
            raise SocioInhabilitadoError(f"El socio {socio.nombre} {socio.apellido} se encuentra inhabilitado para préstamos.")
        
        # 2. Validar que el ejemplar esté disponible físicamente
        if not ejemplar.esta_disponible():
            raise EjemplarNoDisponibleError(f"El ejemplar {ejemplar.id_ejemplar} no está disponible.")
            
        # 3. Validar que ni la sede origen ni la destino estén dadas de baja
        sede_origen.verificar_sede()
        if sede_destino:
            sede_destino.verificar_sede()

        # 4. Validar que el ejemplar pertenezca a la sede de origen
        if ejemplar.sede.id_sede != sede_origen.id_sede:
            raise EjemplarNoDisponibleError(f"El ejemplar {ejemplar.id_ejemplar} no pertenece a la sede de origen {sede_origen.nombre}.")

        self.id_prestamo: str = id_prestamo
        self.socio: Socio = socio
        self.ejemplar: Ejemplar = ejemplar
        self.sede_origen: Sede = sede_origen
        self.sede_destino: Sede = sede_destino if sede_destino else sede_origen
        
        self.fecha_inicio: date = fecha_ref
        self.fecha_vencimiento: date = self.fecha_inicio + timedelta(days=dias_prestamo)
        self.fecha_devolucion: date = None
        self.estado_devuelto: Estado = None
        # Un préstamo inter-sede se cancela cuando se cancela el remito en el que viajaba su ejemplar
        self.cancelado: bool = False
        self.motivo_cancelacion: str = ""

        # Al concretar el préstamo, el ejemplar pasa a estar PRESTADO
        self.ejemplar.estado_ejemplar = EstadoEjemplar.PRESTADO

    @property
    def es_interbibliotecario(self) -> bool:
        """Indica si el préstamo requirió traslado entre sedes distintas."""
        return self.sede_origen.id_sede != self.sede_destino.id_sede

    def esta_vencido(self, fecha_actual: date = None) -> bool:
        """Chequea si ya venció y todavía no fue devuelto. Un préstamo cancelado nunca está vencido."""
        if fecha_actual is None:
            fecha_actual = date.today()
        return not self.fecha_devolucion and not self.cancelado and fecha_actual > self.fecha_vencimiento

    @property
    def esta_abierto(self) -> bool:
        """Sigue vigente: ni devuelto ni cancelado."""
        return self.fecha_devolucion is None and not self.cancelado

    def cancelar(self, motivo: str):
        """
        Anula el préstamo (el socio nunca recibió el libro). No cuenta como vencido ni genera sanción.
        Solo se puede cancelar uno que siga abierto; el ejemplar lo libera quien cancela (el gestor).
        """
        if self.cancelado:
            raise BibliotecaExcepcion(f"El préstamo {self.id_prestamo} ya estaba cancelado.")
        if self.fecha_devolucion is not None:
            raise BibliotecaExcepcion(f"El préstamo {self.id_prestamo} ya fue devuelto: no se puede cancelar.")
        self.cancelado = True
        self.motivo_cancelacion = (motivo or "").strip()

    def registrar_devolucion(self, fecha_devolucion: date, estado_fisico: Estado):
        """
        Registra la entrega física del libro, actualiza su estado
        y penaliza al socio si hubo demora.
        """
        if self.cancelado:
            raise BibliotecaExcepcion(f"El préstamo {self.id_prestamo} fue cancelado: no hay nada que devolver.")
        self.fecha_devolucion = fecha_devolucion
        self.estado_devuelto = estado_fisico
        self.ejemplar.estado_ejemplar = EstadoEjemplar.DISPONIBLE
        self.ejemplar.estado = estado_fisico
        # Si fue interbibliotecario y se devolvió en la sede destino, el ejemplar queda ahora radicado allí
        self.ejemplar.sede = self.sede_destino
        
        # Si se devolvió pasado el vencimiento, aplicamos sanción
        if fecha_devolucion > self.fecha_vencimiento:
            dias_retraso = (fecha_devolucion - self.fecha_vencimiento).days
            nueva_sancion = fecha_devolucion + timedelta(days=dias_retraso * FACTOR_SANCION_POR_MORA)
            # Si el socio ya tiene una sanción, queda siempre la que termina más tarde: las sanciones
            # no se pisan (una devolución con poca mora nunca le acorta una sanción mayor que ya tenía).
            actual = self.socio.penalizado_hasta
            if actual is None or nueva_sancion > actual:
                self.socio.penalizado_hasta = nueva_sancion

    def __str__(self) -> str:
        return f"Préstamo {self.id_prestamo}: Socio {self.socio.dni}, Ejemplar {self.ejemplar.id_ejemplar}, Vence: {self.fecha_vencimiento}"


class Reserva:
    def __init__(self, id_reserva: str, socio: Socio, libro: Libro, sede: Sede):
        sede.verificar_sede()
        
        if not socio.esta_habilitado(date.today()):
            raise SocioInhabilitadoError(f"El socio {socio.nombre} {socio.apellido} está inhabilitado y no puede reservar.")

        self.id_reserva: str = id_reserva
        self.socio: Socio = socio
        self.libro: Libro = libro
        self.sede: Sede = sede
        self.fecha_solicitud: date = date.today()
        # 'activa' es True solo mientras la reserva está pendiente; al cumplirse o cancelarse pasa a False
        self.activa: bool = True
        self.cumplida: bool = False

    @property
    def estado(self) -> str:
        """Activa (pendiente), Cumplida (se le prestó el libro al socio) o Cancelada."""
        if self.cumplida:
            return "Cumplida"
        return "Activa" if self.activa else "Cancelada"

    def cancelar(self):
        if self.cumplida:
            raise BibliotecaExcepcion(f"La reserva {self.id_reserva} ya fue cumplida: no se puede cancelar.")
        self.activa = False

    def cumplir(self):
        """Se concreta la reserva: el socio retiró el libro (se le registró el préstamo). Solo si sigue activa."""
        if not self.activa:
            raise BibliotecaExcepcion(f"La reserva {self.id_reserva} no está activa ({self.estado}): no se puede cumplir.")
        self.activa = False
        self.cumplida = True

    def __str__(self) -> str:
        return f"Reserva {self.id_reserva}: Libro '{self.libro.titulo}' por {self.socio.nombre} en {self.sede.nombre}"