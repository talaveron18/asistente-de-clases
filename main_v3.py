from __future__ import annotations

import os
import threading

import customtkinter as ctk

from chat_argos import ChatArgos
from indice_sqlite import IndiceConocimientoSQLite
from main_v2 import ArgosApp


class ArgosV3App(ArgosApp):
    """ARGOS con índice SQLite FTS5 y chat documental con fuentes."""

    def __init__(self):
        super().__init__()
        self.indice_fts = IndiceConocimientoSQLite()
        self.chat_argos = ChatArgos(self.indice_fts)
        self.tab_indice = self.tabs.add("Índice")
        self.tab_chat = self.tabs.add("Chat ARGOS")
        self._tab_indice_fts()
        self._tab_chat_argos()
        self._actualizar_estadisticas_indice()

    def _tab_indice_fts(self):
        panel = ctk.CTkFrame(self.tab_indice)
        panel.pack(fill="x", padx=14, pady=14)
        ctk.CTkLabel(
            panel,
            text="Índice rápido SQLite FTS5",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            panel,
            text=(
                "Reconstruye este índice después de importar libros, extraer PDFs "
                "o añadir nuevas clases. No modifica los archivos originales."
            ),
            anchor="w",
            justify="left",
            wraplength=900,
            text_color="#aaaaaa",
        ).pack(fill="x", padx=14, pady=(0, 12))
        fila = ctk.CTkFrame(panel, fg_color="transparent")
        fila.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(
            fila,
            text="Reconstruir índice",
            command=self._reconstruir_indice,
            width=160,
        ).pack(side="left")
        self.progreso_indice = ctk.CTkProgressBar(fila)
        self.progreso_indice.pack(side="left", fill="x", expand=True, padx=12)
        self.progreso_indice.set(0)
        self.estado_indice = ctk.CTkLabel(fila, text="Sin comprobar", width=260, anchor="e")
        self.estado_indice.pack(side="right")

        self.info_indice = ctk.CTkTextbox(self.tab_indice, height=360)
        self.info_indice.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.info_indice.insert(
            "end",
            "El índice permite buscar rápidamente entre cientos de clases y tratados.\n\n"
            "Cada fila conserva:\n"
            "• tipo de fuente\n• categoría\n• materia\n• título\n"
            "• página o minuto\n• ruta original\n• fragmento textual\n",
        )
        self.info_indice.configure(state="disabled")

    def _actualizar_estadisticas_indice(self):
        try:
            stats = self.indice_fts.estadisticas()
            self.estado_indice.configure(
                text=(
                    f"{stats['bloques']} bloques · "
                    f"{stats['clases']} de clases · {stats['documentos']} documentales"
                )
            )
        except Exception as exc:
            self.estado_indice.configure(text=f"Índice no disponible: {exc}")

    def _reconstruir_indice(self):
        self.estado_indice.configure(text="Preparando índice...")
        self.progreso_indice.set(0)

        def callback(msg, valor):
            self.after(0, self.estado_indice.configure, {"text": msg})
            self.after(0, self.progreso_indice.set, valor)

        def worker():
            try:
                stats = self.indice_fts.reconstruir(callback)
                texto = (
                    f"Índice listo: {stats['bloques']} bloques, "
                    f"{stats['clases']} intervenciones de clase y "
                    f"{stats['documentos']} páginas documentales."
                )
                self.after(0, self.estado_indice.configure, {"text": texto})
                self.after(0, self.progreso_indice.set, 1)
                self.after(0, self._actualizar_estadisticas_indice)
            except Exception as exc:
                self.after(0, self.estado_indice.configure, {"text": f"Error: {exc}"})
                self.after(0, self.progreso_indice.set, 0)

        threading.Thread(target=worker, daemon=True).start()

    def _tab_chat_argos(self):
        superior = ctk.CTkFrame(self.tab_chat)
        superior.pack(fill="x", padx=14, pady=14)
        self.pregunta_argos = ctk.CTkEntry(
            superior,
            placeholder_text="Pregunta a tus clases, apuntes y tratados...",
        )
        self.pregunta_argos.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=12)
        self.pregunta_argos.bind("<Return>", lambda _e: self._preguntar_argos())
        self.alcance_chat = ctk.CTkComboBox(
            superior,
            values=[
                "Todo", "Clases", "Biblioteca médica", "Tratados",
                "Apuntes", "Exámenes", "Artículos", "Otros",
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
        ).pack(side="left", padx=(6, 12))

        self.estado_chat = ctk.CTkLabel(
            self.tab_chat,
            text="Modo documental: responde únicamente con fuentes locales indexadas.",
            anchor="w",
            text_color="#aaaaaa",
        )
        self.estado_chat.pack(fill="x", padx=18, pady=(0, 8))

        self.respuesta_chat = ctk.CTkTextbox(self.tab_chat, font=ctk.CTkFont(size=13))
        self.respuesta_chat.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.respuesta_chat.insert(
            "end",
            "Primero reconstruye el índice. Después puedes preguntar, por ejemplo:\n\n"
            "• ¿Qué dijeron sobre shock séptico?\n"
            "• ¿Dónde aparece la insuficiencia cardíaca?\n"
            "• Busca criterios diagnósticos de endocarditis.\n",
        )

        self.fuentes_chat = ctk.CTkScrollableFrame(self.tab_chat, height=180)
        self.fuentes_chat.pack(fill="x", padx=14, pady=(0, 14))

    def _preguntar_argos(self):
        pregunta = self.pregunta_argos.get().strip()
        if len(pregunta) < 3:
            self.estado_chat.configure(text="Escribe una pregunta de al menos tres caracteres.")
            return
        self.estado_chat.configure(text="Consultando el índice local...")
        self.respuesta_chat.delete("1.0", "end")
        for widget in self.fuentes_chat.winfo_children():
            widget.destroy()

        def worker():
            respuesta = self.chat_argos.preguntar(
                pregunta,
                alcance=self.alcance_chat.get(),
                limite_fuentes=10,
            )
            self.after(0, self._mostrar_respuesta_argos, respuesta)

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_respuesta_argos(self, respuesta):
        self.respuesta_chat.delete("1.0", "end")
        self.respuesta_chat.insert("end", respuesta.respuesta)
        self.estado_chat.configure(
            text=f"Respuesta documental basada en {len(respuesta.fuentes)} fuentes."
        )
        if not respuesta.fuentes:
            ctk.CTkLabel(
                self.fuentes_chat,
                text="No hay fuentes suficientes. Reconstruye el índice o cambia la consulta.",
            ).pack(pady=20)
            return
        for i, fuente in enumerate(respuesta.fuentes, 1):
            fila = ctk.CTkFrame(self.fuentes_chat)
            fila.pack(fill="x", pady=3)
            etiqueta = f"[{i}] {fuente.categoria} · {fuente.titulo} · {fuente.ubicacion}"
            ctk.CTkLabel(fila, text=etiqueta, anchor="w").pack(
                side="left", fill="x", expand=True, padx=10, pady=8
            )
            ctk.CTkButton(
                fila,
                text="Abrir",
                width=70,
                command=lambda r=fuente.ruta: self._abrir_fuente_chat(r),
            ).pack(side="right", padx=8)

    @staticmethod
    def _abrir_fuente_chat(ruta):
        if ruta and (os.path.isfile(ruta) or os.path.isdir(ruta)):
            os.startfile(ruta)


if __name__ == "__main__":
    ArgosV3App().mainloop()
