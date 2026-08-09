from autoprueba_runtime import (
    ARCHIVOS_PIPELINE_OBLIGATORIOS,
    probar_pipeline_completo,
)


def test_autoprueba_ejecuta_pipeline_medico_completo(tmp_path):
    fuente = tmp_path / "fuente_shock.txt"
    fuente.write_text(
        "El shock causa hipoperfusión tisular y eleva el lactato por metabolismo anaerobio.",
        encoding="utf-8",
    )

    resultado = probar_pipeline_completo(tmp_path / "argos", fuente)

    assert resultado["ok"] is True
    assert resultado["archivos"] == len(ARCHIVOS_PIPELINE_OBLIGATORIOS)
    assert resultado["bloques"] >= 1
    assert resultado["flashcards"] >= 1
    assert resultado["referencias"] >= 1
