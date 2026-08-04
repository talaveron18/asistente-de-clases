from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from indice_sqlite import IndiceConocimientoSQLite
from main_v4 import ArgosV4App
from pipeline_clase import analizar_clase_completa


class ArgosV5App(ArgosV4App):
    """Versión centrada en Medicina y Reuniones con pipeline postclase completo."""

    def __init__(self):
        super().__init__()
        self.title("ARGOS · Medicina y Reuniones")
        self.indice_auto = IndiceConocimientoSQLite()
        self.tab_pipeline = self.tabs.add("Procesar clase")
        self.tab_reuniones = self.tabs.add("Reuniones")
        self._tab_pipeline_clase()
        self._tab_reuniones_simple()

    def _mostrar_resultados(self, caja, segmentos, carpeta):
        """Conserva la salida original y lanza el pipeline completo automáticamente."""
        caja.delete("1.0", "end")
        caja.insert(
            "end",
            "\n".join(s.a_linea_txt() for s in segmentos)
            if segmentos else "No se detectó voz.",
        )
        self.progreso_grabar.set(0)
        self.progreso_archivo.set(0)
        self.estado.configure(text="Transcripción guardada. Generando apuntes ARGOS...")
        self._refrescar_clases()

        def worker():
            try:
                datos = analizar_clase_completa(carpeta)
                self.indice_auto.reconstruir()
                self.after(0, self._actualizar_clases_pipeline)
                self.after(0, self._finalizar_automatico, carpeta, datos)
            except Exception as exc:
                self.after(
                    0,
                    messagebox.showwarning,
                    "Clase guardada con aviso",
                    f"La transcripción se guardó, pero el análisis automático falló:\n{exc}",
                )
                self.after(0, self.estado.configure, {"text": f"Clase guardada; análisis pendiente: {exc}"})

        threading.Thread(target=worker, daemon=True).start()

    def _finalizar_automatico(self, carpeta, datos):
        self.estado.configure(
            text=(
                f"Clase completa: {len(datos.get('bloques', []))} bloques, "
                f"{len(datos.get('avisos_examen', []))} avisos y "
                f"{len(datos.get('preguntas_profesor', []))} preguntas."
            )
        )
        messagebox.showinfo(
            "ARGOS",
            "Clase transcrita, analizada, convertida en apuntes e indexada.\n\n"
            f"Guardada en:\n{carpeta}",
        )

    def _tab_pipeline_clase(self):
        superior = ctk.CTkFrame(self.tab_pipeline)
        superior.pack(fill="x", padx=14, pady=14)
        ctk.CTkLabel(
            superior,
            text="Procesamiento completo de clase",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            superior,
            text=(
                "Las clases nuevas se procesan automáticamente. Esta pantalla permite "
                "reprocesar clases antiguas o regenerar sus apuntes."
            ),
            text_color="#aaaaaa",
            anchor="w",
            justify="left",
            wraplength=930,
        ).pack(fill="x", padx=14, pady=(0, 10))

        fila = ctk.CTkFrame(superior, fg_color="transparent")
        fila.pack(fill="x", padx=14, pady=(0, 14))
        self.clase_pipeline = ctk.CTkComboBox(fila, values=self._opciones_clases_pipeline(), width=560)
        self.clase_pipeline.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(fila, text="Actualizar", command=self._actualizar_clases_pipeline, width=90).pack(side="left", padx=6)
        ctk.CTkButton(fila, text="Reprocesar", command=self._procesar_clase_seleccionada, width=100).pack(side="left")

        self.estado_pipeline = ctk.CTkLabel(self.tab_pipeline, text="Selecciona una clase.", anchor="w")
        self.estado_pipeline.pack(fill="x", padx=18, pady=(0, 8))
        self.salida_pipeline = ctk.CTkTextbox(self.tab_pipeline, font=ctk.CTkFont(size=13))
        self.salida_pipeline.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _opciones_clases_pipeline(self):
        opciones = []
        for clase in self.repositorio.listar_clases():
            opciones.append(f"{clase.get('materia', '')} | {clase.get('titulo', '')} | {clase.get('ruta', '')}")
        return opciones or ["Sin clases guardadas"]

    def _actualizar_clases_pipeline(self):
        valores = self._opciones_clases_pipeline()
        self.clase_pipeline.configure(values=valores)
        self.clase_pipeline.set(valores[0])

    def _ruta_clase_pipeline(self):
        valor = self.clase_pipeline.get()
        if " | " not in valor:
            return None
        return valor.split(" | ", 2)[-1]

    def _procesar_clase_seleccionada(self):
        ruta = self._ruta_clase_pipeline()
        if not ruta or not os.path.isdir(ruta):
            messagebox.showwarning("Clase", "Selecciona una clase válida.")
            return
        self.estado_pipeline.configure(text="Procesando clase...")
        self.salida_pipeline.delete("1.0", "end")

        def worker():
            try:
                datos = analizar_clase_completa(ruta)
                try:
                    self.indice_auto.reconstruir()
                    indice_msg = "Índice actualizado automáticamente."
                except Exception as exc:
                    indice_msg = f"No se pudo actualizar el índice: {exc}"
                self.after(0, self._mostrar_pipeline, datos, ruta, indice_msg)
            except Exception as exc:
                self.after(0, self.estado_pipeline.configure, {"text": f"Error: {exc}"})
                self.after(0, messagebox.showerror, "Procesamiento de clase", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_pipeline(self, datos, ruta, indice_msg):
        bloques = datos.get("bloques", [])
        avisos = datos.get("avisos_examen", [])
        preguntas = datos.get("preguntas_profesor", [])
        resumen = [
            f"Clase: {datos.get('materia')} · {datos.get('titulo')}",
            f"Bloques temáticos: {len(bloques)}",
            f"Avisos de examen: {len(avisos)}",
            f"Preguntas detectadas: {len(preguntas)}",
            indice_msg,
            "",
            "ARCHIVOS GENERADOS:",
            "• transcripcion_limpia.txt",
            "• pipeline_clase.json",
            "• apuntes_argos.md",
            "",
        ]
        for bloque in bloques:
            resumen.append(f"[{bloque['inicio']}–{bloque['fin']}] {bloque['titulo']}")
            resumen.append(f"  {bloque['resumen'][:450]}")
            resumen.append("")
        self.salida_pipeline.insert("end", "\n".join(resumen))
        self.estado_pipeline.configure(text=f"Clase procesada correctamente: {ruta}")
        messagebox.showinfo("ARGOS", "La clase se ha procesado y los apuntes ARGOS están listos.")

    def _tab_reuniones_simple(self):
        panel = ctk.CTkFrame(self.tab_reuniones)
        panel.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(
            panel,
            text="Modo Reuniones",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(16, 6))
        ctk.CTkLabel(
            panel,
            text=(
                "Las reuniones utilizarán el mismo motor de grabación y transcripción, "
                "pero se guardarán separadas de Medicina."
            ),
            justify="left",
            anchor="w",
            wraplength=900,
            text_color="#aaaaaa",
        ).pack(fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            panel,
            text="Abrir carpeta de reuniones",
            command=self._abrir_carpeta_reuniones,
            width=220,
        ).pack(anchor="w", padx=16)

    @staticmethod
    def _abrir_carpeta_reuniones():
        ruta = Path.home() / "Documents" / "ARGOS Reuniones"
        ruta.mkdir(parents=True, exist_ok=True)
        os.startfile(ruta)


if __name__ == "__main__":
    ArgosV5App().mainloop()
