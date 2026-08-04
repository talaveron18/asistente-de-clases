from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from bloqueos import BloqueoArchivo, BloqueoOcupadoError
from chat_argos import ChatArgos
from indice_sqlite import IndiceConocimientoSQLite
from main import AsistenteClasesApp
from orquestador import ClaseEnProcesoError, OrquestadorArgos


class ArgosApp(AsistenteClasesApp):
    """Único punto de entrada y única cola de procesamiento de ARGOS."""

    def __init__(self):
        super().__init__()
        self.title("ARGOS · Clases de Medicina")
        self.indice_fts = IndiceConocimientoSQLite(str(self.repositorio.raiz))
        self.chat_argos = ChatArgos(self.indice_fts)
        self.orquestador = OrquestadorArgos(self.indice_fts)

        self._clases_pipeline: list[dict] = []
        self._cola_pipeline: queue.Queue[dict] = queue.Queue()
        self._rutas_pendientes: set[str] = set()
        self._pipeline_activo = False
        self._indice_pendiente = False

        self.tab_pipeline = self.tabs.add("Procesar clase")
        self.tab_chat = self.tabs.add("Chat ARGOS")
        self._crear_tab_pipeline()
        self._crear_tab_chat()
        recuperadas = self.orquestador.recuperar_interrumpidos(
            self.repositorio.raiz
        )
        self._actualizar_selector_pipeline()
        self._actualizar_estado_indice()
        if recuperadas:
            self.estado_pipeline.configure(
                text=(
                    f"Se recuperaron {recuperadas} clases interrumpidas; "
                    "puedes reprocesarlas."
                )
            )

        threading.Thread(
            target=self._consumir_cola_pipeline,
            daemon=True,
            name="argos-pipeline",
        ).start()

    def _mostrar_resultados(self, caja, segmentos, carpeta):
        caja.delete("1.0", "end")
        caja.insert(
            "end",
            "\n".join(s.a_linea_txt() for s in segmentos)
            if segmentos
            else "No se detectó voz.",
        )
        self.progreso_grabar.set(0)
        self.progreso_archivo.set(0)
        self.estado.configure(text="Transcripción guardada. Clase en cola de análisis...")
        self._refrescar_clases()
        self._actualizar_selector_pipeline()
        self._encolar_pipeline(carpeta, automatico=True)

    def _encolar_pipeline(self, carpeta: str | Path, automatico: bool) -> bool:
        ruta = str(Path(carpeta).resolve())
        if ruta in self._rutas_pendientes:
            if not automatico:
                messagebox.showwarning(
                    "ARGOS", "Esta clase ya está en la cola de procesamiento."
                )
            return False
        self._rutas_pendientes.add(ruta)
        self._cola_pipeline.put(
            {"tipo": "clase", "ruta": ruta, "automatico": automatico}
        )
        posicion = self._cola_pipeline.qsize()
        self.estado_pipeline.configure(
            text=f"Clase añadida a la cola. Posición aproximada: {posicion}."
        )
        return True

    def _consumir_cola_pipeline(self):
        while True:
            trabajo = self._cola_pipeline.get()
            if trabajo.get("tipo") == "indice":
                self._consumir_reconstruccion_indice()
                continue
            ruta = trabajo["ruta"]
            automatico = bool(trabajo["automatico"])
            self._pipeline_activo = True
            self.after(0, self._inicio_pipeline_ui, ruta)
            try:
                resultado = self.orquestador.procesar_clase(
                    ruta,
                    callback=lambda mensaje, progreso: self.after(
                        0,
                        self._actualizar_progreso_pipeline,
                        mensaje,
                        progreso,
                    ),
                )
                self.after(
                    0,
                    self._pipeline_completado,
                    ruta,
                    resultado,
                    automatico,
                )
            except ClaseEnProcesoError as exc:
                self.after(0, self._pipeline_error, ruta, str(exc), automatico)
            except Exception as exc:
                self.after(0, self._pipeline_error, ruta, str(exc), automatico)
            finally:
                self._rutas_pendientes.discard(ruta)
                self._pipeline_activo = False
                self._cola_pipeline.task_done()
                self.after(0, self._fin_pipeline_ui)

    def _consumir_reconstruccion_indice(self):
        self._pipeline_activo = True
        self.after(0, self._inicio_indice_ui)
        try:
            stats = self.indice_fts.reconstruir(
                callback=lambda mensaje, progreso: self.after(
                    0,
                    self._actualizar_progreso_indice,
                    mensaje,
                    progreso,
                )
            )
            self.after(0, self._indice_completado, stats)
        except Exception as exc:
            self.after(0, self._indice_error, str(exc))
        finally:
            self._indice_pendiente = False
            self._pipeline_activo = False
            self._cola_pipeline.task_done()
            self.after(0, self._fin_pipeline_ui)

    def _inicio_indice_ui(self):
        self.btn_reprocesar.configure(state="disabled")
        self.estado_chat.configure(text="Reconstruyendo índice FTS5...")
        self.estado.configure(text="ARGOS está actualizando el índice...")

    def _actualizar_progreso_indice(self, mensaje: str, progreso: float):
        porcentaje = round(max(0.0, min(1.0, progreso)) * 100)
        self.estado_chat.configure(text=f"{mensaje} ({porcentaje} %)")
        self.estado.configure(text=mensaje)

    def _indice_completado(self, stats: dict):
        self._actualizar_estado_indice()
        self.estado.configure(text="Índice FTS5 actualizado.")
        messagebox.showinfo(
            "Índice ARGOS",
            f"Índice listo: {stats['bloques']} bloques.",
        )

    def _indice_error(self, error: str):
        self.estado_chat.configure(text=f"Error al actualizar el índice: {error}")
        self.estado.configure(text=f"Error al actualizar el índice: {error}")
        messagebox.showerror("Índice ARGOS", error)

    def _inicio_pipeline_ui(self, ruta: str):
        self.btn_reprocesar.configure(state="disabled")
        self.progreso_pipeline.set(0)
        self.estado_pipeline.configure(text=f"Procesando: {Path(ruta).name}")
        self.estado.configure(text="ARGOS está procesando una clase...")

    def _actualizar_progreso_pipeline(self, mensaje: str, progreso: float):
        self.estado_pipeline.configure(text=mensaje)
        self.estado.configure(text=mensaje)
        self.progreso_pipeline.set(max(0.0, min(1.0, progreso)))

    def _fin_pipeline_ui(self):
        self.btn_reprocesar.configure(state="normal")
        if self._cola_pipeline.empty():
            self.progreso_pipeline.set(0)

    def _pipeline_completado(
        self,
        ruta: str,
        resultado: dict,
        automatico: bool,
    ):
        self.progreso_pipeline.set(1)
        self.estado_pipeline.configure(text="Procesamiento completado.")
        self.estado.configure(text=f"Clase completa: {ruta}")
        self._actualizar_estado_indice()
        self._actualizar_selector_pipeline()
        self._mostrar_resumen_pipeline(ruta, resultado)
        titulo = "Clase procesada" if automatico else "Reprocesamiento completado"
        messagebox.showinfo(
            "ARGOS",
            f"{titulo}.\n\n"
            f"Fuente: {resultado.get('archivo_fuente', '')}\n"
            f"Bloques: {resultado.get('bloques', 0)}\n"
            f"Avisos de examen: {resultado.get('avisos', 0)}\n"
            f"Preguntas: {resultado.get('preguntas', 0)}\n"
            f"Correcciones médicas: {resultado.get('correcciones', 0)}\n"
            f"Flashcards: {resultado.get('flashcards', 0)}\n"
            f"Referencias locales: {resultado.get('referencias', 0)}\n\n"
            f"Carpeta:\n{ruta}",
        )

    def _pipeline_error(self, ruta: str, error: str, automatico: bool):
        self.progreso_pipeline.set(0)
        self.estado_pipeline.configure(text=f"Error: {error}")
        self.estado.configure(
            text=f"Clase guardada; procesamiento incompleto: {error}"
        )
        messagebox.showerror(
            "ARGOS",
            "La transcripción está guardada, pero el procesamiento falló.\n\n"
            f"Clase: {ruta}\n\nError: {error}\n\n"
            "Consulta estado_argos.json dentro de la carpeta.",
        )

    def _crear_tab_pipeline(self):
        panel = ctk.CTkFrame(self.tab_pipeline)
        panel.pack(fill="x", padx=14, pady=14)
        ctk.CTkLabel(
            panel,
            text="Pipeline único de clase",
            font=ctk.CTkFont(size=19, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            panel,
            text=(
                "Corrección médica → análisis → material de estudio → índice FTS5 "
                "→ referencias. Las clases se procesan en una sola cola."
            ),
            text_color="#aaaaaa",
            anchor="w",
            justify="left",
            wraplength=930,
        ).pack(fill="x", padx=14, pady=(0, 12))

        fila = ctk.CTkFrame(panel, fg_color="transparent")
        fila.pack(fill="x", padx=14, pady=(0, 14))
        self.selector_pipeline = ctk.CTkComboBox(
            fila, values=["Sin clases guardadas"], width=650
        )
        self.selector_pipeline.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            fila,
            text="Actualizar",
            command=self._actualizar_selector_pipeline,
            width=90,
        ).pack(side="left", padx=6)
        self.btn_reprocesar = ctk.CTkButton(
            fila,
            text="Reprocesar clase",
            command=self._reprocesar_clase,
            width=130,
        )
        self.btn_reprocesar.pack(side="left")

        self.estado_pipeline = ctk.CTkLabel(
            self.tab_pipeline, text="Selecciona una clase.", anchor="w"
        )
        self.estado_pipeline.pack(fill="x", padx=18, pady=(0, 6))
        self.progreso_pipeline = ctk.CTkProgressBar(self.tab_pipeline)
        self.progreso_pipeline.pack(fill="x", padx=14, pady=(0, 10))
        self.progreso_pipeline.set(0)
        self.salida_pipeline = ctk.CTkTextbox(
            self.tab_pipeline, font=ctk.CTkFont(size=13)
        )
        self.salida_pipeline.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _actualizar_selector_pipeline(self):
        self._clases_pipeline = self.repositorio.listar_clases("")
        valores = [
            f"{c.get('materia', '')} · {c.get('numero', 0):03d} · "
            f"{c.get('titulo', '')}"
            for c in self._clases_pipeline
        ] or ["Sin clases guardadas"]
        self.selector_pipeline.configure(values=valores)
        self.selector_pipeline.set(valores[0])

    def _clase_pipeline_seleccionada(self):
        if not self._clases_pipeline:
            return None
        valores = list(self.selector_pipeline.cget("values"))
        try:
            indice = valores.index(self.selector_pipeline.get())
        except ValueError:
            return None
        if indice >= len(self._clases_pipeline):
            return None
        return self._clases_pipeline[indice]

    def _reprocesar_clase(self):
        clase = self._clase_pipeline_seleccionada()
        if not clase:
            messagebox.showwarning("ARGOS", "Selecciona una clase válida.")
            return
        self.salida_pipeline.delete("1.0", "end")
        self._encolar_pipeline(clase["ruta"], automatico=False)

    def _mostrar_resumen_pipeline(self, ruta: str, resultado: dict):
        indice = resultado.get("indice", {})
        lineas = [
            f"Clase: {Path(ruta).name}",
            f"Fuente utilizada: {resultado.get('archivo_fuente', '')}",
            "",
            f"Bloques temáticos: {resultado.get('bloques', 0)}",
            f"Avisos de examen: {resultado.get('avisos', 0)}",
            f"Preguntas: {resultado.get('preguntas', 0)}",
            f"Correcciones médicas: {resultado.get('correcciones', 0)}",
            f"Flashcards: {resultado.get('flashcards', 0)}",
            f"Referencias locales: {resultado.get('referencias', 0)}",
            f"Bloques indexados: {indice.get('bloques', 0)}",
            "",
            "El detalle de cada etapa está en estado_argos.json.",
        ]
        self.salida_pipeline.delete("1.0", "end")
        self.salida_pipeline.insert("end", "\n".join(lineas))

    def _crear_tab_chat(self):
        superior = ctk.CTkFrame(self.tab_chat)
        superior.pack(fill="x", padx=14, pady=14)
        self.pregunta_argos = ctk.CTkEntry(
            superior,
            placeholder_text="Pregunta a tus clases, apuntes y tratados...",
        )
        self.pregunta_argos.pack(
            side="left", fill="x", expand=True, padx=(12, 6), pady=12
        )
        self.pregunta_argos.bind("<Return>", lambda _e: self._preguntar_argos())
        self.alcance_chat = ctk.CTkComboBox(
            superior,
            values=[
                "Todo",
                "Clases",
                "Biblioteca médica",
                "Tratados",
                "Apuntes",
                "Exámenes",
                "Artículos",
                "Otros",
            ],
            width=165,
        )
        self.alcance_chat.set("Todo")
        self.alcance_chat.pack(side="left", padx=6)
        ctk.CTkButton(
            superior,
            text="Preguntar",
            command=self._preguntar_argos,
            width=95,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            superior,
            text="Actualizar índice",
            command=self._reconstruir_indice,
            width=125,
        ).pack(side="left", padx=(0, 12))

        self.estado_chat = ctk.CTkLabel(
            self.tab_chat,
            text="Índice sin comprobar.",
            anchor="w",
            text_color="#aaaaaa",
        )
        self.estado_chat.pack(fill="x", padx=18, pady=(0, 8))
        self.respuesta_chat = ctk.CTkTextbox(
            self.tab_chat, font=ctk.CTkFont(size=13)
        )
        self.respuesta_chat.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.fuentes_chat = ctk.CTkScrollableFrame(self.tab_chat, height=175)
        self.fuentes_chat.pack(fill="x", padx=14, pady=(0, 14))

    def _actualizar_estado_indice(self):
        try:
            stats = self.indice_fts.estadisticas()
            self.estado_chat.configure(
                text=(
                    f"Índice FTS5: {stats['bloques']} bloques · "
                    f"{stats['clases']} de clases · "
                    f"{stats['documentos']} documentales"
                )
            )
        except Exception as exc:
            self.estado_chat.configure(text=f"Índice no disponible: {exc}")

    def _reconstruir_indice(self):
        if self._indice_pendiente:
            messagebox.showwarning(
                "Índice ARGOS",
                "La actualización del índice ya está en la cola.",
            )
            return
        self._indice_pendiente = True
        self._cola_pipeline.put({"tipo": "indice"})
        posicion = self._cola_pipeline.qsize()
        self.estado_chat.configure(
            text=f"Actualización añadida a la cola. Posición: {posicion}."
        )

    def _preguntar_argos(self):
        pregunta = self.pregunta_argos.get().strip()
        if len(pregunta) < 3:
            self.estado_chat.configure(text="Escribe una pregunta más concreta.")
            return
        self.respuesta_chat.delete("1.0", "end")
        for widget in self.fuentes_chat.winfo_children():
            widget.destroy()
        self.estado_chat.configure(text="Consultando el único índice FTS5...")

        def worker():
            try:
                respuesta = self.chat_argos.preguntar(
                    pregunta,
                    alcance=self.alcance_chat.get(),
                    limite_fuentes=10,
                )
                self.after(0, self._mostrar_respuesta, respuesta)
            except Exception as exc:
                self.after(0, messagebox.showerror, "Chat ARGOS", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_respuesta(self, respuesta):
        self.respuesta_chat.insert("end", respuesta.respuesta)
        self.estado_chat.configure(
            text=f"Respuesta documental basada en {len(respuesta.fuentes)} fuentes."
        )
        for numero, fuente in enumerate(respuesta.fuentes, 1):
            fila = ctk.CTkFrame(self.fuentes_chat)
            fila.pack(fill="x", pady=3)
            ctk.CTkLabel(
                fila,
                text=(
                    f"[{numero}] {fuente.categoria} · {fuente.titulo} · "
                    f"{fuente.ubicacion}"
                ),
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=10, pady=8)
            ctk.CTkButton(
                fila,
                text="Abrir",
                width=70,
                command=lambda r=fuente.ruta: self._abrir_fuente(r),
            ).pack(side="right", padx=8)

    @staticmethod
    def _abrir_fuente(ruta):
        if ruta and (os.path.isfile(ruta) or os.path.isdir(ruta)):
            os.startfile(ruta)


def _ruta_bloqueo_instancia() -> Path:
    documentos = Path(
        os.environ.get("USERPROFILE", str(Path.home()))
    ) / "Documents"
    return documentos / "Asistente de Clases" / ".argos_instancia.lock"


def _mostrar_aviso_instancia(mensaje: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, mensaje, "ARGOS", 0x30)
    else:
        print(mensaje)


def ejecutar_argos() -> int:
    """Punto de entrada único; garantiza una sola ventana y una sola cola."""
    bloqueo = BloqueoArchivo(
        _ruta_bloqueo_instancia(),
        caducidad_horas=24,
        mensaje_ocupado=(
            "ARGOS ya está abierto. Usa la ventana existente para mantener "
            "una única cola de procesamiento."
        ),
    )
    try:
        with bloqueo:
            app = ArgosApp()
            app.mainloop()
    except BloqueoOcupadoError as exc:
        _mostrar_aviso_instancia(str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(ejecutar_argos())
