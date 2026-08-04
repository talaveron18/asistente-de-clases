import json
import shutil
from pathlib import Path

import pytest

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


def test_indice_recupera_extraccion_si_la_ruta_guardada_es_antigua(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    biblioteca = BibliotecaMedica(str(raiz / "Biblioteca médica"))
    origen = tmp_path / "farreras.txt"
    origen.write_text(
        "La insuficiencia cardíaca puede producir congestión pulmonar.",
        encoding="utf-8",
    )
    item, _ = biblioteca.importar_archivo(str(origen), "Tratados")
    biblioteca.procesar_documento(item["id"])

    indice_path = biblioteca.indice_path
    registros = json.loads(indice_path.read_text(encoding="utf-8"))
    registros[0]["ruta_extraccion"] = str(
        tmp_path / "ubicacion_antigua" / "inexistente.json"
    )
    indice_path.write_text(
        json.dumps(registros, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    indice = IndiceConocimientoSQLite(str(raiz))
    stats = indice.reconstruir()
    resultados = indice.buscar("congestión pulmonar", alcance="Tratados")

    assert stats["documentos"] == 1
    assert resultados
    assert resultados[0].titulo == "farreras.txt"


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
    assert "revisión médica" in resultados[0].ubicacion


@pytest.mark.parametrize(
    "clave_historica",
    ["ruta_extraccion", "ruta_indice_texto", "indice_texto"],
)
def test_indice_admite_todas_las_claves_historicas_de_extraccion(
    tmp_path, clave_historica
):
    raiz = tmp_path / clave_historica / "Asistente de Clases"
    biblioteca = BibliotecaMedica(str(raiz / "Biblioteca médica"))
    origen = tmp_path / f"{clave_historica}.txt"
    origen.write_text("La rifampicina puede teñir de naranja los fluidos.", encoding="utf-8")
    item, _ = biblioteca.importar_archivo(str(origen), "Apuntes")
    procesado = biblioteca.procesar_documento(item["id"])

    registros = json.loads(biblioteca.indice_path.read_text(encoding="utf-8"))
    ruta_extraccion = registros[0].pop("ruta_extraccion")
    registros[0][clave_historica] = ruta_extraccion
    biblioteca.indice_path.write_text(
        json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    indice = IndiceConocimientoSQLite(str(raiz))
    indice.reconstruir()
    resultados = indice.buscar("rifampicina", alcance="Apuntes")

    assert procesado["estado_indice_ia"] == "texto_extraido"
    assert resultados
    assert resultados[0].categoria == "Apuntes"
    assert resultados[0].pagina == 1


def test_indice_recupera_extraccion_y_original_tras_mover_biblioteca(tmp_path):
    raiz_antigua = tmp_path / "antigua" / "Asistente de Clases"
    biblioteca = BibliotecaMedica(str(raiz_antigua / "Biblioteca médica"))
    origen = tmp_path / "harrison.txt"
    origen.write_text("La endocarditis puede producir vegetaciones.", encoding="utf-8")
    item, _ = biblioteca.importar_archivo(str(origen), "Tratados")
    biblioteca.procesar_documento(item["id"])

    raiz_nueva = tmp_path / "nueva" / "Asistente de Clases"
    raiz_nueva.parent.mkdir()
    shutil.move(str(raiz_antigua), str(raiz_nueva))

    indice = IndiceConocimientoSQLite(str(raiz_nueva))
    indice.reconstruir()
    resultados = indice.buscar("vegetaciones", alcance="Tratados")

    assert resultados
    ruta_original = Path(resultados[0].ruta)
    assert ruta_original.exists()
    assert raiz_nueva in ruta_original.parents


def test_indice_conserva_categoria_y_pagina_documental(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    biblioteca = BibliotecaMedica(str(raiz / "Biblioteca médica"))
    original = biblioteca.carpetas["Exámenes"] / "parcial.txt"
    original.write_text("Contenido del parcial", encoding="utf-8")
    extraccion = biblioteca.indice_texto / "doc-examen.json"
    extraccion.write_text(
        json.dumps(
            {
                "paginas": [
                    {"pagina": 1, "texto": "Pregunta sobre neumonía."},
                    {"pagina": 2, "texto": "Pregunta sobre meningococo."},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    biblioteca.indice_path.write_text(
        json.dumps(
            [
                {
                    "id": "doc-examen",
                    "nombre": original.name,
                    "categoria": "Exámenes",
                    "ruta": str(original),
                    "estado_indice_ia": "texto_extraido",
                    "ruta_extraccion": str(extraccion),
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    indice = IndiceConocimientoSQLite(str(raiz))
    indice.reconstruir()
    resultados = indice.buscar("meningococo", alcance="Exámenes")

    assert resultados
    assert resultados[0].categoria == "Exámenes"
    assert resultados[0].pagina == 2
    assert resultados[0].ubicacion == "Página 2"
