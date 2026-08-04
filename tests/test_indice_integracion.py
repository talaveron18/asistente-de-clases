import json
from pathlib import Path

from biblioteca_medica import BibliotecaMedica
from indice_sqlite import IndiceConocimientoSQLite


def test_documento_importado_y_procesado_llega_al_indice(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    biblioteca = BibliotecaMedica(str(raiz / "Biblioteca médica"))

    origen = tmp_path / "tratado_shock.txt"
    origen.write_text(
        "El shock séptico produce vasodilatación y alteraciones de la perfusión.",
        encoding="utf-8",
    )
    item, creado = biblioteca.importar_archivo(str(origen), "Tratados")
    assert creado is True

    procesado = biblioteca.procesar_documento(item["id"])
    assert procesado["estado_indice_ia"] == "texto_extraido"
    assert procesado["ruta_extraccion"]

    indice = IndiceConocimientoSQLite(str(raiz))
    stats = indice.reconstruir()
    resultados = indice.buscar("shock séptico", alcance="Biblioteca médica")

    assert stats["documentos"] == 1
    assert len(resultados) >= 1
    assert resultados[0].titulo == "tratado_shock.txt"
    assert resultados[0].pagina == 1


def test_indice_prefiere_transcripcion_medica_revisada(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    clase = raiz / "Inmunología" / "001 · 2026-08-04 · Citocinas"
    clase.mkdir(parents=True)
    (clase / "ficha.json").write_text(
        json.dumps({"materia": "Inmunología", "titulo": "Citocinas"}),
        encoding="utf-8",
    )
    (clase / "transcripcion.txt").write_text(
        "[00:10] Docente: La interleucina seis participa en la inflamación.",
        encoding="utf-8",
    )
    (clase / "transcripcion_medica_revisada.txt").write_text(
        "[00:10] Docente: La interleucina 6 participa en la inflamación.",
        encoding="utf-8",
    )

    indice = IndiceConocimientoSQLite(str(raiz))
    indice.reconstruir()
    resultados = indice.buscar("interleucina 6", alcance="Clases")

    assert resultados
    assert "interleucina 6" in resultados[0].contenido.lower()
