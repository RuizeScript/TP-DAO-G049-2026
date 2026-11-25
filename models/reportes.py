"""
Reportes de gestión.

Son reportes "cocinados": en vez de listar datos crudos calculan indicadores (tasas, promedios, comparaciones,
semáforos y alertas) a partir de los préstamos, remitos, ejemplares y socios del sistema, para apoyar decisiones.

Cada método devuelve un diccionario con los resultados, así los consumen igual la vista HTML y el PDF.
"""
from collections import Counter
from datetime import date, timedelta

from models.enum import EstadoEjemplar, Estado
from models.operaciones import FACTOR_SANCION_POR_MORA
from models.remito import Creado, Empaquetado, Despachado, Recibido, Cancelado

# --- Umbrales de negocio: se ajustan acá sin tocar la lógica de los reportes ---
DIAS_POR_VENCER = 3          # un préstamo "por vencer" vence dentro de este número de días o menos
MORA_LEVE_MAX = 7            # mora hasta 7 días = leve
MORA_MODERADA_MAX = 14       # de 8 a 14 días = moderada; más de 14 = grave
SLA_TRANSITO_DIAS = 3        # un envío debería llegar (Despachado -> Recibido) en este plazo
DIAS_ESTANCAMIENTO = 3       # un remito sin avanzar más de N días se considera demorado
DISPONIBILIDAD_HOLGADA = 60  # % de ejemplares disponibles en una sede para considerarla holgada
DISPONIBILIDAD_AJUSTADA = 30  # por debajo de este % la sede está en situación crítica
DEMANDA_ALTA = 1.0           # solicitudes inter-sede por ejemplar: >= 1 es demanda alta
DEMANDA_MEDIA = 0.5          # >= 0.5 es demanda media


def porcentaje(parte, total) -> float:
    return round(parte * 100 / total, 1) if total else 0.0


def _promedio(valores):
    return sum(valores) / len(valores) if valores else None


def formatear_duracion(segundos) -> str:
    """Convierte segundos a un texto legible: '2 d 7 h', '3 h 20 min', '45 min', '30 s' ('—' si no hay dato)."""
    if segundos is None:
        return "—"
    segundos = int(round(segundos))
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segs = divmod(resto, 60)
    if dias:
        return f"{dias} d {horas} h" if horas else f"{dias} d"
    if horas:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    if minutos:
        return f"{minutos} min"
    return f"{segs} s"


def _fecha_evento(remito, estado: str):
    """Fecha/hora en que el remito alcanzó ese estado (según su trazabilidad), o None."""
    for evento in remito.trazabilidad:
        if evento["estado"] == estado:
            return evento["fecha_hora"]
    return None


def _segundos_entre(remito, desde: str, hasta: str):
    """Segundos transcurridos entre dos estados del remito; None si todavía no llegó a alguno de los dos."""
    inicio, fin = _fecha_evento(remito, desde), _fecha_evento(remito, hasta)
    if inicio is None or fin is None:
        return None
    return max((fin - inicio).total_seconds(), 0)


class Reportes:
    def __init__(self, gestor):
        # Se guarda el gestor (no sus listas) para leer siempre el estado actual del sistema.
        self.gestor = gestor

    def todos(self, hoy: date = None) -> dict:
        hoy = hoy or date.today()
        return {
            "activos": self.prestamos_activos_y_transito(hoy),
            "morosidad": self.morosidad_y_sanciones(hoy),
            "demanda": self.demanda_intersedes(),
            "disponibilidad": self.disponibilidad_por_sede(),
            "logistica": self.efectividad_logistica(hoy),
            "movimiento": self.movimiento_entre_sedes(),
        }

    # =========================================================================
    # 1. Préstamos activos y material en tránsito
    # =========================================================================
    def prestamos_activos_y_transito(self, hoy: date = None) -> dict:
        """Semáforo de vencimientos de los préstamos en curso + estado del pipeline logístico de los remitos."""
        hoy = hoy or date.today()
        g = self.gestor

        detalle = []
        for p in g.prestamos:
            if not p.esta_abierto:      # los devueltos y los cancelados ya no están activos
                continue
            dias_restantes = (p.fecha_vencimiento - hoy).days
            if dias_restantes < 0:
                semaforo = "Vencido"
            elif dias_restantes <= DIAS_POR_VENCER:
                semaforo = "Por vencer"
            else:
                semaforo = "En plazo"
            detalle.append({"prestamo": p, "dias_restantes": dias_restantes, "semaforo": semaforo})
        detalle.sort(key=lambda d: d["dias_restantes"])  # lo más urgente primero

        conteo = Counter(d["semaforo"] for d in detalle)
        total_activos = len(detalle)
        interbibliotecarios = sum(1 for d in detalle if d["prestamo"].es_interbibliotecario)

        # Pipeline logístico: cuántos remitos y cuántos ejemplares hay detenidos en cada etapa
        etapas = []
        for nombre, clase in (("Creado", Creado), ("Empaquetado", Empaquetado), ("Despachado", Despachado)):
            remitos_etapa = [r for r in g.remitos if isinstance(r.estado_actual, clase)]
            etapas.append({
                "estado": nombre,
                "remitos": len(remitos_etapa),
                "ejemplares": sum(r.cantidad_ejemplares for r in remitos_etapa),
            })

        envios_en_transito = []
        for r in g.remitos:
            if isinstance(r.estado_actual, Despachado):
                despacho = _fecha_evento(r, "Despachado")
                envios_en_transito.append({
                    "remito": r,
                    "dias_en_transito": (hoy - despacho.date()).days if despacho else None,
                })
        envios_en_transito.sort(key=lambda e: e["dias_en_transito"] or 0, reverse=True)

        total_ejemplares = len(g.ejemplares)
        return {
            "fecha_corte": hoy,
            "total_activos": total_activos,
            "locales": total_activos - interbibliotecarios,
            "interbibliotecarios": interbibliotecarios,
            "en_plazo": conteo["En plazo"],
            "por_vencer": conteo["Por vencer"],
            "vencidos": conteo["Vencido"],
            "pct_vencidos": porcentaje(conteo["Vencido"], total_activos),
            "pct_coleccion_prestada": porcentaje(total_activos, total_ejemplares),
            "total_ejemplares": total_ejemplares,
            "detalle": detalle,
            "etapas_logisticas": etapas,
            "remitos_en_curso": sum(e["remitos"] for e in etapas),
            "ejemplares_en_curso": sum(e["ejemplares"] for e in etapas),
            "ejemplares_en_transito": sum(e["ejemplares"] for e in etapas if e["estado"] == "Despachado"),
            "envios_en_transito": envios_en_transito,
        }

    # =========================================================================
    # 2. Morosidad y sanciones acumuladas
    # =========================================================================
    def morosidad_y_sanciones(self, hoy: date = None) -> dict:
        """
        Mora actual por gravedad y por socio, sanción proyectada (regla: FACTOR_SANCION_POR_MORA días de
        inhabilitación por día de retraso), sanciones vigentes y tasa de incumplimiento histórica.

        La sanción proyectada respeta la regla real de la devolución: si el socio ya está sancionado se mantiene la
        fecha que termina más tarde (las sanciones no se pisan ni se acortan). Por eso cada préstamo informa si
        devolverlo hoy tendría efecto ("extiende_sancion") o si el socio ya tiene una sanción igual o más larga.
        """
        hoy = hoy or date.today()
        g = self.gestor

        vencidos = []
        for p in g.prestamos:
            if not p.esta_vencido(hoy):
                continue
            dias = (hoy - p.fecha_vencimiento).days
            if dias <= MORA_LEVE_MAX:
                gravedad = "Leve"
            elif dias <= MORA_MODERADA_MAX:
                gravedad = "Moderada"
            else:
                gravedad = "Grave"
            sancion_dias = dias * FACTOR_SANCION_POR_MORA
            sancion_hasta = hoy + timedelta(days=sancion_dias)
            actual = p.socio.penalizado_hasta
            vigente = actual if actual is not None and actual >= hoy else None   # sanción que todavía rige hoy
            vencidos.append({
                "prestamo": p,
                "dias_retraso": dias,
                "gravedad": gravedad,
                "sancion_dias": sancion_dias,                      # si devolviera hoy
                "sancion_hasta": sancion_hasta,
                "sancion_vigente_hasta": vigente,
                "extiende_sancion": actual is None or sancion_hasta > actual,   # False: ya tiene una igual o más larga
            })
        vencidos.sort(key=lambda d: d["dias_retraso"], reverse=True)

        # Acumulado por socio (un mismo socio puede tener varios préstamos vencidos)
        acumulado = {}
        for d in vencidos:
            socio = d["prestamo"].socio
            fila = acumulado.setdefault(socio.id_socio, {
                "socio": socio, "prestamos_vencidos": 0, "mora_acumulada": 0, "mora_maxima": 0,
            })
            fila["prestamos_vencidos"] += 1
            fila["mora_acumulada"] += d["dias_retraso"]
            fila["mora_maxima"] = max(fila["mora_maxima"], d["dias_retraso"])
        por_socio = sorted(acumulado.values(), key=lambda f: f["mora_acumulada"], reverse=True)

        # Historial: cuántos préstamos con plazo cumplido terminaron en incumplimiento
        devueltos = [p for p in g.prestamos if p.fecha_devolucion is not None]
        devueltos_tarde = [p for p in devueltos if p.fecha_devolucion > p.fecha_vencimiento]
        resueltos = len(devueltos) + len(vencidos)       # préstamos cuyo resultado (en término o no) ya se conoce
        incumplidos = len(devueltos_tarde) + len(vencidos)

        # Sanciones vigentes hoy
        sancionados = []
        for s in g.socios.values():
            if not s.esta_habilitado(hoy):
                sancionados.append({"socio": s, "hasta": s.penalizado_hasta,
                                    "dias_restantes": (s.penalizado_hasta - hoy).days})
        sancionados.sort(key=lambda f: f["dias_restantes"], reverse=True)

        # Proyección por socio: si devolviera todo hoy, su sanción es la más larga de sus préstamos (no la suma),
        # y solo se aplica si supera a la que ya tiene.
        filas_por_socio = {}
        for d in vencidos:
            filas_por_socio.setdefault(d["prestamo"].socio.id_socio, []).append(d)
        dias_a_aplicar = [
            max(f["sancion_dias"] for f in filas)
            for filas in filas_por_socio.values() if any(f["extiende_sancion"] for f in filas)
        ]
        socios_sin_efecto = sum(1 for filas in filas_por_socio.values() if not any(f["extiende_sancion"] for f in filas))

        gravedades = Counter(d["gravedad"] for d in vencidos)
        moras = [d["dias_retraso"] for d in vencidos]
        return {
            "fecha_corte": hoy,
            "total_vencidos": len(vencidos),
            "mora_total": sum(moras),
            "mora_promedio": round(_promedio(moras), 1) if moras else 0.0,
            "mora_maxima": max(moras) if moras else 0,
            "socios_a_sancionar": len(dias_a_aplicar),             # sanciones nuevas o ampliadas si devolvieran hoy
            "sancion_proyectada_max_dias": max(dias_a_aplicar) if dias_a_aplicar else 0,
            "socios_sin_efecto": socios_sin_efecto,                # ya tienen una sanción igual o más larga
            "por_gravedad": {"Leve": gravedades["Leve"], "Moderada": gravedades["Moderada"], "Grave": gravedades["Grave"]},
            "detalle": vencidos,
            "por_socio": por_socio,
            "sancionados": sancionados,
            "pct_socios_sancionados": porcentaje(len(sancionados), len(g.socios)),
            "devueltos_tarde": len(devueltos_tarde),
            "total_resueltos": resueltos,
            "tasa_incumplimiento": porcentaje(incumplidos, resueltos),
        }

    # =========================================================================
    # 3. Demanda de libros para préstamos inter-sedes
    # =========================================================================
    def demanda_intersedes(self) -> dict:
        """Ranking de títulos más pedidos entre sedes, contrastado con su oferta (ejemplares) y sus reservas."""
        g = self.gestor
        # Las solicitudes canceladas (por un remito cancelado) siguen contando: el pedido existió, la demanda es real.
        inter = [p for p in g.prestamos if p.es_interbibliotecario]

        acumulado = {}
        for p in inter:
            libro = p.ejemplar.libro
            fila = acumulado.setdefault(libro.isbn, {"libro": libro, "solicitudes": 0, "rutas": Counter()})
            fila["solicitudes"] += 1
            fila["rutas"][(p.sede_origen.nombre, p.sede_destino.nombre)] += 1

        ranking = []
        for isbn, fila in acumulado.items():
            ejemplares = [e for e in g.ejemplares.values() if e.libro.isbn == isbn]
            solicitudes = fila["solicitudes"]
            por_ejemplar = round(solicitudes / len(ejemplares), 2) if ejemplares else None
            if por_ejemplar is not None and por_ejemplar >= DEMANDA_ALTA:
                nivel = "Alta"
            elif por_ejemplar is not None and por_ejemplar >= DEMANDA_MEDIA:
                nivel = "Media"
            else:
                nivel = "Baja"
            (origen, destino), _ = sorted(fila["rutas"].items(), key=lambda kv: (-kv[1], kv[0]))[0]
            ranking.append({
                "libro": fila["libro"],
                "solicitudes": solicitudes,
                "pct_del_total": porcentaje(solicitudes, len(inter)),
                "ejemplares_red": len(ejemplares),
                "ejemplares_disponibles": sum(1 for e in ejemplares if e.esta_disponible()),
                "solicitudes_por_ejemplar": por_ejemplar,
                "reservas_activas": sum(1 for r in g.reservas if r.activa and r.libro.isbn == isbn),
                "ruta_principal": f"{origen} → {destino}",
                "nivel_demanda": nivel,
            })
        ranking.sort(key=lambda f: (-f["solicitudes"], f["libro"].titulo))
        for posicion, fila in enumerate(ranking, start=1):
            fila["posicion"] = posicion

        total_prestamos = len(g.prestamos)
        return {
            "total_prestamos": total_prestamos,
            "total_intersede": len(inter),
            "pct_intersede": porcentaje(len(inter), total_prestamos),
            "titulos_distintos": len(ranking),
            "concentracion_top3": porcentaje(sum(f["solicitudes"] for f in ranking[:3]), len(inter)),
            "titulos_demanda_alta": sum(1 for f in ranking if f["nivel_demanda"] == "Alta"),
            "ranking": ranking,
        }

    # =========================================================================
    # 4. Disponibilidad de catálogo por sede
    # =========================================================================
    def disponibilidad_por_sede(self) -> dict:
        """Tasa de disponibilidad, desglose por estado, estado físico y cobertura del catálogo de cada sede."""
        g = self.gestor
        total_titulos = len(g.libros)
        danados = (Estado.DETERIORADO, Estado.DANADO)

        sedes = []
        for sede in g.sedes.values():
            ejemplares = [e for e in g.ejemplares.values() if e.sede.id_sede == sede.id_sede]
            por_estado = {est.value: sum(1 for e in ejemplares if e.estado_ejemplar == est) for est in EstadoEjemplar}
            disponibles = por_estado[EstadoEjemplar.DISPONIBLE.value]
            tasa = porcentaje(disponibles, len(ejemplares))

            titulos = {e.libro.isbn for e in ejemplares}
            titulos_disponibles = {e.libro.isbn for e in ejemplares if e.esta_disponible()}

            if not sede.activa:
                situacion = "Inactiva"
            elif not ejemplares:
                situacion = "Sin stock"
            elif tasa >= DISPONIBILIDAD_HOLGADA:
                situacion = "Holgada"
            elif tasa >= DISPONIBILIDAD_AJUSTADA:
                situacion = "Ajustada"
            else:
                situacion = "Crítica"

            sedes.append({
                "sede": sede,
                "total": len(ejemplares),
                "por_estado": por_estado,
                "disponibles": disponibles,
                "no_disponibles": len(ejemplares) - disponibles,
                "tasa_disponibilidad": tasa,
                "titulos": len(titulos),
                "titulos_agotados": len(titulos - titulos_disponibles),   # tiene el título pero ninguna copia libre
                "cobertura_catalogo": porcentaje(len(titulos_disponibles), total_titulos),
                "ejemplares_deteriorados": sum(1 for e in ejemplares if e.estado in danados),
                "situacion": situacion,
            })
        # las más comprometidas primero; las sedes inactivas o sin stock no compiten y van al final
        sedes.sort(key=lambda s: (s["situacion"] in ("Inactiva", "Sin stock"), s["tasa_disponibilidad"]))

        # Visión de toda la red
        todos = list(g.ejemplares.values())
        disponibles_red = sum(1 for e in todos if e.esta_disponible())
        por_libro = {}
        for e in todos:
            por_libro.setdefault(e.libro.isbn, []).append(e)
        agotados = [
            ejs[0].libro for ejs in por_libro.values() if not any(e.esta_disponible() for e in ejs)
        ]
        return {
            "sedes": sedes,
            "total_ejemplares": len(todos),
            "disponibles_red": disponibles_red,
            "tasa_red": porcentaje(disponibles_red, len(todos)),
            "titulos_agotados_red": sorted(agotados, key=lambda l: l.titulo),
            "ejemplares_deteriorados": sum(1 for e in todos if e.estado in danados),
            "sedes_criticas": sum(1 for s in sedes if s["situacion"] == "Crítica"),
        }

    # =========================================================================
    # 5. Efectividad logística: tasa de envíos exitosos e incidencias
    # =========================================================================
    def efectividad_logistica(self, hoy: date = None) -> dict:
        """
        Éxito = remito entregado dentro del SLA de tránsito. Incidencias = entregas tardías, remitos estancados
        (sin avanzar más de DIAS_ESTANCAMIENTO días) y remitos cancelados estando ya en tránsito.
        Un remito cancelado ANTES de salir no es una falla logística: no entra en las tasas ni en el agrupamiento,
        solo se informa aparte. Incluye tiempos promedio por etapa y el efecto del agrupamiento.
        """
        hoy = hoy or date.today()
        remitos = self.gestor.remitos

        recibidos = [r for r in remitos if isinstance(r.estado_actual, Recibido)]
        cancelados = [r for r in remitos if isinstance(r.estado_actual, Cancelado)]
        cancelados_en_transito = [r for r in cancelados if r.fue_despachado]
        cancelados_sin_salir = [r for r in cancelados if not r.fue_despachado]
        en_curso = [r for r in remitos if not isinstance(r.estado_actual, (Recibido, Cancelado))]
        # Remitos que efectivamente entran en la evaluación logística: todos menos los que nunca salieron
        evaluados = [r for r in remitos if not any(r is c for c in cancelados_sin_salir)]

        incidencias, a_tiempo = [], 0
        for r in recibidos:
            transito = _segundos_entre(r, "Despachado", "Recibido")
            if transito is not None and transito > SLA_TRANSITO_DIAS * 86400:
                incidencias.append({
                    "remito": r, "tipo": "Entrega tardía", "dias": round(transito / 86400, 1),
                    "detalle": f"Tránsito de {formatear_duracion(transito)} (SLA: {SLA_TRANSITO_DIAS} d)",
                })
            else:
                a_tiempo += 1

        estancados = 0
        for r in en_curso:
            ultimo = r.trazabilidad[-1]["fecha_hora"]
            dias_sin_avance = (hoy - ultimo.date()).days
            if dias_sin_avance > DIAS_ESTANCAMIENTO:
                estancados += 1
                incidencias.append({
                    "remito": r, "tipo": "Estancado", "dias": dias_sin_avance,
                    "detalle": f"Lleva {dias_sin_avance} días en estado {r.estado_actual}",
                })
        for r in cancelados_en_transito:
            en_camino = _segundos_entre(r, "Despachado", "Cancelado")
            incidencias.append({
                "remito": r, "tipo": "Cancelado en tránsito",
                "dias": round(en_camino / 86400, 1) if en_camino is not None else 0,
                "detalle": f"Se canceló tras {formatear_duracion(en_camino)} en camino: {r.motivo_cancelacion}",
            })
        incidencias.sort(key=lambda i: i["dias"], reverse=True)

        etapas = []
        for nombre, desde, hasta in (
            ("Espera de armado (Creado → Empaquetado)", "Creado", "Empaquetado"),
            ("Preparación (Empaquetado → Despachado)", "Empaquetado", "Despachado"),
            ("Tránsito (Despachado → Recibido)", "Despachado", "Recibido"),
            ("Ciclo total (Creado → Recibido)", "Creado", "Recibido"),
        ):
            duraciones = [s for s in (_segundos_entre(r, desde, hasta) for r in remitos) if s is not None]
            etapas.append({
                "etapa": nombre,
                "remitos": len(duraciones),
                "promedio_s": _promedio(duraciones),
                "maximo_s": max(duraciones) if duraciones else None,
            })

        ejemplares_enviados = sum(r.cantidad_ejemplares for r in evaluados)
        # envíos cuyo resultado ya se puede evaluar (un cancelado en tránsito es un envío fallido)
        resueltos = len(recibidos) + estancados + len(cancelados_en_transito)
        return {
            "fecha_corte": hoy,
            "total_remitos": len(remitos),
            "remitos_evaluados": len(evaluados),
            "recibidos": len(recibidos),
            "en_curso": len(en_curso),
            "cancelados": len(cancelados),
            "cancelados_sin_salir": len(cancelados_sin_salir),
            "cancelados_en_transito": len(cancelados_en_transito),
            "entregados_a_tiempo": a_tiempo,
            "entregas_tardias": len(recibidos) - a_tiempo,
            "estancados": estancados,
            "tasa_entrega": porcentaje(len(recibidos), len(evaluados)),
            "tasa_exito": porcentaje(a_tiempo, resueltos),
            "total_incidencias": len(incidencias),
            "incidencias": incidencias,
            "tiempos_por_etapa": etapas,
            "ejemplares_enviados": ejemplares_enviados,
            "ejemplares_por_remito": round(ejemplares_enviados / len(evaluados), 2) if evaluados else 0.0,
            # sin agrupar, cada ejemplar habría viajado en su propio envío
            "envios_evitados": ejemplares_enviados - len(evaluados),
            "pct_envios_evitados": porcentaje(ejemplares_enviados - len(evaluados), ejemplares_enviados),
            "remitos_por_estado": {
                nombre: sum(1 for r in remitos if isinstance(r.estado_actual, clase))
                for nombre, clase in (("Creado", Creado), ("Empaquetado", Empaquetado),
                                      ("Despachado", Despachado), ("Recibido", Recibido), ("Cancelado", Cancelado))
            },
        }

    # =========================================================================
    # 6. Movimiento de ejemplares entre sedes
    # =========================================================================
    def movimiento_entre_sedes(self) -> dict:
        """Envíos por ruta (origen → destino) con tiempo de tránsito, y balance de ejemplares enviados/recibidos por sede."""
        # Un remito cancelado no movió ejemplares entre sedes: no cuenta como movimiento
        remitos = [r for r in self.gestor.remitos if not isinstance(r.estado_actual, Cancelado)]

        rutas = {}
        balance = {}

        def fila_balance(sede):
            return balance.setdefault(sede.id_sede, {
                "sede": sede, "enviados": 0, "recibidos": 0, "por_salir": 0, "en_camino": 0,
            })

        for r in remitos:
            n = r.cantidad_ejemplares
            origen, destino = r.sede_origen, r.sede_destino

            ruta = rutas.setdefault((origen.id_sede, destino.id_sede), {
                "origen": origen, "destino": destino, "remitos": 0, "ejemplares": 0, "entregados": 0, "transitos": [],
            })
            ruta["remitos"] += 1
            ruta["ejemplares"] += n

            if isinstance(r.estado_actual, (Creado, Empaquetado)):
                fila_balance(origen)["por_salir"] += n
            elif isinstance(r.estado_actual, Despachado):
                fila_balance(origen)["enviados"] += n
                fila_balance(destino)["en_camino"] += n
            elif isinstance(r.estado_actual, Recibido):
                fila_balance(origen)["enviados"] += n
                fila_balance(destino)["recibidos"] += n
                ruta["entregados"] += n
                transito = _segundos_entre(r, "Despachado", "Recibido")
                if transito is not None:
                    ruta["transitos"].append(transito)

        tabla_rutas = []
        for ruta in rutas.values():
            tabla_rutas.append({
                "origen": ruta["origen"],
                "destino": ruta["destino"],
                "remitos": ruta["remitos"],
                "ejemplares": ruta["ejemplares"],
                "ejemplares_por_remito": round(ruta["ejemplares"] / ruta["remitos"], 2),
                "entregados": ruta["entregados"],
                "transito_promedio_s": _promedio(ruta["transitos"]),
            })
        tabla_rutas.sort(key=lambda f: (-f["ejemplares"], f["origen"].nombre, f["destino"].nombre))

        sedes = []
        for fila in balance.values():
            saldo = fila["recibidos"] - fila["enviados"]
            fila["saldo"] = saldo
            fila["perfil"] = "Receptora neta" if saldo > 0 else "Emisora neta" if saldo < 0 else "Equilibrada"
            sedes.append(fila)
        sedes.sort(key=lambda f: f["saldo"])

        transitos = [s for ruta in rutas.values() for s in ruta["transitos"]]
        return {
            "total_remitos": len(remitos),
            "total_ejemplares": sum(r.cantidad_ejemplares for r in remitos),
            "rutas_activas": len(tabla_rutas),
            "ruta_principal": tabla_rutas[0] if tabla_rutas else None,
            "sede_mas_emisora": sedes[0] if sedes and sedes[0]["saldo"] < 0 else None,
            "sede_mas_receptora": sedes[-1] if sedes and sedes[-1]["saldo"] > 0 else None,
            "transito_promedio_s": _promedio(transitos),
            "rutas": tabla_rutas,
            "balance_sedes": sedes,
        }
