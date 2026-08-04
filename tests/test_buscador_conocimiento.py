import json
from pathlib import Path

from buscador_conocimiento import BuscadorConocimiento


def test_busca_en_clases_y_documentos(tmp_path):
    raiz = tmp_path / "Asistente de Clases"

    clase = raiz / "Fisiopatología II" / "001 · 2026-08-03 · Shock"
    clase.mkdir(parents=True)
    (clase / "ficha.json").write_text(json.dumps({
        "materia": "Fisiopatología II",
        "titulo": "Shock",
    }), encoding="utf-8")
    (clase / "transcripcion.txt").write_text(
        "[35:20] Docente: En el shock séptico existe vasodilatación periférica.",
        encoding="utf-8",
    )

    biblioteca = raiz / "Biblioteca médica"
    indice_texto = biblioteca / "_indice_texto"
    indice_texto.mkdir(parents=True)
    extraccion = indice_texto / "harrison.json"
    extraccion.write_text(json.dumps({
        "paginas": [
            {"pagina": 842, "texto": "El shock séptico se caracteriza por alteraciones circulatorias."}
        ]
    }), encoding="utf-8")
    (biblioteca / "indice_biblioteca.json").write_text(json.dumps([{
        "nombre": "Harrison.pdf",
        "categoria": "Tratados",
        "ruta": str(biblioteca / "Tratados" / "Harrison.pdf"),
        "estado_indice_ia": "texto_extraido",
        "ruta_indice_texto": str(extraccion),
    }]), encoding="utf-8")

    resultados = BuscadorConocimiento(str(raiz)).buscar("shock séptico")

    assert len(resultados) == 2
    assert any(r.minuto == "35:20" for r in resultados)
    assert any(r.pagina == 842 for r in resultados)


def test_no_busca_documentos_no_procesados(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    biblioteca = raiz / "Biblioteca médica"
    biblioteca.mkdir(parents=True)
    (biblioteca / "indice_biblioteca.json").write_text(json.dumps([{
        "nombre": "Escaneado.pdf",
        "categoria": "Tratados",
        "estado_indice_ia": "requiere_ocr",
        "ruta": str(biblioteca / "Escaneado.pdf"),
    }]), encoding="utf-8")

    resultados = BuscadorConocimiento(str(raiz)).buscar("insuficiencia")
    assert resultados == []
