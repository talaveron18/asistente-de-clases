import json
import multiprocessing
import os
import threading
import time
from pathlib import Path

from biblioteca_medica import BibliotecaMedica
from chat_argos import ChatArgos
from indice_sqlite import IndiceConocimientoSQLite
from orquestador import OrquestadorArgos


def _reconstruir_en_otro_proceso(raiz, salida, identificador, inicio):
    indice = IndiceConocimientoSQLite(raiz)
    original = indice._leer_clases

    def lectura_lenta():
        instante_inicio = time.time_ns()
        time.sleep(0.3)
        resultado = original()
        instante_fin = time.time_ns()
        Path(salida).write_text(
            json.dumps(
                {
                    "id": identificador,
                    "pid": os.getpid(),
                    "inicio": instante_inicio,
                    "fin": instante_fin,
                }
            ),
            encoding="utf-8",
        )
        return resultado

    indice._leer_clases = lectura_lenta
    assert inicio.wait(timeout=10)
    indice.reconstruir()


def _crear_clase(raiz: Path, numero: int = 1) -> Path:
    clase = raiz / "Inmunología" / f"{numero:03d} · 2026-08-04 · Citocinas"
    clase.mkdir(parents=True)
    (clase / "ficha.json").write_text(
        json.dumps(
            {"materia": "Inmunología", "titulo": "Citocinas", "numero": numero}
        ),
        encoding="utf-8",
    )
    (clase / "transcripcion.txt").write_text(
        "\n".join(
            [
                "[00:00] Docente: Este concepto vale para entender la inflamación.",
                "[01:00] Docente: La interleucina seis participa participa en la inflamación.",
                "[02:00] Docente: Qué función tienen los linfocitos te",
                "[03:00] Docente: Recordad que esto es clave para el examen.",
            ]
        ),
        encoding="utf-8",
    )
    return clase


def test_flujo_completo_chat_e_idempotencia(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    clase = _crear_clase(raiz)
    biblioteca = BibliotecaMedica(str(raiz / "Biblioteca médica"))
    tratado = tmp_path / "tratado_citocinas.txt"
    tratado.write_text(
        "La interleucina 6 es una citocina implicada en la respuesta inflamatoria.",
        encoding="utf-8",
    )
    item, _ = biblioteca.importar_archivo(str(tratado), "Tratados")
    biblioteca.procesar_documento(item["id"])
    indice = IndiceConocimientoSQLite(str(raiz))
    orquestador = OrquestadorArgos(indice)

    primero = orquestador.procesar_clase(clase)
    archivos_deterministas = [
        "transcripcion_medica_revisada.txt",
        "correcciones_medicas.json",
        "pipeline_clase.json",
        "transcripcion_limpia.txt",
        "analisis_clase.json",
        "analisis_clase.md",
        "apuntes_argos.md",
        "flashcards_argos.tsv",
        "preguntas_repaso.md",
        "repaso_rapido.md",
        "argos_enriquecido.json",
        "apuntes_argos_enriquecidos.md",
    ]
    primera_salida = {
        nombre: (clase / nombre).read_bytes() for nombre in archivos_deterministas
    }

    respuesta = ChatArgos(indice).preguntar("interleucina 6", alcance="Todo")
    segundo = orquestador.procesar_clase(clase)
    segunda_salida = {
        nombre: (clase / nombre).read_bytes() for nombre in archivos_deterministas
    }

    assert primero["archivo_fuente"] == "transcripcion_medica_revisada.txt"
    assert primero["referencias"] >= 1
    assert primero == segundo
    assert primera_salida == segunda_salida
    assert (clase / "apuntes_argos.docx").exists()
    assert respuesta.fuentes
    assert any(f.tipo_fuente == "Clase" and f.minuto == "01:00" for f in respuesta.fuentes)
    assert "interleucina 6" in respuesta.respuesta.lower()

    limpia = (clase / "transcripcion_limpia.txt").read_text(encoding="utf-8")
    assert "Este concepto vale" in limpia
    assert "participa participa" not in limpia
    pipeline = json.loads((clase / "pipeline_clase.json").read_text(encoding="utf-8"))
    assert pipeline["archivo_fuente"] == "transcripcion_medica_revisada.txt"
    assert pipeline["preguntas_detalladas"]
    assert pipeline["avisos_examen_detallados"]


def test_dos_instancias_no_reconstruyen_el_mismo_indice_a_la_vez(
    tmp_path, monkeypatch
):
    raiz = tmp_path / "Asistente de Clases"
    _crear_clase(raiz, 1)
    indice_a = IndiceConocimientoSQLite(str(raiz))
    indice_b = IndiceConocimientoSQLite(str(raiz))
    activos = 0
    maximo = 0
    guardia = threading.Lock()

    def envolver(indice):
        original = indice._leer_clases

        def lectura_lenta():
            nonlocal activos, maximo
            with guardia:
                activos += 1
                maximo = max(maximo, activos)
            try:
                time.sleep(0.15)
                return original()
            finally:
                with guardia:
                    activos -= 1

        monkeypatch.setattr(indice, "_leer_clases", lectura_lenta)

    envolver(indice_a)
    envolver(indice_b)
    errores = []

    def reconstruir(indice):
        try:
            indice.reconstruir()
        except Exception as exc:  # pragma: no cover - se comprueba abajo
            errores.append(exc)

    hilos = [
        threading.Thread(target=reconstruir, args=(indice_a,)),
        threading.Thread(target=reconstruir, args=(indice_b,)),
    ]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=5)

    assert all(not hilo.is_alive() for hilo in hilos)
    assert errores == []
    assert maximo == 1


def test_dos_procesos_no_reconstruyen_sqlite_simultaneamente(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    _crear_clase(raiz, 1)
    IndiceConocimientoSQLite(str(raiz)).reconstruir()
    contexto = multiprocessing.get_context("spawn")
    inicio = contexto.Event()
    salidas = [tmp_path / "intervalo-1.json", tmp_path / "intervalo-2.json"]
    procesos = [
        contexto.Process(
            target=_reconstruir_en_otro_proceso,
            args=(str(raiz), str(salidas[i]), i + 1, inicio),
        )
        for i in range(2)
    ]
    for proceso in procesos:
        proceso.start()
    inicio.set()
    for proceso in procesos:
        proceso.join(timeout=15)

    assert all(not proceso.is_alive() for proceso in procesos)
    assert all(proceso.exitcode == 0 for proceso in procesos)
    intervalos = [json.loads(ruta.read_text(encoding="utf-8")) for ruta in salidas]
    intervalos.sort(key=lambda x: x["inicio"])
    assert intervalos[0]["fin"] <= intervalos[1]["inicio"]
