from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from chat_argos import ChatArgos
from correccion_medica import corregir_archivo_transcripcion
from enriquecedor_argos import enriquecer_clase_con_fuentes
from indice_sqlite import IndiceConocimientoSQLite
from main import AsistenteClasesApp
from material_estudio import generar_material_estudio
from pipeline_clase import analizar_clase_completa


class ArgosApp(AsistenteClasesApp):
    """Único punto de entrada de ARGOS.

    Reutiliza el núcleo estable de grabación/biblioteca de ``main.py`` y añade
    el procesamiento de estudio y el chat sin la cadena main_v2...main_v7.
    """

    def __init__(self):
        super().__init__()
        self.title("ARGOS · Clases de Medicina")
        self.indice_fts = IndiceConocimientoSQLite(str(self.repositorio.raiz))
        self.chat_argos = ChatArgos(self.indice_fts)
        self._pipeline_activo = False
        self._clases_pipeline: list[dict] = []

        self.tab_pipeline = self.tabs.add("Procesar clase")
        self.tab_chat = self.tabs.add("Chat ARGOS")
        self._crear_tab_pipeline()
        self._crear_tab_chat()
        self._actualizar_selector_pipeline()
        self._actualizar_estado_indice()

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
        self.estado.configure(text="Transcripción guardada. Procesando la clase...")
        self._refrescar_clases()
        self._pipeline_activo = True

        def worker():
            try:
                resultado = self._procesar_clase_completa(carpeta)
                self.after(0, self._finalizar_clase, carpeta, resultado)
            except Exception as exc:
                self.after(0, messagebox.showwarning, "Clase guardada con aviso", str(exc))
                self.after(
                    0,
                    self.estado.configure,
                    {"text": f"Clase guardada; procesamiento pendiente: {exc}"},
                )
            finally:
                self._pipeline_activo = False

        threading.Thread(target=worker, daemon=True).start()

    def _procesar_clase_completa(self, carpeta: str | Path) -> dict:
        """Una sola cadena: análisis, revisión, materiales, fuentes e índice."""
        carpeta = Path(carpeta)
        analizar_clase_completa(carpeta)
        correcciones = corregir_archivo_transcripcion(carpeta)
        datos = analizar_clase_completa(carpeta)
        material = generar_material_estudio(carpeta)
        enriquecido = enriquecer_clase_con_fuentes(carpeta)
        indice = self.indice_fts.reconstruir()

        return {
            "bloques": len(datos.get("bloques", [])),
            "avisos": len(datos.get("avisos_examen", [])),
            "preguntas": len(datos.get("preguntas_profesor", [])),
            "correcciones": correcciones.get("total_cambios", 0),
            "flashcards": material.get("flashcards", 0),
            "referencias": sum(
                len(b.get("referencias_locales", []))
                for b in enriquecido.get("bloques", [])
            ),
            "indice": indice,
        }

    def _finalizar_clase(self, carpeta, resultado):
        self.estado.configure(text=f"Clase completa: {carpeta}")
        self._actualizar_selector_pipeline()
        self._actualizar_estado_indice()
        messagebox.showinfo(
            "ARGOS",
            "Clase transcrita y procesada.\n\n"
            f"Bloques: {resultado['bloques']}\n"
            f"Avisos de examen: {resultado['avisos']}\n"
            f"Preguntas: {resultado['preguntas']}\n"
            f"Correcciones médicas: {resultado['correcciones']}\n"
            f"Flashcards: {resultado['flashcards']}\n"
            f"Referencias locales: {resultado['referencias']}\n\n"
            f"Carpeta:\n{carpeta}",
        )

    def _crear_tab_pipeline(self):
        panel = ctk.CTkFrame(self.tab_pipeline)
        panel.pack(fill="x", padx=14, pady=14)
        ctk.CTkLabel(
            panel,
            text="Pipeline completo de clase",
            font=ctk.CTkFont(size=19, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            panel,
            text=(
                "Reprocesa de forma secuencial: análisis, corrección médica, "
                "apuntes, flashcards, referencias locales e índice."
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
        self.estado_pipeline.pack(fill="x", padx=18, pady=(0, 8))
        self.salida_pipeline = ctk.CTkTextbox(
            self.tab_pipeline, font=ctk.CTkFont(size=13)
        )
        self.salida_pipeline.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _actualizar_selector_pipeline(self):
        self._clases_pipeline = self.repositorio.listar_clases("")
        valores = [
            f"{c.get('materia', '')} · {c.get('numero', 0):03d} · {c.get('titulo', '')}"
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
        return self._clases_pipeline[indice] if indice < len(self._clases_pipeline) else None

    def _reprocesar_clase(self):
        if self._pipeline_activo:
            messagebox.showwarning("ARGOS", "Ya hay una clase procesándose.")
            return
        clase = self._clase_pipeline_seleccionada()
        if not clase:
            messagebox.showwarning("ARGOS", "Selecciona una clase válida.")
            return

        self._pipeline_activo = True
        self.btn_reprocesar.configure(state="disabled")
        self.estado_pipeline.configure(text="Procesando clase...")
        self.salida_pipeline.delete("1.0", "end")

        def worker():
            try:
                resultado = self._procesar_clase_completa(clase["ruta"])
                self.after(0, self._mostrar_reprocesado, clase, resultado)
            except Exception as exc:
                self.after(0, messagebox.showerror, "Procesamiento", str(exc))
                self.after(
                    0, self.estado_pipeline.configure, {"text": f"Error: {exc}"}
                )
            finally:
                self._pipeline_activo = False
                self.after(0, self.btn_reprocesar.configure, {"state": "normal"})

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_reprocesado(self, clase, resultado):
        lineas = [
            f"Clase: {clase.get('materia')} · {clase.get('titulo')}",
            "",
            f"Bloques temáticos: {resultado['bloques']}",
            f"Avisos de examen: {resultado['avisos']}",
            f"Preguntas: {resultado['preguntas']}",
            f"Correcciones médicas: {resultado['correcciones']}",
            f"Flashcards: {resultado['flashcards']}",
            f"Referencias locales: {resultado['referencias']}",
            f"Bloques indexados: {resultado['indice']['bloques']}",
        ]
        self.salida_pipeline.insert("end", "\n".join(lineas))
        self.estado_pipeline.configure(text="Procesamiento completado.")
        self._actualizar_estado_indice()

    def _crear_tab_chat(self):
        superior = ctk.CTkFrame(self.tab_chat)
        superior.pack(fill="x", padx=14, pady=14)
        self.pregunta_argos = ctk.CTkEntry(
            superior, placeholder_text="Pregunta a tus clases, apuntes y tratados..."
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
            superior, text="Preguntar", command=self._preguntar_argos, width=95
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
                    f"Índice local: {stats['bloques']} bloques · "
                    f"{stats['clases']} de clases · {stats['documentos']} documentales"
                )
            )
        except Exception as exc:
            self.estado_chat.configure(text=f"Índice no disponible: {exc}")

    def _reconstruir_indice(self):
        self.estado_chat.configure(text="Reconstruyendo índice...")

        def worker():
            try:
                stats = self.indice_fts.reconstruir()
                self.after(0, self._actualizar_estado_indice)
                self.after(
                    0,
                    messagebox.showinfo,
                    "Índice ARGOS",
                    f"Índice listo: {stats['bloques']} bloques.",
                )
            except Exception as exc:
                self.after(0, messagebox.showerror, "Índice ARGOS", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _preguntar_argos(self):
        pregunta = self.pregunta_argos.get().strip()
        if len(pregunta) < 3:
            self.estado_chat.configure(text="Escribe una pregunta más concreta.")
            return
        self.respuesta_chat.delete("1.0", "end")
        for widget in self.fuentes_chat.winfo_children():
            widget.destroy()
        self.estado_chat.configure(text="Consultando el índice local...")

        def worker():
            try:
                respuesta = self.chat_argos.preguntar(
                    pregunta, alcance=self.alcance_chat.get(), limite_fuentes=10
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
        for i, fuente in enumerate(respuesta.fuentes, 1):
            fila = ctk.CTkFrame(self.fuentes_chat)
            fila.pack(fill="x", pady=3)
            ctk.CTkLabel(
                fila,
                text=f"[{i}] {fuente.categoria} · {fuente.titulo} · {fuente.ubicacion}",
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


if __name__ == "__main__":
    ArgosApp().mainloop()
