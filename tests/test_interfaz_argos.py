import json
import queue
import threading
from types import SimpleNamespace
from pathlib import Path

from interfaz_argos import (
    ARCHIVOS_MATERIAL_COMPLETO,
    NavegacionArgos,
    leer_estado_material_clase,
    leer_material_clase,
    preparar_material_para_lectura,
)
from main import AsistenteClasesApp


def test_navegacion_prioriza_el_flujo_del_estudiante():
    assert NavegacionArgos.ORDEN == [
        "Inicio",
        "Grabar clase",
        "Importar archivo",
        "Mis clases",
        "Biblioteca",
        "Chat ARGOS",
        "Procesar clase",
        "Configuración",
    ]
    assert NavegacionArgos.ETIQUETAS["Procesar clase"] == "Estado y procesos"
    assert NavegacionArgos.ETIQUETAS["Chat ARGOS"] == "Preguntar a ARGOS"


def test_ficha_prefiere_material_revisado_y_enriquecido(tmp_path):
    (tmp_path / "transcripcion.txt").write_text("original", encoding="utf-8")
    revisada = tmp_path / "transcripcion_medica_revisada.txt"
    revisada.write_text("revisada", encoding="utf-8")
    (tmp_path / "apuntes_argos.md").write_text("base", encoding="utf-8")
    enriquecidos = tmp_path / "apuntes_argos_enriquecidos.md"
    enriquecidos.write_text("enriquecidos", encoding="utf-8")

    ruta_transcripcion, transcripcion = leer_material_clase(
        tmp_path, "Transcripción"
    )
    ruta_apuntes, apuntes = leer_material_clase(tmp_path, "Apuntes")

    assert ruta_transcripcion == revisada
    assert transcripcion == "revisada"
    assert ruta_apuntes == enriquecidos
    assert apuntes == "enriquecidos"


def test_redisenio_no_contiene_marca_ni_textos_de_proactor():
    raiz = Path(__file__).resolve().parents[1]
    codigo = "\n".join(
        (raiz / nombre).read_text(encoding="utf-8")
        for nombre in ("interfaz_argos.py", "main.py", "argos_app.py")
    ).lower()
    assert "proactor" not in codigo
    assert "potor" not in codigo


def test_estado_material_exige_todos_los_archivos_obligatorios(tmp_path):
    (tmp_path / "transcripcion.txt").write_text("Clase útil", encoding="utf-8")
    (tmp_path / "estado_argos.json").write_text(
        json.dumps({"estado": "completado"}), encoding="utf-8"
    )

    assert leer_estado_material_clase(tmp_path).clave == "incompleto"

    for nombre in ARCHIVOS_MATERIAL_COMPLETO:
        (tmp_path / nombre).write_text("contenido", encoding="utf-8")

    estado = leer_estado_material_clase(tmp_path)
    assert estado.clave == "listo"
    assert estado.etiqueta == "Material listo"


def test_estado_material_resume_la_trazabilidad(tmp_path):
    for nombre in ARCHIVOS_MATERIAL_COMPLETO:
        (tmp_path / nombre).write_text("contenido", encoding="utf-8")
    (tmp_path / "trazabilidad_argos.json").write_text(
        json.dumps({
            "metricas": {
                "cobertura_documental_porcentaje": 75.0,
                "preguntas_con_respuesta_explicitada": 3,
                "preguntas": 5,
            }
        }),
        encoding="utf-8",
    )

    estado = leer_estado_material_clase(tmp_path)

    assert estado.clave == "listo"
    assert "Cobertura documental: 75 %" in estado.detalle
    assert "Respuestas explícitas localizadas: 3 de 5" in estado.detalle


def test_ficha_incluye_fuentes_y_control_como_seccion(tmp_path):
    trazabilidad = tmp_path / "trazabilidad_argos.md"
    trazabilidad.write_text("# Fuentes y control", encoding="utf-8")

    ruta, contenido = leer_material_clase(tmp_path, "Fuentes")

    assert ruta == trazabilidad
    assert "Fuentes y control" in contenido


def test_estado_material_muestra_el_error_persistente(tmp_path):
    (tmp_path / "estado_argos.json").write_text(
        json.dumps(
            {
                "estado": "error",
                "error": {"mensaje": "Falló la generación de preguntas"},
            }
        ),
        encoding="utf-8",
    )

    estado = leer_estado_material_clase(tmp_path)

    assert estado.clave == "error"
    assert "preguntas" in estado.detalle


def test_worker_encola_actualizacion_y_no_ejecuta_tk_directamente():
    llamadas = []
    app = SimpleNamespace(
        _cerrando=False,
        _hilo_ui=threading.get_ident(),
        _cola_ui=queue.SimpleQueue(),
    )

    hilo = threading.Thread(
        target=lambda: AsistenteClasesApp._enviar_ui(
            app, llamadas.append, "actualizado"
        )
    )
    hilo.start()
    hilo.join(timeout=2)

    assert llamadas == []
    callback, args = app._cola_ui.get_nowait()
    callback(*args)
    assert llamadas == ["actualizado"]


def test_medidor_conserva_solo_el_ultimo_nivel_publicado():
    app = SimpleNamespace(_nivel_audio_pendiente=None)

    AsistenteClasesApp._publicar_nivel_audio(app, 0.15)
    AsistenteClasesApp._publicar_nivel_audio(app, 0.72)

    assert app._nivel_audio_pendiente == 0.72


def test_arranque_de_whisper_deja_diagnostico_sin_simular_exito(
    tmp_path, monkeypatch
):
    estado = tmp_path / "estado-modelo.json"
    listo = tmp_path / "modelo-listo.json"
    monkeypatch.setenv("ARGOS_MODEL_STATUS_FILE", str(estado))
    monkeypatch.setenv("ARGOS_READY_FILE", str(listo))

    AsistenteClasesApp._registrar_progreso_modelos(
        "Cargando Whisper tiny...", 0.1
    )

    progreso = json.loads(estado.read_text(encoding="utf-8"))
    assert progreso["estado"] == "cargando_modelos"
    assert progreso["progreso"] == 0.1
    assert not listo.exists()

    AsistenteClasesApp._registrar_resultado_modelos(True, "Listo · CPU")

    resultado = json.loads(listo.read_text(encoding="utf-8"))
    assert resultado == {"modelos_cargados": True, "detalle": "Listo · CPU"}


def test_markdown_se_muestra_sin_marcas_tecnicas():
    fragmentos = preparar_material_para_lectura(
        "# Shock\n\n## Idea central\n\n- **Hipoperfusión** tisular\n",
        "Apuntes",
    )
    texto = "".join(fragmento for fragmento, _etiqueta in fragmentos)
    etiquetas = [etiqueta for _fragmento, etiqueta in fragmentos]

    assert "#" not in texto
    assert "**" not in texto
    assert "• Hipoperfusión tisular" in texto
    assert "titulo1" in etiquetas
    assert "titulo2" in etiquetas


def test_tarjetas_tsv_se_convierten_en_pregunta_y_respuesta():
    fragmentos = preparar_material_para_lectura(
        "Frente\tDorso\tMinuto\n¿Qué es el shock?\tHipoperfusión tisular.\t03:12\n",
        "Tarjetas",
    )
    texto = "".join(fragmento for fragmento, _etiqueta in fragmentos)

    assert "Tarjeta 1" in texto
    assert "¿Qué es el shock?" in texto
    assert "Hipoperfusión tisular." in texto
    assert "Referencia: 03:12" in texto
