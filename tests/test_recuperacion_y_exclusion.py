import ast
import json
import os
import queue
import threading
import time
from pathlib import Path

import pytest

import argos_app
import biblioteca_medica as modulo_biblioteca
import bloqueos as modulo_bloqueos
from biblioteca_medica import BibliotecaMedica
from bloqueos import BloqueoArchivo
from indice_sqlite import IndiceConocimientoSQLite
from main import AsistenteClasesApp
from orquestador import OrquestadorArgos


def _crear_clase(raiz: Path) -> Path:
    clase = raiz / "Patología" / "001 · 2026-08-04 · Inflamación"
    clase.mkdir(parents=True)
    (clase / "ficha.json").write_text(
        json.dumps({"materia": "Patología", "titulo": "Inflamación"}),
        encoding="utf-8",
    )
    (clase / "transcripcion.txt").write_text(
        "[00:00] Docente: La interleucina seis causa inflamación.",
        encoding="utf-8",
    )
    return clase


def test_estado_de_clase_interrumpida_se_convierte_en_error(tmp_path):
    raiz = tmp_path / "Asistente de Clases"
    clase = _crear_clase(raiz)
    (clase / "estado_argos.json").write_text(
        json.dumps(
            {
                "estado": "procesando",
                "fin": None,
                "pasos": [
                    {"nombre": "analisis_clase", "estado": "procesando"}
                ],
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    orquestador = OrquestadorArgos(IndiceConocimientoSQLite(str(raiz)))

    assert orquestador.recuperar_interrumpidos(raiz) == 1

    estado = json.loads(
        (clase / "estado_argos.json").read_text(encoding="utf-8")
    )
    assert estado["estado"] == "error"
    assert estado["error"]["tipo"] == "ProcesamientoInterrumpido"
    assert estado["pasos"][0]["estado"] == "error"


def test_documento_interrumpido_se_recupera_y_reprocesa(tmp_path):
    raiz = tmp_path / "Biblioteca médica"
    biblioteca = BibliotecaMedica(str(raiz))
    origen = tmp_path / "tratado.txt"
    origen.write_text("Contenido médico recuperable.", encoding="utf-8")
    item, _ = biblioteca.importar_archivo(str(origen), "Tratados")
    indice = biblioteca._leer_indice()
    indice[0]["estado_indice_ia"] = "procesando"
    biblioteca._guardar_indice(indice)

    recuperada = BibliotecaMedica(str(raiz))

    assert recuperada.interrumpidos_recuperados == 1
    assert recuperada.listar()[0]["estado_indice_ia"] == "error"
    resultados = recuperada.procesar_pendientes()
    assert len(resultados) == 1
    assert resultados[0]["estado_indice_ia"] == "texto_extraido"


def test_biblioteca_serializa_extraccion_e_importacion(
    tmp_path, monkeypatch
):
    raiz = tmp_path / "Biblioteca médica"
    biblioteca_a = BibliotecaMedica(str(raiz))
    biblioteca_b = BibliotecaMedica(str(raiz))
    primero = tmp_path / "primero.txt"
    segundo = tmp_path / "segundo.txt"
    primero.write_text("Primer documento médico.", encoding="utf-8")
    segundo.write_text("Segundo documento médico.", encoding="utf-8")
    item, _ = biblioteca_a.importar_archivo(str(primero), "Tratados")
    iniciado = threading.Event()
    continuar = threading.Event()
    original = modulo_biblioteca.extraer_documento

    def extraccion_lenta(ruta, callback=None):
        iniciado.set()
        assert continuar.wait(timeout=5)
        return original(ruta, callback)

    monkeypatch.setattr(modulo_biblioteca, "extraer_documento", extraccion_lenta)
    errores = []

    def extraer():
        try:
            biblioteca_a.procesar_documento(item["id"])
        except Exception as exc:  # pragma: no cover - se comprueba abajo
            errores.append(exc)

    def importar():
        try:
            biblioteca_b.importar_archivo(str(segundo), "Apuntes")
        except Exception as exc:  # pragma: no cover - se comprueba abajo
            errores.append(exc)

    hilo_extraccion = threading.Thread(target=extraer)
    hilo_importacion = threading.Thread(target=importar)
    hilo_extraccion.start()
    assert iniciado.wait(timeout=5)
    hilo_importacion.start()
    time.sleep(0.1)
    assert hilo_importacion.is_alive()
    continuar.set()
    hilo_extraccion.join(timeout=5)
    hilo_importacion.join(timeout=5)

    assert errores == []
    items = BibliotecaMedica(str(raiz)).listar()
    assert {x["nombre"] for x in items} == {"primero.txt", "segundo.txt"}
    estados = {x["nombre"]: x["estado_indice_ia"] for x in items}
    assert estados["primero.txt"] == "texto_extraido"
    assert estados["segundo.txt"] == "pendiente"


def test_pid_reutilizado_no_mantiene_un_bloqueo(tmp_path, monkeypatch):
    ruta = tmp_path / ".lock"
    monkeypatch.setattr(
        modulo_bloqueos,
        "_identidad_proceso",
        lambda _pid: "identidad-del-proceso-actual",
    )
    ruta.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "pid_inicio": "identidad-de-un-proceso-anterior",
                "host": "",
                "token": "anterior",
            }
        ),
        encoding="utf-8",
    )

    with BloqueoArchivo(ruta):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        assert datos["token"] != "anterior"
    assert not ruta.exists()


def test_segunda_ventana_no_crea_otra_cola(tmp_path, monkeypatch):
    ruta_lock = tmp_path / ".argos_instancia.lock"
    monkeypatch.setattr(argos_app, "_ruta_bloqueo_instancia", lambda: ruta_lock)
    avisos = []
    monkeypatch.setattr(argos_app, "_mostrar_aviso_instancia", avisos.append)
    creadas = []

    class AppFalsa:
        def __init__(self):
            creadas.append(self)

        def mainloop(self):
            return None

    monkeypatch.setattr(argos_app, "ArgosApp", AppFalsa)
    with BloqueoArchivo(ruta_lock):
        assert argos_app.ejecutar_argos() == 2
    assert creadas == []
    assert avisos and "ya está abierto" in avisos[0]

    assert argos_app.ejecutar_argos() == 0
    assert len(creadas) == 1
    assert not ruta_lock.exists()


def test_reconstruccion_manual_entra_en_la_misma_cola():
    app = object.__new__(argos_app.ArgosApp)
    app._indice_pendiente = False
    app._cola_pipeline = queue.Queue()

    class EtiquetaFalsa:
        def __init__(self):
            self.texto = ""

        def configure(self, **kwargs):
            self.texto = kwargs.get("text", "")

    app.estado_chat = EtiquetaFalsa()

    argos_app.ArgosApp._reconstruir_indice(app)

    assert app._indice_pendiente is True
    assert app._cola_pipeline.get_nowait() == {"tipo": "indice"}
    assert "cola" in app.estado_chat.texto.lower()


def test_main_no_es_un_punto_de_entrada_y_spec_usa_argos_app():
    raiz = Path(__file__).parents[1]
    arbol = ast.parse((raiz / "main.py").read_text(encoding="utf-8"))
    comparaciones_main = [
        nodo
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Compare)
        and any(
            isinstance(valor, ast.Constant) and valor.value == "__main__"
            for valor in nodo.comparators
        )
    ]
    assert comparaciones_main == []
    assert '["argos_app.py"]' in (raiz / "ARGOS.spec").read_text(
        encoding="utf-8"
    )


def test_resultado_de_carga_de_modelos_se_escribe_atomicamente(
    tmp_path, monkeypatch
):
    destino = tmp_path / "ready.json"
    monkeypatch.setenv("ARGOS_READY_FILE", str(destino))

    AsistenteClasesApp._registrar_resultado_modelos(True, "Listo · CPU")

    resultado = json.loads(destino.read_text(encoding="utf-8"))
    assert resultado == {
        "modelos_cargados": True,
        "detalle": "Listo · CPU",
    }
    assert not destino.with_suffix(".json.tmp").exists()
