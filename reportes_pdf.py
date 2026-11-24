from io import BytesIO
from datetime import date
from xml.sax.saxutils import escape

import matplotlib
matplotlib.use("Agg")  # backend sin interfaz gráfica, necesario para generar imágenes desde un server Flask
import matplotlib.pyplot as plt

from matplotlib.ticker import MaxNLocator

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

from models.reportes import formatear_duracion

_ESTILOS = getSampleStyleSheet()
_TITULO = ParagraphStyle("TituloBiblioRed", parent=_ESTILOS["Heading1"], textColor=colors.HexColor("#1d3557"))
_SUBTITULO = ParagraphStyle("Subtitulo", parent=_ESTILOS["Heading2"], textColor=colors.HexColor("#2a5784"), spaceBefore=12)
_NORMAL = _ESTILOS["Normal"]
_NOTA = ParagraphStyle("Nota", parent=_NORMAL, fontSize=8, textColor=colors.HexColor("#667468"))
_CELDA = ParagraphStyle("Celda", parent=_NORMAL, fontSize=8, leading=10)
_CELDA_ENCABEZADO = ParagraphStyle("CeldaEncabezado", parent=_CELDA, fontName="Helvetica-Bold", textColor=colors.white)
_KPI = ParagraphStyle("Kpi", parent=_NORMAL, fontSize=8, leading=12)

_COLOR_PRIMARIO = "#1d3557"
_COLOR_SECUNDARIO = "#e76f51"
_COLOR_OK = "#2a9d8f"
_COLOR_AVISO = "#e9c46a"
_COLOR_ALERTA = "#e63946"

_ANCHO_UTIL_CM = 18  # A4 (21 cm) menos los márgenes de 1,5 cm


def _limpiar(texto) -> str:
    """La tipografía estándar del PDF (Helvetica) no tiene flechas ni comparadores: se reemplazan por ASCII."""
    texto = str(texto)
    for original, reemplazo in (("→", "->"), ("≤", "<="), ("≥", ">="), ("−", "-")):
        texto = texto.replace(original, reemplazo)
    return texto


def _encabezado():
    hoy = date.today().strftime("%d/%m/%Y")
    return [
        Paragraph("BiblioRed - Sistema de Préstamos Interbibliotecarios", _TITULO),
        Paragraph(f"Informe generado el {hoy}", _NORMAL),
        Spacer(1, 0.5 * cm),
    ]


def _tabla(encabezados, filas, anchos=None):
    """Tabla con celdas que ajustan el texto. anchos: proporciones relativas de cada columna (opcional)."""
    datos = [[Paragraph(escape(_limpiar(h)), _CELDA_ENCABEZADO) for h in encabezados]]
    for fila in filas:
        datos.append([Paragraph(escape(_limpiar(c)), _CELDA) for c in fila])

    proporciones = anchos or [1] * len(encabezados)
    total = sum(proporciones)
    anchos_cm = [_ANCHO_UTIL_CM * cm * p / total for p in proporciones]

    tabla = Table(datos, colWidths=anchos_cm, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_COLOR_PRIMARIO)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tabla


def _kpis(indicadores, por_fila=3):
    """
    Tablero de indicadores clave. indicadores: lista de (etiqueta, valor, detalle|None).
    Cada indicador es una celda con la etiqueta chica, el valor grande y el detalle debajo.
    """
    celdas = []
    for etiqueta, valor, detalle in indicadores:
        html = (f'<font size="7" color="#667468">{escape(_limpiar(etiqueta)).upper()}</font><br/>'
                f'<font size="13"><b>{escape(_limpiar(valor))}</b></font>')
        if detalle:
            html += f'<br/><font size="7" color="#667468">{escape(_limpiar(detalle))}</font>'
        celdas.append(Paragraph(html, _KPI))

    filas = [celdas[i:i + por_fila] for i in range(0, len(celdas), por_fila)]
    for fila in filas:
        fila.extend([""] * (por_fila - len(fila)))  # completa la última fila para que la grilla quede pareja

    tabla = Table(filas, colWidths=[_ANCHO_UTIL_CM * cm / por_fila] * por_fila)
    tabla.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9f7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tabla


def _sin_datos(mensaje):
    return Paragraph(f"<i>{escape(_limpiar(mensaje))}</i>", _NORMAL)


def _truncar(texto, largo=42):
    return texto if len(texto) <= largo else texto[:largo - 1] + "…"


def _grafico_barh(etiquetas, valores, color=_COLOR_PRIMARIO, ancho_cm=15, alto_cm=None):
    """Gráfico de barras horizontales embebido como imagen (Matplotlib -> PNG -> ReportLab Image)."""
    if alto_cm is None:
        alto_cm = max(3.5, 0.6 * len(etiquetas) + 1.5)

    fig, ax = plt.subplots(figsize=(ancho_cm / 2.54, alto_cm / 2.54), dpi=150)
    posiciones = range(len(etiquetas))
    ax.barh(posiciones, valores, color=color)
    ax.set_yticks(list(posiciones))
    ax.set_yticklabels(etiquetas, fontsize=8)
    ax.invert_yaxis()  # el primero de la lista arriba
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlim(0, max(valores) * 1.15 if max(valores) else 1)
    for i, v in enumerate(valores):
        if v:
            ax.text(v, i, f" {v}", va="center", fontsize=8)
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    return Image(buffer, width=ancho_cm * cm, height=alto_cm * cm)


def _grafico_barh_agrupado(etiquetas, series, ancho_cm=15, alto_cm=None):
    """series: dict {nombre_serie: [valores por etiqueta]}, dos barras por etiqueta."""
    if alto_cm is None:
        alto_cm = max(3.5, 0.8 * len(etiquetas) + 1.5)

    nombres_series = list(series.keys())
    colores = [_COLOR_PRIMARIO, _COLOR_SECUNDARIO]
    alto_barra = 0.35
    posiciones = range(len(etiquetas))

    valor_maximo = max((v for valores in series.values() for v in valores), default=0)

    fig, ax = plt.subplots(figsize=(ancho_cm / 2.54, alto_cm / 2.54), dpi=150)
    for idx, nombre in enumerate(nombres_series):
        offset = (idx - (len(nombres_series) - 1) / 2) * alto_barra
        y = [p + offset for p in posiciones]
        barras = ax.barh(y, series[nombre], height=alto_barra, label=nombre, color=colores[idx % len(colores)])
        etiquetas_valor = [str(v) if v else "" for v in series[nombre]]
        ax.bar_label(barras, labels=etiquetas_valor, fontsize=7, padding=2)

    ax.set_yticks(list(posiciones))
    ax.set_yticklabels(etiquetas, fontsize=8)
    ax.invert_yaxis()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlim(0, valor_maximo * 1.2 if valor_maximo else 1)
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    fig.tight_layout()

    buffer = BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    buffer.seek(0)
    return Image(buffer, width=ancho_cm * cm, height=alto_cm * cm)


def _generar_documento(elementos_contenido) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm
    )
    doc.build(_encabezado() + elementos_contenido)
    buffer.seek(0)
    return buffer


def _fecha(d):
    return d.strftime("%d/%m/%Y")


def _titulo_seccion(texto, nota=None):
    elementos = [Paragraph(escape(_limpiar(texto)), _SUBTITULO)]
    if nota:
        elementos.append(Paragraph(escape(_limpiar(nota)), _NOTA))
    elementos.append(Spacer(1, 0.2 * cm))
    return elementos


def _subtitulo(texto):
    return [Spacer(1, 0.3 * cm), Paragraph(f"<b>{escape(_limpiar(texto))}</b>", _NORMAL), Spacer(1, 0.1 * cm)]


# --- Secciones reutilizables (indicadores + gráfico + detalle, una por reporte) ---

def _seccion_prestamos_activos_transito(rep):
    elementos = _titulo_seccion(
        "1. Préstamos activos y material en tránsito",
        f"Semáforo de vencimientos y pipeline logístico. Fecha de corte: {_fecha(rep['fecha_corte'])}."
    )
    elementos.append(_kpis([
        ("Préstamos activos", rep["total_activos"], f"{rep['interbibliotecarios']} inter-sede / {rep['locales']} locales"),
        ("En plazo", rep["en_plazo"], None),
        ("Por vencer (<= 3 días)", rep["por_vencer"], None),
        ("Vencidos", rep["vencidos"], f"{rep['pct_vencidos']}% de los activos"),
        ("Colección prestada", f"{rep['pct_coleccion_prestada']}%", f"{rep['total_activos']} de {rep['total_ejemplares']} ejemplares"),
        ("Ejemplares en logística", rep["ejemplares_en_curso"],
         f"{rep['remitos_en_curso']} remito(s), {rep['ejemplares_en_transito']} en tránsito"),
    ]))
    elementos.append(Spacer(1, 0.3 * cm))

    if rep["total_activos"]:
        elementos.append(_grafico_barh(
            ["En plazo", "Por vencer", "Vencidos"],
            [rep["en_plazo"], rep["por_vencer"], rep["vencidos"]],
            color=[_COLOR_OK, _COLOR_AVISO, _COLOR_ALERTA], alto_cm=4
        ))
        elementos += _subtitulo("Préstamos en curso (del más urgente al menos urgente)")
        filas = []
        for d in rep["detalle"]:
            p, dias = d["prestamo"], d["dias_restantes"]
            situacion = f"Vencido hace {-dias} d" if dias < 0 else "Vence hoy" if dias == 0 else f"Faltan {dias} d"
            filas.append([p.id_prestamo, f"{p.socio.nombre} {p.socio.apellido}", p.ejemplar.libro.titulo,
                          _fecha(p.fecha_vencimiento), situacion])
        elementos.append(_tabla(["Préstamo", "Socio", "Libro", "Vence", "Situación"], filas, [1.2, 2.2, 3.5, 1.4, 1.8]))
    else:
        elementos.append(_sin_datos("Sin préstamos activos."))

    elementos += _subtitulo("Pipeline logístico (remitos sin entregar)")
    elementos.append(_tabla(
        ["Etapa", "Remitos", "Ejemplares"],
        [[e["estado"], e["remitos"], e["ejemplares"]] for e in rep["etapas_logisticas"]],
        [3, 1, 1]
    ))
    if rep["envios_en_transito"]:
        elementos += _subtitulo("Material en tránsito ahora")
        filas = [
            [e["remito"].id_remito, f"{e['remito'].sede_origen.nombre} -> {e['remito'].sede_destino.nombre}",
             e["remito"].cantidad_ejemplares,
             f"hace {e['dias_en_transito']} d" if e["dias_en_transito"] is not None else "-"]
            for e in rep["envios_en_transito"]
        ]
        elementos.append(_tabla(["Remito", "Ruta", "Ejemplares", "Despachado"], filas, [1.5, 4, 1, 1.5]))
    return elementos


def _seccion_morosidad(rep):
    elementos = _titulo_seccion(
        "2. Morosidad y sanciones acumuladas",
        f"Sanción: 2 días de inhabilitación por cada día de retraso. Fecha de corte: {_fecha(rep['fecha_corte'])}."
    )
    pg = rep["por_gravedad"]
    elementos.append(_kpis([
        ("Préstamos vencidos", rep["total_vencidos"],
         f"{pg['Grave']} grave(s), {pg['Moderada']} moderada(s), {pg['Leve']} leve(s)"),
        ("Mora promedio", f"{rep['mora_promedio']} días", f"máxima: {rep['mora_maxima']} días"),
        ("Sanción proyectada", f"{rep['sancion_proyectada_total']} días", "si todos devolvieran hoy"),
        ("Incumplimiento histórico", f"{rep['tasa_incumplimiento']}%",
         f"sobre {rep['total_resueltos']} préstamos resueltos ({rep['devueltos_tarde']} devueltos tarde)"),
        ("Socios sancionados", len(rep["sancionados"]), f"{rep['pct_socios_sancionados']}% del padrón"),
    ]))
    elementos.append(Spacer(1, 0.3 * cm))

    if rep["detalle"]:
        color_gravedad = {"Leve": _COLOR_AVISO, "Moderada": _COLOR_SECUNDARIO, "Grave": _COLOR_ALERTA}
        elementos.append(_grafico_barh(
            [d["prestamo"].id_prestamo for d in rep["detalle"]],
            [d["dias_retraso"] for d in rep["detalle"]],
            color=[color_gravedad[d["gravedad"]] for d in rep["detalle"]]
        ))
        elementos += _subtitulo("Préstamos vencidos y sanción proyectada")
        filas = [
            [d["prestamo"].id_prestamo, f"{d['prestamo'].socio.nombre} {d['prestamo'].socio.apellido}",
             d["prestamo"].ejemplar.libro.titulo, f"{d['dias_retraso']} d", d["gravedad"],
             f"{d['sancion_dias']} d (hasta {_fecha(d['sancion_hasta'])})"]
            for d in rep["detalle"]
        ]
        elementos.append(_tabla(["Préstamo", "Socio", "Libro", "Mora", "Gravedad", "Sanción si devuelve hoy"],
                                filas, [1.2, 2, 3, 0.8, 1.1, 2.4]))
    else:
        elementos.append(_sin_datos("No hay préstamos vencidos."))

    if rep["por_socio"]:
        elementos += _subtitulo("Mora acumulada por socio")
        filas = [[f"{f['socio'].nombre} {f['socio'].apellido}", f["prestamos_vencidos"],
                  f"{f['mora_acumulada']} d", f"{f['mora_maxima']} d"] for f in rep["por_socio"]]
        elementos.append(_tabla(["Socio", "Préstamos vencidos", "Mora acumulada", "Mora máxima"], filas, [3, 1.5, 1.5, 1.5]))

    elementos += _subtitulo("Sanciones vigentes hoy")
    if rep["sancionados"]:
        filas = [[f"{s['socio'].nombre} {s['socio'].apellido}", _fecha(s["hasta"]), f"{s['dias_restantes']} d"]
                 for s in rep["sancionados"]]
        elementos.append(_tabla(["Socio", "Inhabilitado hasta", "Días restantes"], filas, [3, 1.5, 1.5]))
    else:
        elementos.append(_sin_datos("No hay socios sancionados."))
    return elementos


def _seccion_demanda_intersedes(rep):
    elementos = _titulo_seccion(
        "3. Demanda de libros en préstamos inter-sedes",
        "Títulos más pedidos entre sedes, contrastados con los ejemplares que tiene la red."
    )
    elementos.append(_kpis([
        ("Préstamos inter-sede", rep["total_intersede"], f"{rep['pct_intersede']}% de {rep['total_prestamos']} préstamos"),
        ("Títulos distintos pedidos", rep["titulos_distintos"], None),
        ("Concentración top 3", f"{rep['concentracion_top3']}%", "de la demanda inter-sede"),
        ("Títulos con demanda alta", rep["titulos_demanda_alta"], ">= 1 solicitud por ejemplar"),
    ], por_fila=4))
    elementos.append(Spacer(1, 0.3 * cm))

    if rep["ranking"]:
        elementos.append(_grafico_barh(
            [_truncar(f["libro"].titulo) for f in rep["ranking"]],
            [f["solicitudes"] for f in rep["ranking"]],
        ))
        elementos += _subtitulo("Ranking detallado")
        filas = [
            [f["posicion"], f["libro"].titulo, f"{f['solicitudes']} ({f['pct_del_total']}%)",
             f"{f['ejemplares_disponibles']}/{f['ejemplares_red']}",
             f["solicitudes_por_ejemplar"] if f["solicitudes_por_ejemplar"] is not None else "-",
             f["reservas_activas"], f["ruta_principal"], f["nivel_demanda"]]
            for f in rep["ranking"]
        ]
        elementos.append(_tabla(
            ["#", "Título", "Solicitudes", "Ej. disp./total", "Solic. por ej.", "Reservas", "Ruta más frecuente", "Demanda"],
            filas, [0.4, 3, 1.3, 1.1, 1, 0.9, 2.6, 1]
        ))
    else:
        elementos.append(_sin_datos("No hay solicitudes interbibliotecarias registradas."))
    return elementos


def _seccion_disponibilidad(rep):
    elementos = _titulo_seccion(
        "4. Disponibilidad de catálogo por sede",
        "Sedes ordenadas de la más comprometida a la más holgada."
    )
    elementos.append(_kpis([
        ("Disponibilidad de la red", f"{rep['tasa_red']}%", f"{rep['disponibles_red']} de {rep['total_ejemplares']} ejemplares"),
        ("Sedes en situación crítica", rep["sedes_criticas"], "< 30% disponible"),
        ("Títulos agotados en la red", len(rep["titulos_agotados_red"]), "ninguna copia libre"),
        ("Ejemplares deteriorados", rep["ejemplares_deteriorados"], "deteriorados o dañados"),
    ], por_fila=4))
    elementos.append(Spacer(1, 0.3 * cm))

    if rep["sedes"]:
        elementos.append(_grafico_barh_agrupado(
            [s["sede"].nombre for s in rep["sedes"]],
            {
                "Disponibles": [s["disponibles"] for s in rep["sedes"]],
                "No disponibles": [s["no_disponibles"] for s in rep["sedes"]],
            }
        ))
        elementos += _subtitulo("Detalle por sede")
        filas = [
            [s["sede"].nombre, s["total"], f"{s['tasa_disponibilidad']}%",
             s["por_estado"]["Prestado"], s["por_estado"]["En preparación"], s["por_estado"]["En tránsito"],
             s["por_estado"]["Reservado"], f"{s['titulos_agotados']} de {s['titulos']}",
             f"{s['cobertura_catalogo']}%", s["ejemplares_deteriorados"], s["situacion"]]
            for s in rep["sedes"]
        ]
        elementos.append(_tabla(
            ["Sede", "Total", "Disp.", "Prest.", "En prep.", "En trán.", "Reserv.", "Títulos agotados", "Cobertura", "Deter.", "Situación"],
            filas, [2.6, 0.7, 0.8, 0.8, 0.8, 0.8, 0.8, 1.2, 1, 0.7, 1.1]
        ))
    else:
        elementos.append(_sin_datos("No hay sedes registradas."))

    if rep["titulos_agotados_red"]:
        elementos += _subtitulo("Títulos sin ninguna copia disponible en la red")
        elementos.append(Paragraph(escape(_limpiar(", ".join(l.titulo for l in rep["titulos_agotados_red"]))), _NORMAL))
    return elementos


def _seccion_efectividad_logistica(rep):
    elementos = _titulo_seccion(
        "5. Efectividad logística e incidencias",
        "Éxito = remito entregado dentro del SLA de tránsito (3 días). Incidencia = entrega tardía o remito sin avanzar más de 3 días."
    )
    elementos.append(_kpis([
        ("Tasa de éxito", f"{rep['tasa_exito']}%", f"{rep['entregados_a_tiempo']} entregas a tiempo"),
        ("Remitos entregados", f"{rep['recibidos']} / {rep['total_remitos']}",
         f"{rep['tasa_entrega']}% completado, {rep['en_curso']} en curso"),
        ("Incidencias", rep["total_incidencias"],
         f"{rep['entregas_tardias']} entregas tardías, {rep['estancados']} estancados"),
        ("Ejemplares por remito", rep["ejemplares_por_remito"],
         f"{rep['ejemplares_enviados']} ejemplares en {rep['total_remitos']} remitos"),
        ("Envíos evitados", rep["envios_evitados"], f"{rep['pct_envios_evitados']}% menos viajes por el agrupamiento"),
    ]))
    elementos.append(Spacer(1, 0.3 * cm))

    if rep["total_remitos"]:
        estados = rep["remitos_por_estado"]
        elementos.append(_grafico_barh(
            list(estados.keys()), list(estados.values()),
            color=[_COLOR_AVISO, _COLOR_AVISO, _COLOR_PRIMARIO, _COLOR_OK], alto_cm=4.5
        ))

    elementos += _subtitulo("Tiempo promedio por etapa")
    filas = [[t["etapa"], t["remitos"], formatear_duracion(t["promedio_s"]), formatear_duracion(t["maximo_s"])]
             for t in rep["tiempos_por_etapa"]]
    elementos.append(_tabla(["Etapa", "Remitos medidos", "Promedio", "Máximo"], filas, [4, 1.3, 1.3, 1.3]))

    elementos += _subtitulo("Incidencias detectadas")
    if rep["incidencias"]:
        filas = [[i["remito"].id_remito,
                  f"{i['remito'].sede_origen.nombre} -> {i['remito'].sede_destino.nombre}",
                  i["tipo"], i["detalle"]] for i in rep["incidencias"]]
        elementos.append(_tabla(["Remito", "Ruta", "Tipo", "Detalle"], filas, [1.4, 3, 1.2, 3.5]))
    else:
        elementos.append(_sin_datos("Sin incidencias: todos los envíos van en tiempo y forma."))
    return elementos


def _seccion_movimiento(rep):
    elementos = _titulo_seccion(
        "6. Movimiento de ejemplares entre sedes",
        "Envíos por ruta, tiempo promedio de tránsito y balance de ejemplares enviados vs. recibidos."
    )
    ruta = rep["ruta_principal"]
    emisora, receptora = rep["sede_mas_emisora"], rep["sede_mas_receptora"]
    elementos.append(_kpis([
        ("Ejemplares movidos", rep["total_ejemplares"], f"{rep['total_remitos']} remito(s)"),
        ("Rutas activas", rep["rutas_activas"], None),
        ("Ruta principal", f"{ruta['origen'].nombre} -> {ruta['destino'].nombre}" if ruta else "-",
         f"{ruta['ejemplares']} ejemplares" if ruta else None),
        ("Tránsito promedio", formatear_duracion(rep["transito_promedio_s"]), "Despachado -> Recibido"),
        ("Sede más emisora", emisora["sede"].nombre if emisora else "-", f"saldo {emisora['saldo']}" if emisora else None),
        ("Sede más receptora", receptora["sede"].nombre if receptora else "-",
         f"saldo +{receptora['saldo']}" if receptora else None),
    ]))
    elementos.append(Spacer(1, 0.3 * cm))

    if rep["balance_sedes"]:
        elementos.append(_grafico_barh_agrupado(
            [b["sede"].nombre for b in rep["balance_sedes"]],
            {
                "Enviados": [b["enviados"] for b in rep["balance_sedes"]],
                "Recibidos": [b["recibidos"] for b in rep["balance_sedes"]],
            }
        ))
        elementos += _subtitulo("Envíos por ruta")
        filas = [[f"{r['origen'].nombre} -> {r['destino'].nombre}", r["remitos"], r["ejemplares"],
                  r["ejemplares_por_remito"], r["entregados"], formatear_duracion(r["transito_promedio_s"])]
                 for r in rep["rutas"]]
        elementos.append(_tabla(["Ruta", "Remitos", "Ejemplares", "Ej. por remito", "Entregados", "Tránsito prom."],
                                filas, [4, 1, 1.2, 1.2, 1.2, 1.4]))

        elementos += _subtitulo("Balance por sede (recibidos - enviados)")
        filas = [[b["sede"].nombre, b["enviados"], b["recibidos"], f"{b['saldo']:+d}", b["por_salir"], b["en_camino"], b["perfil"]]
                 for b in rep["balance_sedes"]]
        elementos.append(_tabla(["Sede", "Enviados", "Recibidos", "Saldo", "Por salir", "En camino", "Perfil"],
                                filas, [3, 1, 1, 0.8, 1, 1, 1.6]))
    else:
        elementos.append(_sin_datos("Todavía no hay remitos."))
    return elementos


# --- Funciones públicas: una por reporte + una combinada ---

def pdf_prestamos_activos_transito(rep) -> BytesIO:
    return _generar_documento(_seccion_prestamos_activos_transito(rep))


def pdf_morosidad_y_sanciones(rep) -> BytesIO:
    return _generar_documento(_seccion_morosidad(rep))


def pdf_demanda_intersedes(rep) -> BytesIO:
    return _generar_documento(_seccion_demanda_intersedes(rep))


def pdf_disponibilidad_por_sede(rep) -> BytesIO:
    return _generar_documento(_seccion_disponibilidad(rep))


def pdf_efectividad_logistica(rep) -> BytesIO:
    return _generar_documento(_seccion_efectividad_logistica(rep))


def pdf_movimiento_entre_sedes(rep) -> BytesIO:
    return _generar_documento(_seccion_movimiento(rep))


def pdf_todos_los_reportes(reps) -> BytesIO:
    """reps: el diccionario que devuelve Reportes.todos()."""
    elementos = []
    for seccion, clave in (
        (_seccion_prestamos_activos_transito, "activos"),
        (_seccion_morosidad, "morosidad"),
        (_seccion_demanda_intersedes, "demanda"),
        (_seccion_disponibilidad, "disponibilidad"),
        (_seccion_efectividad_logistica, "logistica"),
        (_seccion_movimiento, "movimiento"),
    ):
        elementos += seccion(reps[clave])
        elementos.append(Spacer(1, 0.6 * cm))
    return _generar_documento(elementos)
