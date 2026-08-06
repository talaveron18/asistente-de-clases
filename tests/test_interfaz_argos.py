from pathlib import Path

from interfaz_argos import NavegacionArgos, leer_material_clase


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
