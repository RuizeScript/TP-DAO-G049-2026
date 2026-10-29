from io import BytesIO
from datetime import date

import matplotlib
matplotlib.use("Agg")  # backend sin interfaz gráfica, necesario para generar imágenes desde un server Flask
import matplotlib.pyplot as plt

from matplotlib.ticker import MaxNLocator

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

_ESTILOS = getSampleStyleSheet()
_TITULO = ParagraphStyle("TituloBiblioRed", parent=_ESTILOS["Heading1"], textColor=colors.HexColor("#1d3557"))
_SUBTITULO = ParagraphStyle("Subtitulo", parent=_ESTILOS["Heading2"], textColor=colors.HexColor("#2a5784"), spaceBefore=12)
_NORMAL = _ESTILOS["Normal"]

_COLOR_PRIMARIO = "#1d3557"
_COLOR_SECUNDARIO = "#e76f51"


def _encabezado():
    hoy = date.today().strftime("%d/%m/%Y")
    return [
        Paragraph("BiblioRed - Sistema de Préstamos Interbibliotecarios", _TITULO),
        Paragraph(f"Informe generado el {hoy}", _NORMAL),
        Spacer(1, 0.5 * cm),
    ]


def _tabla(encabezados, filas):
    datos = [encabezados] + filas
    tabla = Table(datos, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_COLOR_PRIMARIO)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tabla


def _sin_datos(mensaje):
    return Paragraph(f"<i>{mensaje}</i>", _NORMAL)


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


# --- Secciones reutilizables (tabla + gráfico, una por reporte) ---

def _seccion_prestamos_activos_transito(rep1):
    elementos = [Paragraph("Préstamos activos y material en tránsito", _SUBTITULO)]

    if rep1["total_prestamos_activos"] or rep1["total_en_transito"]:
        elementos.append(_grafico_barh(
            ["Préstamos activos", "Ejemplares en tránsito"],
            [rep1["total_prestamos_activos"], rep1["total_en_transito"]],
            alto_cm=3.5
        ))
        elementos.append(Spacer(1, 0.3 * cm))

    if rep1["prestamos_activos"]:
        filas = [
            [p.id_prestamo, f"{p.socio.nombre} {p.socio.apellido}", p.ejemplar.libro.titulo, p.fecha_vencimiento.strftime("%d/%m/%Y")]
            for p in rep1["prestamos_activos"]
        ]
        elementos.append(_tabla(["ID", "Socio", "Ejemplar", "Vence"], filas))
    else:
        elementos.append(_sin_datos("Sin préstamos activos."))

    elementos.append(Spacer(1, 0.3 * cm))
    elementos.append(Paragraph(f"Material en tránsito: {rep1['total_en_transito']}", _NORMAL))
    if rep1["ejemplares_en_transito"]:
        filas = [[e.id_ejemplar, e.libro.titulo] for e in rep1["ejemplares_en_transito"]]
        elementos.append(_tabla(["Ejemplar", "Libro"], filas))
    return elementos


def _seccion_prestamos_vencidos(rep2):
    elementos = [Paragraph("Préstamos vencidos y días de mora", _SUBTITULO)]
    if rep2["detalle"]:
        detalle_ordenado = sorted(rep2["detalle"], key=lambda d: d["dias_retraso"], reverse=True)
        elementos.append(_grafico_barh(
            [d["prestamo"].id_prestamo for d in detalle_ordenado],
            [d["dias_retraso"] for d in detalle_ordenado],
            color=_COLOR_SECUNDARIO
        ))
        elementos.append(Spacer(1, 0.3 * cm))

        filas = [
            [
                d["prestamo"].id_prestamo,
                f"{d['prestamo'].socio.nombre} {d['prestamo'].socio.apellido}",
                d["prestamo"].fecha_vencimiento.strftime("%d/%m/%Y"),
                str(d["dias_retraso"]),
            ]
            for d in rep2["detalle"]
        ]
        elementos.append(_tabla(["Préstamo", "Socio", "Vencimiento", "Días de mora"], filas))
    else:
        elementos.append(_sin_datos("No hay préstamos vencidos."))
    return elementos


def _seccion_disponibilidad_por_sede(rep3):
    elementos = [Paragraph("Disponibilidad de catálogo por sede", _SUBTITULO)]
    if rep3:
        nombres = list(rep3.keys())
        elementos.append(_grafico_barh_agrupado(
            nombres,
            {
                "Disponibles": [rep3[n]["disponibles"] for n in nombres],
                "No disponibles": [rep3[n]["no_disponibles"] for n in nombres],
            }
        ))
        elementos.append(Spacer(1, 0.3 * cm))

        filas = [
            [nombre, str(d["total_ejemplares"]), str(d["disponibles"]), str(d["no_disponibles"]), "Activa" if d["activa"] else "Inactiva"]
            for nombre, d in rep3.items()
        ]
        elementos.append(_tabla(["Sede", "Total", "Disponibles", "No disp.", "Estado"], filas))
    else:
        elementos.append(_sin_datos("No hay sedes registradas."))
    return elementos


def _seccion_libros_mas_solicitados(rep4):
    elementos = [Paragraph("Libros más solicitados para préstamos inter-sedes", _SUBTITULO)]
    if rep4:
        elementos.append(_grafico_barh(
            [_truncar(item["libro"]) for item in rep4],
            [item["solicitudes_intersede"] for item in rep4],
        ))
        elementos.append(Spacer(1, 0.3 * cm))

        filas = [[str(i + 1), item["libro"], str(item["solicitudes_intersede"])] for i, item in enumerate(rep4)]
        elementos.append(_tabla(["#", "Libro", "Solicitudes inter-sede"], filas))
    else:
        elementos.append(_sin_datos("No hay solicitudes interbibliotecarias registradas."))
    return elementos


# --- Funciones públicas: una por reporte + una combinada ---

def pdf_prestamos_activos_transito(rep1) -> BytesIO:
    return _generar_documento(_seccion_prestamos_activos_transito(rep1))


def pdf_prestamos_vencidos(rep2) -> BytesIO:
    return _generar_documento(_seccion_prestamos_vencidos(rep2))


def pdf_disponibilidad_por_sede(rep3) -> BytesIO:
    return _generar_documento(_seccion_disponibilidad_por_sede(rep3))


def pdf_libros_mas_solicitados(rep4) -> BytesIO:
    return _generar_documento(_seccion_libros_mas_solicitados(rep4))


def pdf_todos_los_reportes(rep1, rep2, rep3, rep4) -> BytesIO:
    elementos = []
    elementos += _seccion_prestamos_activos_transito(rep1)
    elementos.append(Spacer(1, 0.6 * cm))
    elementos += _seccion_prestamos_vencidos(rep2)
    elementos.append(Spacer(1, 0.6 * cm))
    elementos += _seccion_disponibilidad_por_sede(rep3)
    elementos.append(Spacer(1, 0.6 * cm))
    elementos += _seccion_libros_mas_solicitados(rep4)
    return _generar_documento(elementos)
