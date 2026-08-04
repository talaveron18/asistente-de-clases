import json
import os
import time
from pathlib import Path

import pytest

from indice_sqlite import IndiceConocimientoSQLite
from orquestador import ClaseEnProcesoError, OrquestadorArgos


def _crear_clase(raiz: Path) -> Path:
    clase = raiz / "Inmunología" / "001 · 2026-08-04 · Citocinas"
    clase.mkdir(parents=True)
    (clase / "ficha.json").write_text(
        json.dumps(
            {"materia": "Inmunología", "titulo": "Citocinas", "numero": 1}
        ),
        encoding="utf-8",
    )
    (clase / "transcripcion.txt").write_text(
        "\n".join(
            [
                "[00:00] Docente: La interleucina seis participa en inflamación.",
                "[01:00] Docente: Qué función tienen los linfocitos te",
                "[02:00] Docente: Esto entra en el examen.",
            ]
        ),
        encoding="utf-8",
    )
    return clase


def test_orquestador_ejecuta_una_sola_cadena_y_registra_estado(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    clase = _crear_clase(raiz)
    indice = IndiceConocimientoSQLite(str(raiz))
    orquestador = OrquestadorArgos(indice)
    progreso = []

    resultado = orquestador.procesar_clase(
        clase, callback=lambda mensaje, valor: progreso.append((mensaje, valor))
    )

    assert resultado["archivo_fuente"] == "transcripcion_medica_revisada.txt"
    assert resultado["correcciones"] >= 2
    assert resultado["preguntas"] == 1
    assert resultado["avisos"] == 1
    assert progreso[-1][1] == 1.0

    estado = json.loads((clase / "estado_argos.json").read_text(encoding="utf-8"))
    assert estado["estado"] == "completado"
    assert [paso["nombre"] for paso in estado["pasos"]] == list(
        OrquestadorArgos.PASOS
    )
    assert all(paso["estado"] == "completado" for paso in estado["pasos"])
    assert not (clase / ".argos_procesando.lock").exists()

    pipeline = json.loads(
        (clase / "pipeline_clase.json").read_text(encoding="utf-8")
    )
    assert pipeline["archivo_fuente"] == "transcripcion_medica_revisada.txt"
    resultados = indice.buscar("interleucina 6", alcance="Clases")
    assert resultados
    assert "revisión médica" in resultados[0].ubicacion


def test_bloqueo_impide_procesar_la_misma_clase_en_paralelo(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    clase = _crear_clase(raiz)
    bloqueo = clase / ".argos_procesando.lock"
    bloqueo.write_text(
        json.dumps({"pid": os.getpid(), "inicio": time.time()}),
        encoding="utf-8",
    )
    indice = IndiceConocimientoSQLite(str(raiz))

    with pytest.raises(ClaseEnProcesoError):
        OrquestadorArgos(indice).procesar_clase(clase)

    assert bloqueo.exists()
