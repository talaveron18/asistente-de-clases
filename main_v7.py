from __future__ import annotations

import os
import threading

import customtkinter as ctk
from tkinter import messagebox

from enriquecedor_argos import procesar_bloque_medico_completo
from main_v6 import ArgosV6App


class ArgosV7App(ArgosV6App):
    """ARGOS para clases con revisión médica conservadora y referencias locales."""

    def __init__(self):
        super().__init__()
        self.title("ARGOS · Medicina y Reuniones · v7")
        self.tab_revision_medica = self.tabs.add("Revisión médica")
        self._tab_revision_medica()

    def _tab_revision_medica(self):
        panel = ctk.CTkFrame(self.tab_revision_medica)
        panel.pack(fill="x", padx=14, pady=14)
        ctk.CTkLabel(
            panel,
            text="Revisión médica y referencias",
            font=ctk.CTkFont(size=19, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ctk.CTkLabel(
            panel,
            text=(
                "Corrige únicamente términos médicos incluidos en un glosario validado y "
                "añade referencias de tratados, apuntes y otros documentos locales. "
                "Cada cambio queda registrado para revisión."
            ),
            anchor="w",
            justify="left",
            wraplength=930,
            text_color="#aaaaaa",
        ).pack(fill="x", padx=14, pady=(0, 12))

        fila = ctk.CTkFrame(panel, fg_color="transparent")
        fila.pack(fill="x", padx=14, pady=(0, 14))
        self.clase_revision = ctk.CTkComboBox(
            fila, values=self._opciones_revision(), width=620
        )
        self.clase_revision.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            fila, text="Actualizar", command=self._actualizar_revision, width=90
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            fila,
            text="Revisar y enriquecer",
            command=self._ejecutar_revision_medica,
            width=155,
        ).pack(side="left")

        self.estado_revision = ctk.CTkLabel(
            self.tab_revision_medica,
            text="Selecciona una clase ya procesada.",
            anchor="w",
        )
        self.estado_revision.pack(fill="x", padx=18, pady=(0, 8))
        self.salida_revision = ctk.CTkTextbox(
            self.tab_revision_medica, font=ctk.CTkFont(size=13)
        )
        self.salida_revision.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _opciones_revision(self):
        opciones = []
        for clase in self.repositorio.listar_clases(""):
            opciones.append(
                f"{clase.get('materia', '')} | {clase.get('titulo', '')} | {clase.get('ruta', '')}"
            )
        return opciones or ["Sin clases guardadas"]

    def _actualizar_revision(self):
        valores = self._opciones_revision()
        self.clase_revision.configure(values=valores)
        self.clase_revision.set(valores[0])

    def _ruta_revision(self):
        valor = self.clase_revision.get()
        if " | " not in valor:
            return None
        return valor.split(" | ", 2)[-1]

    def _ejecutar_revision_medica(self):
        ruta = self._ruta_revision()
        if not ruta or not os.path.isdir(ruta):
            messagebox.showwarning("Revisión médica", "Selecciona una clase válida.")
            return
        self.estado_revision.configure(text="Revisando términos y buscando referencias...")
        self.salida_revision.delete("1.0", "end")

        def worker():
            try:
                resultado = procesar_bloque_medico_completo(ruta)
                self.after(0, self._mostrar_revision_medica, ruta, resultado)
            except Exception as exc:
                self.after(0, self.estado_revision.configure, {"text": f"Error: {exc}"})
                self.after(0, messagebox.showerror, "Revisión médica", str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_revision_medica(self, ruta, resultado):
        lineas = [
            "REVISIÓN MÉDICA COMPLETADA",
            "",
            f"Correcciones de alta confianza: {resultado.get('correcciones', 0)}",
            f"Bloques procesados: {resultado.get('bloques', 0)}",
            f"Referencias locales añadidas: {resultado.get('referencias', 0)}",
            "",
            "ARCHIVOS GENERADOS:",
        ]
        lineas.extend(f"• {x}" for x in resultado.get("archivos", []))
        lineas += [
            "",
            "Regla de seguridad:",
            "• Las correcciones no sustituyen revisión humana.",
            "• Las referencias deben comprobarse en la página original.",
            "• ARGOS no añade afirmaciones médicas sin fuente local.",
        ]
        self.salida_revision.insert("end", "\n".join(lineas))
        self.estado_revision.configure(text=f"Revisión completada: {ruta}")
        messagebox.showinfo(
            "ARGOS",
            "Revisión médica y enriquecimiento terminados.\n"
            "Consulta los archivos generados dentro de la carpeta de la clase.",
        )


if __name__ == "__main__":
    ArgosV7App().mainloop()
