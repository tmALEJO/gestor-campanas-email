"""
Servidor local del gestor de correos Nariñotex.

Ejecuta:  python app.py      (o doble clic en iniciar.bat)
Abre solo el navegador en http://127.0.0.1:5050
"""
import io
import json
import threading
import webbrowser

from flask import Flask, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from core import db, servicio
from core.config import HOST, PUERTO, STATIC_DIR, listar_excels

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB por subida


def con():
    return db.conectar()


def _filtros_de(datos):
    return {
        "paises": datos.get("paises") or [],
        "proveedores": datos.get("proveedores") or [],
        "secciones": datos.get("secciones") or [],
        "modo": datos.get("modo") or "azar",
        "excluir_genericos": bool(datos.get("excluir_genericos")),
        "solo_verificados": bool(datos.get("solo_verificados")),
        "rellenar": bool(datos.get("rellenar", True)),
    }


def _archivos_subidos(campo="archivos"):
    archivos = [(f.filename, f.read()) for f in request.files.getlist(campo) if f and f.filename]
    if not archivos:
        raise ValueError("No seleccionaste ningún archivo.")
    return archivos


@app.errorhandler(ValueError)
@app.errorhandler(RuntimeError)
def error_usuario(e):
    return jsonify({"error": str(e)}), 400


@app.errorhandler(Exception)
def error_general(e):
    if isinstance(e, HTTPException):
        return e
    app.logger.exception(e)
    return jsonify({"error": f"Error interno: {e}"}), 500


# ------------------------------------------------------------------ páginas
@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ------------------------------------------------------------------ consultas
@app.get("/api/resumen")
def api_resumen():
    c = con()
    datos = servicio.resumen(c)
    datos["excels"] = [p.name for p in listar_excels()]
    return jsonify(datos)


@app.get("/api/opciones")
def api_opciones():
    return jsonify(servicio.opciones(con()))


@app.post("/api/contar")
def api_contar():
    return jsonify(servicio.contar(con(), _filtros_de(request.get_json(force=True))))


@app.get("/api/buscar")
def api_buscar():
    return jsonify(servicio.buscar(con(), request.args.get("q", "")))


@app.get("/api/lotes")
def api_lotes():
    return jsonify(servicio.lotes(con()))


# ------------------------------------------------------------------ acciones
@app.post("/api/importar_excel")
def api_importar_excel():
    db.respaldar("antes-importar")
    return jsonify(servicio.importar_excel(con()))


@app.post("/api/generar")
def api_generar():
    datos = request.get_json(force=True)
    db.respaldar("antes-generar")
    r = servicio.generar(con(), _filtros_de(datos), int(datos.get("cantidad") or 0), datos.get("nombre", ""))
    return jsonify(r)


@app.post("/api/completar")
def api_completar():
    filtros = _filtros_de(json.loads(request.form.get("filtros") or "{}"))
    db.respaldar("antes-completar")
    r = servicio.completar(con(), _archivos_subidos(), int(request.form.get("cantidad") or 0),
                           filtros, request.form.get("nombre", ""))
    return jsonify(r)


@app.post("/api/marcar")
def api_marcar():
    archivos = _archivos_subidos()
    palabra = request.form.get("palabra", "")
    if request.form.get("confirmar") != "1":
        return jsonify(servicio.previsualizar_marcado(con(), archivos, palabra))
    db.respaldar("antes-marcar")
    return jsonify(servicio.marcar_desde_archivos(con(), archivos, request.form.get("estado", ""),
                                                  palabra, request.form.get("motivo", "")))


@app.post("/api/importar_estado")
def api_importar_estado():
    db.respaldar("antes-importar-estado")
    return jsonify(servicio.importar_estado(con(), _archivos_subidos()))


@app.post("/api/estado_manual")
def api_estado_manual():
    d = request.get_json(force=True)
    return jsonify(servicio.cambiar_estado_manual(con(), d.get("email", ""), d.get("estado", "")))


@app.post("/api/lotes/<int:lote_id>/anular")
def api_anular(lote_id):
    db.respaldar("antes-anular")
    return jsonify(servicio.anular_lote(con(), lote_id))


@app.get("/api/lotes/<int:lote_id>/descargar")
def api_descargar(lote_id):
    contenido, mime, nombre = servicio.archivo_lote(
        con(), lote_id, request.args.get("formato", "csv"),
        request.args.get("extras") == "1", request.args.get("solo_nuevos") == "1")
    return send_file(io.BytesIO(contenido), mimetype=mime, as_attachment=True, download_name=nombre)


@app.get("/api/exportar")
def api_exportar():
    estado = request.args.get("estado", "todos")
    contenido = servicio.exportar_estado(con(), estado)
    return send_file(io.BytesIO(contenido), mimetype="text/csv", as_attachment=True,
                     download_name=f"estado_correos_{estado}.csv")


def preparar():
    c = con()
    total = c.execute("SELECT COUNT(*) FROM contactos").fetchone()[0]
    if total == 0 and listar_excels():
        print("Base vacía: importando y limpiando el Excel por primera vez...")
        rep = servicio.importar_excel(c)
        print(f"  -> {rep['validos_unicos']} correos válidos únicos, {rep['invalidos']} descartados.")
    else:
        db.respaldar("inicio")


if __name__ == "__main__":
    preparar()
    url = f"http://{HOST}:{PUERTO}"
    print(f"\n  Gestor de correos listo en {url}\n  (deja esta ventana abierta; ciérrala para apagarlo)\n")
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=HOST, port=PUERTO, debug=False, threaded=True)
