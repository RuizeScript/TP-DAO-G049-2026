from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from models.gestor import GestorBiblioteca
from models.datos_demo import cargar_datos_iniciales
from models.entidades import Sede, Socio, Libro, Ejemplar
from models.enum import Estado
from models.excepciones import BibliotecaExcepcion, TransicionInvalidaError
from models.remito import Recibido, Cancelado
from models.reportes import Reportes, formatear_duracion
import reportes_pdf

app = Flask(__name__)
app.secret_key = "dao_biblioteca_secret_key_2026"
app.jinja_env.filters["duracion"] = formatear_duracion   # {{ segundos|duracion }} -> "2 d 7 h"

# Instanciamos el Gestor (Singleton) y cargamos datos demostrativos
gestor = GestorBiblioteca()
cargar_datos_iniciales(gestor)
generador_reportes = Reportes(gestor)


# -------------------------------------------------------------------------
# 1. Dashboard Principal
# -------------------------------------------------------------------------
@app.route("/")
def index():
    ultimos_prestamos = sorted(gestor.prestamos, key=lambda p: p.fecha_inicio, reverse=True)[:5]
    # "En proceso" = todavía vigentes: ni recibidos ni cancelados (los dos son estados finales)
    remitos_en_proceso = [r for r in gestor.remitos if r.estado_actual.__class__.__name__ not in ("Recibido", "Cancelado")]
    remitos_entregados = sum(1 for r in gestor.remitos if r.estado_actual.__class__.__name__ == "Recibido")
    remitos_cancelados = sum(1 for r in gestor.remitos if r.esta_cancelado)

    # Un préstamo cancelado (por un remito cancelado) no está activo
    total_prestamos_activos = len([p for p in gestor.prestamos if p.esta_abierto])

    return render_template(
        "index.html",
        total_sedes=len(gestor.sedes),
        total_socios=len(gestor.socios),
        total_libros=len(gestor.libros),
        total_ejemplares=len(gestor.ejemplares),
        total_prestamos_activos=total_prestamos_activos,
        total_remitos=len(gestor.remitos),
        ultimos_prestamos=ultimos_prestamos,
        remitos_en_proceso=remitos_en_proceso,
        remitos_entregados=remitos_entregados,
        remitos_cancelados=remitos_cancelados
    )


# -------------------------------------------------------------------------
# 2. Sedes
# -------------------------------------------------------------------------
@app.route("/sedes", methods=["GET", "POST"])
def sedes():
    if request.method == "POST":
        id_sede = request.form.get("id_sede", "").strip() or None
        nombre = request.form.get("nombre", "").strip()
        direccion = request.form.get("direccion", "").strip()
        contacto = request.form.get("contacto", "").strip()
        horarios = request.form.get("horarios", "").strip()
        comentarios = request.form.get("comentarios", "").strip()
        activa = True if request.form.get("activa") else False

        try:
            nueva_sede = Sede(
                id_sede=id_sede,
                nombre=nombre,
                direccion=direccion,
                contacto=contacto,
                horarios=horarios,
                activa=activa,
                comentarios=comentarios
            )
            sede_creada = gestor.agregar_sede(nueva_sede)
            flash(f"Sede '{nombre}' ({sede_creada.id_sede}) registrada exitosamente.", "success")
        except BibliotecaExcepcion as e:
            flash(str(e), "danger")
        return redirect(url_for("sedes"))

    lista = list(gestor.sedes.values())
    # Para cada sede, qué registros la usan: si hay alguno no se puede eliminar (el modal lo explica)
    en_uso = {s.id_sede: gestor.referencias_de_sede(s.id_sede) for s in lista}
    return render_template("sedes.html", sedes=lista, en_uso=en_uso)


@app.route("/sedes/<id_sede>/editar", methods=["POST"])
def editar_sede(id_sede):
    try:
        sede = gestor.editar_sede(
            id_sede,
            nombre=request.form.get("nombre", ""),
            direccion=request.form.get("direccion", ""),
            contacto=request.form.get("contacto", ""),
            horarios=request.form.get("horarios", ""),
            comentarios=request.form.get("comentarios"),
        )
        flash(f"Sede '{sede.nombre}' ({sede.id_sede}) actualizada.", "success")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("sedes"))


@app.route("/sedes/<id_sede>/eliminar", methods=["POST"])
def eliminar_sede(id_sede):
    try:
        sede = gestor.eliminar_sede(id_sede)
        flash(f"Sede '{sede.nombre}' ({sede.id_sede}) eliminada definitivamente.", "info")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("sedes"))


@app.route("/sedes/<id_sede>/toggle", methods=["POST"])
def toggle_sede(id_sede):
    try:
        sede = gestor.obtener_sede(id_sede)
        nuevo_estado = not sede.activa
        # Al inhabilitar el formulario envía el motivo (obligatorio); al activar no hace falta
        gestor.cambiar_estado_sede(id_sede, nuevo_estado, request.form.get("comentarios", ""))
        if nuevo_estado:
            flash(f"Sede '{sede.nombre}' ha sido activada.", "info")
        else:
            flash(f"Sede '{sede.nombre}' ha sido dada de baja. Motivo: {sede.comentarios}", "info")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("sedes"))


# -------------------------------------------------------------------------
# 3. Socios
# -------------------------------------------------------------------------
@app.route("/socios", methods=["GET", "POST"])
def socios():
    if request.method == "POST":
        id_socio = request.form.get("id_socio", "").strip() or None
        nombre = request.form.get("nombre", "").strip()
        apellido = request.form.get("apellido", "").strip()
        dni = request.form.get("dni", "").strip()
        email = request.form.get("email", "").strip()

        try:
            nuevo_socio = Socio(id_socio=id_socio, nombre=nombre, apellido=apellido, dni=dni, email=email)
            socio_creado = gestor.agregar_socio(nuevo_socio)
            flash(f"Socio {nombre} {apellido} ({socio_creado.id_socio}) registrado exitosamente.", "success")
        except BibliotecaExcepcion as e:
            flash(str(e), "danger")
        return redirect(url_for("socios"))

    return render_template("socios.html", socios=list(gestor.socios.values()), hoy=date.today())


# -------------------------------------------------------------------------
# 4. Catálogo, Ejemplares y Disponibilidad
# -------------------------------------------------------------------------
@app.route("/catalogo", methods=["GET"])
def catalogo():
    isbn_filtro = request.args.get("isbn", "").strip()
    id_sede_filtro = request.args.get("id_sede", "").strip()

    consulta_realizada = False
    resultados_disponibilidad = []

    if isbn_filtro:
        consulta_realizada = True
        resultados_disponibilidad = gestor.consultar_disponibilidad(
            isbn=isbn_filtro,
            id_sede=id_sede_filtro if id_sede_filtro else None
        )

    return render_template(
        "catalogo.html",
        libros=list(gestor.libros.values()),
        ejemplares=list(gestor.ejemplares.values()),
        sedes=list(gestor.sedes.values()),
        consulta_realizada=consulta_realizada,
        resultados_disponibilidad=resultados_disponibilidad,
        isbn_seleccionado=isbn_filtro,
        sede_seleccionada=id_sede_filtro
    )


@app.route("/catalogo/libro", methods=["POST"])
def nuevo_libro():
    isbn = request.form.get("isbn", "").strip() or None
    titulo = request.form.get("titulo", "").strip()
    autor = request.form.get("autor", "").strip()
    categoria = request.form.get("categoria", "").strip()
    editorial = request.form.get("editorial", "").strip()

    try:
        libro = Libro(isbn=isbn, titulo=titulo, autor=autor, categoria=categoria, editorial=editorial)
        libro_creado = gestor.agregar_libro(libro)
        flash(f"Libro '{titulo}' (ISBN: {libro_creado.isbn}) agregado al catálogo.", "success")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("catalogo"))


@app.route("/catalogo/ejemplar", methods=["POST"])
def nuevo_ejemplar():
    id_ejemplar = request.form.get("id_ejemplar", "").strip() or None
    isbn = request.form.get("isbn", "").strip()
    id_sede = request.form.get("id_sede", "").strip()

    try:
        libro = gestor.libros.get(isbn)
        if not libro:
            raise BibliotecaExcepcion("Libro no encontrado.")
        sede = gestor.obtener_sede(id_sede)
        ejemplar = Ejemplar(id_ejemplar=id_ejemplar, libro=libro, sede=sede)
        ejemplar_creado = gestor.agregar_ejemplar(ejemplar)
        flash(f"Ejemplar '{ejemplar_creado.id_ejemplar}' ({libro.titulo}) asignado a '{sede.nombre}'.", "success")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("catalogo"))


# -------------------------------------------------------------------------
# 5. Préstamos y Reservas
# -------------------------------------------------------------------------
@app.route("/prestamos", methods=["GET", "POST"])
def prestamos():
    if request.method == "POST":
        id_prestamo = request.form.get("id_prestamo", "").strip() or None
        id_socio = request.form.get("id_socio", "").strip()
        id_ejemplar = request.form.get("id_ejemplar", "").strip()
        id_sede_destino = request.form.get("id_sede_destino", "").strip()
        dias_prestamo = int(request.form.get("dias_prestamo", 14))
        # La sede de origen no se elige: es la sede donde está el ejemplar
        ejemplar = gestor.ejemplares.get(id_ejemplar)
        id_sede_origen = ejemplar.sede.id_sede if ejemplar else ""

        try:
            p = gestor.crear_prestamo(
                id_prestamo=id_prestamo,
                id_socio=id_socio,
                id_ejemplar=id_ejemplar,
                id_sede_origen=id_sede_origen,
                id_sede_destino=id_sede_destino if id_sede_destino else None,
                dias_prestamo=dias_prestamo
            )
            msg = f"Préstamo '{p.id_prestamo}' registrado con éxito."
            if p.es_interbibliotecario:
                remito = gestor.remito_en_curso_de(p.ejemplar.id_ejemplar)
                msg += (f" El ejemplar viaja en el remito {remito.id_remito} "
                        f"({remito.sede_origen.nombre} → {remito.sede_destino.nombre}), "
                        f"que ahora lleva {remito.cantidad_ejemplares} ejemplar(es).")
            flash(msg, "success")
        except BibliotecaExcepcion as e:
            flash(f"Error al registrar préstamo: {e}", "danger")
        return redirect(url_for("prestamos"))

    # El select solo ofrece lo que se puede prestar (disponible y en una sede activa)
    ejemplares_prestables = gestor.ejemplares_prestables()

    # Si se llega desde el Catálogo ("Registrar préstamo"), el ejemplar elegido viene en la URL y queda ya seleccionado
    id_preseleccionado = request.args.get("ejemplar", "").strip()
    if id_preseleccionado:
        elegido = next((e for e in ejemplares_prestables if e.id_ejemplar == id_preseleccionado), None)
        if elegido:
            flash(f"Ejemplar {elegido.id_ejemplar} ({elegido.libro.titulo}, {elegido.sede.nombre}) cargado desde el Catálogo. "
                  "Completá el socio y la sede de destino.", "info")
        else:
            id_preseleccionado = ""
            flash(f"El ejemplar '{request.args.get('ejemplar').strip()}' no se puede prestar ahora: no existe, "
                  "no está disponible o su sede está dada de baja.", "warning")

    return render_template(
        "prestamos.html",
        prestamos=gestor.prestamos_recientes(),
        reservas=gestor.reservas,
        socios=list(gestor.socios.values()),
        ejemplares=ejemplares_prestables,
        id_ejemplar_preseleccionado=id_preseleccionado,
        sedes=list(gestor.sedes.values()),
        libros=list(gestor.libros.values()),
        estados_fisicos=list(Estado),
        hoy=date.today()
    )


@app.route("/prestamos/<id_prestamo>/devolver", methods=["POST"])
def devolucion(id_prestamo):
    fecha_devolucion_str = request.form.get("fecha_devolucion")
    estado_fisico_str = request.form.get("estado_fisico")

    try:
        fecha_devolucion = date.fromisoformat(fecha_devolucion_str)
        estado_fisico = Estado[estado_fisico_str]
        gestor.registrar_devolucion(id_prestamo, fecha_devolucion, estado_fisico)
        flash(f"Devolución del préstamo '{id_prestamo}' registrada con éxito.", "success")
    except (BibliotecaExcepcion, ValueError, KeyError) as e:
        flash(f"Error al registrar devolución: {e}", "danger")
    return redirect(url_for("prestamos"))


@app.route("/reservas", methods=["POST"])
def crear_reserva():
    id_reserva = request.form.get("id_reserva", "").strip() or None
    id_socio = request.form.get("id_socio", "").strip()
    isbn = request.form.get("isbn", "").strip()
    id_sede = request.form.get("id_sede", "").strip()

    try:
        reserva = gestor.crear_reserva(id_socio=id_socio, isbn=isbn, id_sede=id_sede, id_reserva=id_reserva)
        flash(f"Reserva '{reserva.id_reserva}' registrada exitosamente para {reserva.socio.nombre} {reserva.socio.apellido}.", "success")
    except BibliotecaExcepcion as e:
        flash(f"Error al registrar reserva: {e}", "danger")
    return redirect(url_for("prestamos"))


@app.route("/reservas/<id_reserva>/cancelar", methods=["POST"])
def cancelar_reserva(id_reserva):
    try:
        gestor.cancelar_reserva(id_reserva)
        flash(f"Reserva '{id_reserva}' cancelada.", "info")
    except BibliotecaExcepcion:
        flash("Reserva no encontrada.", "danger")
    return redirect(url_for("prestamos"))


# -------------------------------------------------------------------------
# 6. Remitos y Logística (Patrón State)
# -------------------------------------------------------------------------
@app.route("/remitos")
def remitos():
    # Qué préstamos se cancelarían con cada remito: la ventana de confirmación de "Cancelar" lo informa antes de decidir
    prestamos_afectados = {
        r.id_remito: gestor.prestamos_de_remito(r)
        for r in gestor.remitos if not isinstance(r.estado_actual, (Recibido, Cancelado))
    }
    return render_template("remitos.html", remitos=gestor.remitos, prestamos_afectados=prestamos_afectados)


@app.route("/remitos/<id_remito>/empaquetar", methods=["POST"])
def empaquetar(id_remito):
    try:
        gestor.empaquetar_remito(id_remito)
        n = gestor.obtener_remito(id_remito).cantidad_ejemplares
        flash(f"Remito '{id_remito}' empaquetado. {n} ejemplar(es) en preparación; ya no admite más ejemplares.", "success")
    except TransicionInvalidaError as e:
        flash(f"Error de transición State: {e}", "danger")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("remitos"))


@app.route("/remitos/<id_remito>/despachar", methods=["POST"])
def despachar(id_remito):
    try:
        gestor.despachar_remito(id_remito)
        n = gestor.obtener_remito(id_remito).cantidad_ejemplares
        flash(f"Remito '{id_remito}' despachado. {n} ejemplar(es) en tránsito.", "info")
    except TransicionInvalidaError as e:
        flash(f"Error de transición State: {e}", "danger")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("remitos"))


@app.route("/remitos/<id_remito>/recibir", methods=["POST"])
def recibir(id_remito):
    try:
        gestor.recibir_remito(id_remito)
        n = gestor.obtener_remito(id_remito).cantidad_ejemplares
        flash(f"Remito '{id_remito}' recibido en sede destino. {n} ejemplar(es) listo(s) para entregar a los socios.", "success")
    except TransicionInvalidaError as e:
        flash(f"Error de transición State: {e}", "danger")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("remitos"))


@app.route("/remitos/<id_remito>/cancelar", methods=["POST"])
def cancelar_remito(id_remito):
    # La pantalla pide confirmación antes de enviar este formulario: cancelar es definitivo (estado final)
    try:
        resumen = gestor.cancelar_remito(id_remito, request.form.get("motivo", ""))
        remito = gestor.obtener_remito(id_remito)
        flash(
            f"Remito '{id_remito}' cancelado (motivo: {remito.motivo_cancelacion}). "
            f"{len(resumen['ejemplares'])} ejemplar(es) volvieron a estar disponibles en {remito.sede_origen.nombre} "
            f"y {len(resumen['prestamos'])} préstamo(s) quedaron cancelados.",
            "warning"
        )
    except TransicionInvalidaError as e:
        flash(f"Error de transición State: {e}", "danger")
    except BibliotecaExcepcion as e:
        flash(str(e), "danger")
    return redirect(url_for("remitos"))


# -------------------------------------------------------------------------
# 7. Reportes de Gestión (no triviales: indicadores, tasas y alertas calculadas)
# -------------------------------------------------------------------------
@app.route("/reportes")
def reportes():
    return render_template("reportes.html", hoy=date.today(), **generador_reportes.todos(date.today()))


def _enviar_pdf(buffer, nombre_archivo):
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=nombre_archivo)


@app.route("/reportes/pdf/activos")
def reporte_pdf_activos():
    rep = generador_reportes.prestamos_activos_y_transito(date.today())
    return _enviar_pdf(reportes_pdf.pdf_prestamos_activos_transito(rep), "reporte_prestamos_activos_transito.pdf")


@app.route("/reportes/pdf/vencidos")
def reporte_pdf_vencidos():
    rep = generador_reportes.morosidad_y_sanciones(date.today())
    return _enviar_pdf(reportes_pdf.pdf_morosidad_y_sanciones(rep), "reporte_morosidad_y_sanciones.pdf")


@app.route("/reportes/pdf/intersedes")
def reporte_pdf_intersedes():
    rep = generador_reportes.demanda_intersedes()
    return _enviar_pdf(reportes_pdf.pdf_demanda_intersedes(rep), "reporte_demanda_intersedes.pdf")


@app.route("/reportes/pdf/disponibilidad")
def reporte_pdf_disponibilidad():
    rep = generador_reportes.disponibilidad_por_sede()
    return _enviar_pdf(reportes_pdf.pdf_disponibilidad_por_sede(rep), "reporte_disponibilidad_por_sede.pdf")


@app.route("/reportes/pdf/logistica")
def reporte_pdf_logistica():
    rep = generador_reportes.efectividad_logistica(date.today())
    return _enviar_pdf(reportes_pdf.pdf_efectividad_logistica(rep), "reporte_efectividad_logistica.pdf")


@app.route("/reportes/pdf/movimiento")
def reporte_pdf_movimiento():
    rep = generador_reportes.movimiento_entre_sedes()
    return _enviar_pdf(reportes_pdf.pdf_movimiento_entre_sedes(rep), "reporte_movimiento_entre_sedes.pdf")


@app.route("/reportes/pdf/completo")
def reporte_pdf_completo():
    reps = generador_reportes.todos(date.today())
    return _enviar_pdf(reportes_pdf.pdf_todos_los_reportes(reps), "informe_completo_reportes.pdf")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
