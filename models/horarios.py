"""
Validación y normalización del horario de atención de una sede.

Formato aceptado: una o más franjas separadas por coma. Cada franja es
    <día> [a <día>] <hora apertura> - <hora cierre>
con días Lun, Mar, Mié, Jue, Vie, Sáb, Dom (en orden de semana) y horas en formato 24 h.
Ejemplo:  "Lun a Vie 09:00 - 18:00, Sáb 09:00 - 13:00"

normalizar_horarios() valida el texto y lo devuelve en forma canónica (días con mayúscula y acento, horas con
dos dígitos), así todas las sedes quedan escritas igual sin importar cómo lo tipeó el usuario.
"""
import re

from models.excepciones import HorarioInvalidoError

DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_INDICE_DIA = {"lun": 0, "mar": 1, "mie": 2, "mié": 2, "jue": 3, "vie": 4, "sab": 5, "sáb": 5, "dom": 6}

EJEMPLO = "Lun a Vie 09:00 - 18:00, Sáb 09:00 - 13:00"
_AYUDA = (
    "Formato: días (un día, o 'Lun a Vie') + hora de apertura - hora de cierre en 24 h; "
    f"varias franjas separadas por coma. Ejemplo: {EJEMPLO}"
)

# [^\W\d_] = cualquier letra (incluye acentos); {3} = abreviatura de 3 letras
_FRANJA = re.compile(
    r"^(?P<d1>[^\W\d_]{3})(?:\s+a\s+(?P<d2>[^\W\d_]{3}))?"
    r"\s+(?P<h1>\d{1,2}:\d{2})\s*[-–]\s*(?P<h2>\d{1,2}:\d{2})$",
    re.IGNORECASE,
)


def _dia(abreviatura: str, franja: str) -> int:
    indice = _INDICE_DIA.get(abreviatura.lower())
    if indice is None:
        raise HorarioInvalidoError(
            f"'{abreviatura}' no es un día válido en '{franja}'. Usá: {', '.join(DIAS)}."
        )
    return indice


def _minutos(hora: str, franja: str) -> int:
    horas, minutos = (int(x) for x in hora.split(":"))
    if not (0 <= horas <= 23 and 0 <= minutos <= 59):
        raise HorarioInvalidoError(f"La hora '{hora}' no es válida en '{franja}' (de 00:00 a 23:59).")
    return horas * 60 + minutos


def _texto_hora(minutos: int) -> str:
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def normalizar_horarios(texto) -> str:
    """Devuelve el horario en formato canónico o lanza HorarioInvalidoError explicando qué está mal."""
    texto = (texto or "").strip()
    if not texto:
        raise HorarioInvalidoError(f"Los horarios son obligatorios. {_AYUDA}")

    ocupado = {dia: [] for dia in range(7)}   # franjas ya cargadas por día, para detectar superposiciones
    franjas = []
    for franja in (f.strip() for f in texto.split(",")):
        if not franja:
            raise HorarioInvalidoError(f"Hay una franja vacía (¿una coma de más?). {_AYUDA}")
        m = _FRANJA.match(franja)
        if not m:
            raise HorarioInvalidoError(f"'{franja}' no tiene un formato válido. {_AYUDA}")

        primero = _dia(m["d1"], franja)
        ultimo = _dia(m["d2"], franja) if m["d2"] else primero
        if m["d2"] and ultimo <= primero:
            raise HorarioInvalidoError(
                f"Los días de '{franja}' deben ir en orden de semana (por ejemplo 'Lun a Vie'); "
                "para un solo día escribí solo ese día."
            )

        apertura, cierre = _minutos(m["h1"], franja), _minutos(m["h2"], franja)
        if cierre <= apertura:
            raise HorarioInvalidoError(f"La hora de cierre debe ser posterior a la de apertura en '{franja}'.")

        for dia in range(primero, ultimo + 1):
            for otra_apertura, otro_cierre in ocupado[dia]:
                if apertura < otro_cierre and otra_apertura < cierre:
                    raise HorarioInvalidoError(f"Los horarios del {DIAS[dia]} se superponen.")
            ocupado[dia].append((apertura, cierre))

        dias = DIAS[primero] if primero == ultimo else f"{DIAS[primero]} a {DIAS[ultimo]}"
        franjas.append(f"{dias} {_texto_hora(apertura)} - {_texto_hora(cierre)}")

    return ", ".join(franjas)
