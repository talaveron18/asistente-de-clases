from __future__ import annotations

import os
import threading
from pathlib import Path

import customtkinter as ctk

from analizador_clase import AnalizadorClase
from main_v3 import ArgosV3App


class ArgosV4App(ArgosV3App):
    """ARGOS centrado en clases: análisis temporal, examen y preguntas."""

    def __init__(self):
        super().__init__()
        self.analizador_clase = AnalizadorClase()
        self.clases_disponibles = []
        self.tab_analisis = self.tabs.add("Análisis de clase")
        self._tab_analisis_clase()
        self._cargar_clases_analisis()

    def _tab_analisis_clase(self):
        superior = ctk.CTkFrame(self.tab_analisis)
        superior.pack(fill="x", padx=14, pady=14)

        ctk.CTkLabel(
            superior,
            text="Clase",
            font=ctk.CTkFont(weight="bold"),
        ).pack(side="left", padx=(12, 6), pady=12)

        self.selector_clase_analisis = ctk.CTkComboBox(superior, values=["Sin clases"], width=520)
        self.selector_clase_analisis.pack(side="left", padx=6)

        ctk.CTkButton(
            superior,
            text="Actualizar lista",
            command=self._cargar_clases_analisis,
            width=110,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            superior,
            text="Analizar clase",
            command=self._analizar_clase_seleccionada,
            width=120,
        ).pack(side="left", padx=(6, 12))

        self.estado_analisis = ctk.CTkLabel(
            self.tab_analisis,
            text="Selecciona una clase transcrita.",
            anchor="w",
            text_color="#aaaaaa",
        )
        self.estado_analisis.pack(fill="x", padx=18, pady=(0, 8))

        self.resultado_analisis = ctk.CTkTextbox(self.tab_analisis, font=ctk.CTkFont(size=13))
        self.resultado_analisis.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        self.resultado_analisis.insert(
            "end",
            "Este análisis detecta:\n\n"
            "• cambios de tema y posible índice temporal\n"
            "• avisos como «esto entra», «muy importante» o «puede caer»\n"
            "• preguntas formuladas durante la clase\n\n"
            "Cada hallazgo conserva su minuto exacto.\n",
        )

        acciones = ctk.CTkFrame(self.tab_analisis, fg_color="transparent")
        acciones.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(
            acciones,
            text="Abrir carpeta de la clase",
            command=self._abrir_carpeta_clase_analisis,
            width=170,
        ).pack(side="right")

    def _cargar_clases_analisis(self):
        self.clases_disponibles = self.repositorio.listar_clases("")
        valores = []
        for clase in self.clases_disponibles:
            valores.append(
                f"{clase.get('materia', '')} · {clase.get('numero', 0):03d} · {clase.get('titulo', '')}"
            )
        if not valores:
            valores = ["Sin clases"]
        self.selector_clase_analisis.configure(values=valores)
        self.selector_clase_analisis.set(valores[0])
        self.estado_analisis.configure(text=f"{len(self.clases_disponibles)} clases disponibles.")

    def _clase_seleccionada(self):
        if not self.clases_disponibles:
            return None
        indice = self.selector_clase_analisis.cget("values").index(self.selector_clase_analisis.get())
        if indice < 0 or indice >= len(self.clases_disponibles):
            return None
        return self.clases_disponibles[indice]

    def _analizar_clase_seleccionada(self):
        clase = self._clase_seleccionada()
        if not clase:
            self.estado_analisis.configure(text="No hay ninguna clase disponible para analizar.")
            return
        self.estado_analisis.configure(text="Analizando transcripción...")
        self.resultado_analisis.delete("1.0", "end")

        def worker():
            try:
                resultado = self.analizador_clase.analizar_carpeta(clase["ruta"])
                self.after(0, self._mostrar_analisis_clase, resultado)
            except Exception as exc:
                self.after(0, self.estado_analisis.configure, {"text": f"Error: {exc}"})

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_analisis_clase(self, resultado):
        lineas = [
            f"MATERIA: {resultado.get('materia', '')}",
            f"CLASE: {resultado.get('titulo', '')}",
            "",
            "ÍNDICE TEMPORAL",
        ]
        indice = resultado.get("indice_temporal", [])
        if indice:
            lineas.extend(f"[{x['tiempo']}] {x['descripcion']}" for x in indice)
        else:
            lineas.append("No se detectaron cambios de tema explícitos.")

        lineas.extend(["", "AVISOS DE EXAMEN"])
        avisos = resultado.get("avisos_examen", [])
        if avisos:
            lineas.extend(f"[{x['tiempo']}] {x['texto']}" for x in avisos)
        else:
            lineas.append("No se detectaron avisos explícitos.")

        lineas.extend(["", "PREGUNTAS DETECTADAS"])
        preguntas = resultado.get("preguntas", [])
        if preguntas:
            lineas.extend(f"[{x['tiempo']}] {x['texto']}" for x in preguntas)
        else:
            lineas.append("No se detectaron preguntas.")

        self.resultado_analisis.delete("1.0", "end")
        self.resultado_analisis.insert("end", "\n".join(lineas))
        self.estado_analisis.configure(
            text=(
                f"Análisis guardado: {len(indice)} temas, "
                f"{len(avisos)} avisos y {len(preguntas)} preguntas."
            )
        )

    def _abrir_carpeta_clase_analisis(self):
        clase = self._clase_seleccionada()
        if clase and os.path.isdir(clase.get("ruta", "")):
            os.startfile(clase["ruta"])


if __name__ == "__main__":
    ArgosV4App().mainloop()
