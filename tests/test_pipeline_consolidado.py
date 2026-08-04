import json
from pathlib import Path

from pipeline_clase import analizar_clase_completa


def _crear_clase(raiz: Path) -> Path:
    clase = raiz / "Fisiopatología" / "001 · 2026-08-04 · Shock"
    clase.mkdir(parents=True)
    (clase / "ficha.json").write_text(
        json.dumps(
            {"materia": "Fisiopatología", "titulo": "Shock", "numero": 1}
        ),
        encoding="utf-8",
    )
    (clase / "transcripcion.txt").write_text(
        "\n".join(
            [
                "[00:00] Docente: Este paciente vale para el estudio.",
                "[01:00] Docente: Qué ocurre en el shock distributivo",
                "[02:00] Docente: La perfusión perfusión disminuye.",
                "[03:00] Docente: Recordad que esto es clave para el examen.",
                "[12:30] Docente: Ahora vamos a hablar de tratamiento vasopresor.",
            ]
        ),
        encoding="utf-8",
    )
    (clase / "transcripcion_medica_revisada.txt").write_text(
        "\n".join(
            [
                "[00:00] Docente: Este paciente vale para el estudio.",
                "[01:00] Docente: Qué ocurre en el shock distributivo",
                "[02:00] Docente: La perfusión perfusión disminuye.",
                "[03:00] Docente: Recordad que esto es clave para el examen.",
                "[12:30] Docente: Ahora vamos a hablar de tratamiento vasopresor.",
            ]
        ),
        encoding="utf-8",
    )
    return clase


def test_pipeline_conserva_mejoras_de_los_modulos_retirados(tmp_path):
    clase = _crear_clase(tmp_path)

    resultado = analizar_clase_completa(clase, minutos_bloque=10)

    assert resultado["archivo_fuente"] == "transcripcion_medica_revisada.txt"
    assert resultado["procedencia"] == "clase/revisada"
    assert len(resultado["bloques"]) >= 2
    assert resultado["indice_temporal"]
    assert any(
        pregunta["confianza"] == "media"
        and "Qué ocurre" in pregunta["texto"]
        for pregunta in resultado["preguntas_detalladas"]
    )
    assert any(
        "Recordad que" in aviso["texto"]
        for aviso in resultado["avisos_examen_detallados"]
    )

    limpia = (clase / "transcripcion_limpia.txt").read_text(encoding="utf-8")
    assert "Este paciente vale para el estudio" in limpia
    assert "perfusión perfusión" not in limpia
    assert "La perfusión disminuye" in limpia

    analisis = json.loads(
        (clase / "analisis_clase.json").read_text(encoding="utf-8")
    )
    assert analisis["archivo_fuente"] == "transcripcion_medica_revisada.txt"
    assert analisis["preguntas"]
