import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from indice_sqlite import IndiceConocimientoSQLite
from orquestador import ClaseEnProcesoError, OrquestadorArgos
import orquestador as modulo_orquestador


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
    assert any(0.75 < valor <= 0.89 for _mensaje, valor in progreso)

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


def test_bloqueo_real_impide_dos_hilos_sobre_la_misma_clase(
    tmp_path, monkeypatch
):
    raiz = tmp_path / "Asistente de Clases"
    clase = _crear_clase(raiz)
    indice = IndiceConocimientoSQLite(str(raiz))
    entro = threading.Event()
    continuar = threading.Event()
    errores = []
    original = modulo_orquestador.corregir_archivo_transcripcion

    def correccion_lenta(carpeta):
        entro.set()
        assert continuar.wait(timeout=5)
        return original(carpeta)

    monkeypatch.setattr(
        modulo_orquestador, "corregir_archivo_transcripcion", correccion_lenta
    )

    def primer_proceso():
        try:
            OrquestadorArgos(indice).procesar_clase(clase)
        except Exception as exc:  # pragma: no cover - se comprueba abajo
            errores.append(exc)

    hilo = threading.Thread(target=primer_proceso)
    hilo.start()
    assert entro.wait(timeout=5)
    with pytest.raises(ClaseEnProcesoError):
        OrquestadorArgos(indice).procesar_clase(clase)
    continuar.set()
    hilo.join(timeout=10)

    assert not hilo.is_alive()
    assert errores == []
    assert not (clase / ".argos_procesando.lock").exists()


def test_bloqueo_obsoleto_se_recupera_si_el_pid_ya_no_existe(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    clase = _crear_clase(raiz)
    bloqueo = clase / ".argos_procesando.lock"
    bloqueo.write_text(
        json.dumps(
            {
                "pid": 999_999_999,
                "host": socket.gethostname(),
                "inicio": "2026-08-04T00:00:00",
                "token": "proceso-terminado",
            }
        ),
        encoding="utf-8",
    )

    resultado = OrquestadorArgos(
        IndiceConocimientoSQLite(str(raiz))
    ).procesar_clase(clase)

    assert resultado["archivo_fuente"] == "transcripcion_medica_revisada.txt"
    assert not bloqueo.exists()


def test_fallo_se_registra_y_siempre_retira_el_bloqueo(tmp_path, monkeypatch):
    raiz = tmp_path / "Asistente de Clases"
    clase = _crear_clase(raiz)

    def fallar(_carpeta):
        raise RuntimeError("fallo sintético de corrección")

    monkeypatch.setattr(
        modulo_orquestador, "corregir_archivo_transcripcion", fallar
    )
    with pytest.raises(RuntimeError, match="fallo sintético"):
        OrquestadorArgos(
            IndiceConocimientoSQLite(str(raiz))
        ).procesar_clase(clase)

    estado = json.loads((clase / "estado_argos.json").read_text(encoding="utf-8"))
    assert estado["estado"] == "error"
    assert estado["error"]["tipo"] == "RuntimeError"
    assert estado["pasos"][-1]["estado"] == "error"
    assert estado["pasos"][-1]["error"]["mensaje"] == "fallo sintético de corrección"
    assert not (clase / ".argos_procesando.lock").exists()
