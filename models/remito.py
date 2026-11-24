from abc import ABC, abstractmethod
from datetime import datetime
from models.excepciones import TransicionInvalidaError

#Cualqioer estado q exista tiene q tener los metodos agregar_ejemplar, empaquetar, despachar y recibir,
#por eso se define la clase abstracta EstadoRemito
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


class Recibido(EstadoRemito):
    def agregar_ejemplar(self, remito, ejemplar):
        raise TransicionInvalidaError("No se pueden agregar ejemplares a un remito que ya fue recibido")

    def empaquetar(self, remito):
        raise TransicionInvalidaError("No se puede empaquetar un remito que ya ha sido recibido")

    def despachar(self, remito):
        raise TransicionInvalidaError("No se puede despachar un remito que ya ha sido recibido")

    def recibir(self, remito):
        raise TransicionInvalidaError("El remito ya ha sido recibido")


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

    def __str__(self):
        return f"Remito {self.id_remito} - Estado: {self.estado_actual} - {self.cantidad_ejemplares} ejemplar(es)"