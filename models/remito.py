from abc import ABC, abstractmethod
from datetime import datetime
from models.excepciones import BibliotecaExcepcion, TransicionInvalidaError

#Cualqioer estado q exista tiene q tener los metodos agregar_ejemplar, empaquetar, despachar, recibir y cancelar,
#por eso se define la clase abstracta EstadoRemito
#
# Ciclo de vida:  Creado -> Empaquetado -> Despachado -> Recibido
#                    \            |             /
#                     +-----> Cancelado <------+     (se puede cancelar desde cualquier estado que todavía no sea final)
# Recibido y Cancelado son estados FINALES: desde ahí no se puede hacer nada más.
class EstadoRemito(ABC):
    @abstractmethod
    def agregar_ejemplar(self, remito, ejemplar):
        pass

    @abstractmethod
    def empaquetar(self, remito):
        pass

    @abstractmethod
    def despachar(self, remito):
        pass

    @abstractmethod
    def recibir(self, remito):
        pass

    @abstractmethod
    def cancelar(self, remito, motivo):
        pass

    def _pasar_a_cancelado(self, remito, motivo):
        # Lo comparten los tres estados desde los que se puede cancelar; el motivo queda en la trazabilidad
        remito.estado_actual = Cancelado()
        remito.registrar_trazabilidad(motivo)

    def __str__(self):
        return self.__class__.__name__


class Creado(EstadoRemito):
    # Mientras el remito está Creado está "abierto": es el único estado que admite más ejemplares.
    def agregar_ejemplar(self, remito, ejemplar):
        if any(e.id_ejemplar == ejemplar.id_ejemplar for e in remito.ejemplares):
            raise TransicionInvalidaError(
                f"El ejemplar {ejemplar.id_ejemplar} ya está incluido en el remito {remito.id_remito}"
            )
        remito.ejemplares.append(ejemplar)

    def empaquetar(self, remito):
        if not remito.ejemplares:
            raise TransicionInvalidaError("No se puede empaquetar un remito sin ejemplares")
        remito.estado_actual = Empaquetado()
        remito.registrar_trazabilidad("Empaquetado")

    def despachar(self, remito):
        raise TransicionInvalidaError("No se puede despachar un remito que no está empaquetado")

    def recibir(self, remito):
        raise TransicionInvalidaError("No se puede recibir un remito que no está empaquetado")

    def cancelar(self, remito, motivo):
        self._pasar_a_cancelado(remito, motivo)


class Empaquetado(EstadoRemito):
    def agregar_ejemplar(self, remito, ejemplar):
        raise TransicionInvalidaError("No se pueden agregar ejemplares a un remito que ya fue empaquetado")

    def empaquetar(self, remito):
        raise TransicionInvalidaError("El remito ya ha sido empaquetado")

    def despachar(self, remito):
        remito.estado_actual = Despachado()
        remito.registrar_trazabilidad("Despachado")

    def recibir(self, remito):
        raise TransicionInvalidaError("No se puede recibir un remito que no ha sido despachado")

    def cancelar(self, remito, motivo):
        self._pasar_a_cancelado(remito, motivo)


class Despachado(EstadoRemito):
    def agregar_ejemplar(self, remito, ejemplar):
        raise TransicionInvalidaError("No se pueden agregar ejemplares a un remito que ya fue despachado")

    def empaquetar(self, remito):
        raise TransicionInvalidaError("No se puede empaquetar un remito que ya ha sido despachado")

    def despachar(self, remito):
        raise TransicionInvalidaError("El remito ya ha sido despachado")

    def recibir(self, remito):
        remito.estado_actual = Recibido()
        remito.registrar_trazabilidad("Recibido")

    def cancelar(self, remito, motivo):
        # En tránsito también se puede cancelar (se cayó una sede, falló el transporte, etc.)
        self._pasar_a_cancelado(remito, motivo)


class Recibido(EstadoRemito):
    def agregar_ejemplar(self, remito, ejemplar):
        raise TransicionInvalidaError("No se pueden agregar ejemplares a un remito que ya fue recibido")

    def empaquetar(self, remito):
        raise TransicionInvalidaError("No se puede empaquetar un remito que ya ha sido recibido")

    def despachar(self, remito):
        raise TransicionInvalidaError("No se puede despachar un remito que ya ha sido recibido")

    def recibir(self, remito):
        raise TransicionInvalidaError("El remito ya ha sido recibido")

    def cancelar(self, remito, motivo):
        raise TransicionInvalidaError("No se puede cancelar un remito que ya fue recibido: el envío ya se completó")


class Cancelado(EstadoRemito):
    # Estado final: el envío se anuló y no admite ninguna operación más.
    def agregar_ejemplar(self, remito, ejemplar):
        raise TransicionInvalidaError("No se pueden agregar ejemplares a un remito cancelado")

    def empaquetar(self, remito):
        raise TransicionInvalidaError("No se puede empaquetar un remito cancelado")

    def despachar(self, remito):
        raise TransicionInvalidaError("No se puede despachar un remito cancelado")

    def recibir(self, remito):
        raise TransicionInvalidaError("No se puede recibir un remito cancelado")

    def cancelar(self, remito, motivo):
        raise TransicionInvalidaError("El remito ya fue cancelado")


class Remito:
    # Un remito agrupa N ejemplares que viajan juntos entre la misma sede de origen y de destino (relación 1 a N).
    def __init__(self, id_remito: str, sede_origen, sede_destino, ejemplares=None):
        self._id_remito = id_remito
        self.sede_origen = sede_origen
        self.sede_destino = sede_destino
        self.ejemplares = list(ejemplares) if ejemplares else []
        self.estado_actual = Creado()
        self.trazabilidad = []
        self.registrar_trazabilidad("Creado")

    @property
    def id_remito(self):
        return self._id_remito

    @id_remito.setter
    def id_remito(self, value):
        self._id_remito = value

    @property
    def cantidad_ejemplares(self) -> int:
        return len(self.ejemplares)

    @property
    def historial_trazabilidad(self):
        return self.trazabilidad

    @property
    def esta_cancelado(self) -> bool:
        return isinstance(self.estado_actual, Cancelado)

    @property
    def motivo_cancelacion(self):
        """Por qué se canceló (el último evento de la trazabilidad); None si el remito no está cancelado."""
        return self.trazabilidad[-1]["observacion"] if self.esta_cancelado else None

    @property
    def fue_despachado(self) -> bool:
        """True si el remito llegó a salir de la sede de origen (aunque después se haya cancelado en el camino)."""
        return any(evento["estado"] == "Despachado" for evento in self.trazabilidad)

    def registrar_trazabilidad(self, observacion: str):
        registro = {
            "estado": str(self.estado_actual),
            "fecha_hora": datetime.now(),
            "observacion": observacion
        }
        self.trazabilidad.append(registro)

    # delega la accion a su estado actual que es una clase con sus def, que es quien sabe como empaquetar un remito
    def agregar_ejemplar(self, ejemplar):
        self.estado_actual.agregar_ejemplar(self, ejemplar)

    def empaquetar(self):
        self.estado_actual.empaquetar(self)

    def despachar(self):
        self.estado_actual.despachar(self)

    def recibir(self):
        self.estado_actual.recibir(self)

    def cancelar(self, motivo: str):
        # El motivo es obligatorio: queda como observación del evento "Cancelado" en la trazabilidad
        motivo = (motivo or "").strip()
        if not motivo:
            raise BibliotecaExcepcion("Indicá el motivo de la cancelación del remito.")
        self.estado_actual.cancelar(self, motivo)

    def __str__(self):
        return f"Remito {self.id_remito} - Estado: {self.estado_actual} - {self.cantidad_ejemplares} ejemplar(es)"