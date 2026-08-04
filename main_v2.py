from __future__ import annotations

import os
import threading

import customtkinter as ctk

from buscador_conocimiento import BuscadorConocimiento
from main import AsistenteClasesApp


class ArgosApp(AsistenteClasesApp):
    """Versión ampliada con buscador unificado de conocimiento."""

    def __init__(self):
        super().__init__()
        self.buscador_conocimiento = BuscadorConocimiento()
        self.tab_buscar = self.tabs.add("Buscar")
        self._tab_busqueda_unificada()

    def _tab_busqueda_unificada(self):
        superior = ctk.CTkFrame(self.tab_buscar)
        superior.pack(fill="x", padx=14, pady=14)

        self.consulta_global = ctk.CTkEntry(
            superior,
            placeholder_text="Buscar un concepto en clases, tratados, apuntes y exámenes...",
        )
        self.consulta_global.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=12)
        self.consulta_global.bind("<Return>", lambda _e: self._buscar_conocimiento())

        self.alcance_busqueda = ctk.CTkComboBox(
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
        self.alcance_busqueda.set("Todo")
        self.alcance_busqueda.pack(side="left", padx=6)

        ctk.CTkButton(
            superior,
            text="Buscar",
            command=self._buscar_conocimiento,
            width=90,
        ).pack(side="left", padx=(6, 12))

        self.estado_busqueda = ctk.CTkLabel(
            self.tab_buscar,
            text="Escribe al menos dos caracteres.",
            anchor="w",
            text_color="#aaaaaa",
        )
        self.estado_busqueda.pack(fill="x", padx=18, pady=(0, 8))

        self.resultados_busqueda = ctk.CTkScrollableFrame(self.tab_buscar)
        self.resultados_busqueda.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def _buscar_conocimiento(self):
        consulta = self.consulta_global.get().strip()
        if len(consulta) < 2:
            self.estado_busqueda.configure(text="Escribe al menos dos caracteres.")
            return
        alcance = self.alcance_busqueda.get()
        self.estado_busqueda.configure(text="Buscando...")
        for widget in self.resultados_busqueda.winfo_children():
            widget.destroy()

        def worker():
            resultados = self.buscador_conocimiento.buscar(consulta, alcance, limite=150)
            self.after(0, self._mostrar_busqueda, consulta, resultados)

        threading.Thread(target=worker, daemon=True).start()

    def _mostrar_busqueda(self, consulta, resultados):
        self.estado_busqueda.configure(
            text=f"{len(resultados)} coincidencias para «{consulta}»."
        )
        if not resultados:
            ctk.CTkLabel(
                self.resultados_busqueda,
                text="No se encontraron coincidencias literales.",
            ).pack(pady=30)
            return

        for resultado in resultados:
            tarjeta = ctk.CTkFrame(self.resultados_busqueda)
            tarjeta.pack(fill="x", pady=5)

            cabecera = ctk.CTkFrame(tarjeta, fg_color="transparent")
            cabecera.pack(fill="x", padx=12, pady=(9, 2))
            ctk.CTkLabel(
                cabecera,
                text=f"{resultado.tipo_fuente} · {resultado.titulo}",
                anchor="w",
                font=ctk.CTkFont(weight="bold"),
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(
                cabecera,
                text=resultado.ubicacion,
                text_color="#90caf9",
            ).pack(side="right", padx=(12, 0))

            ctk.CTkLabel(
                tarjeta,
                text=resultado.fragmento,
                anchor="w",
                justify="left",
                wraplength=900,
            ).pack(fill="x", padx=12, pady=(2, 8))

            ctk.CTkButton(
                tarjeta,
                text="Abrir fuente",
                width=105,
                command=lambda r=resultado.ruta: self._abrir_resultado(r),
            ).pack(anchor="e", padx=12, pady=(0, 10))

    @staticmethod
    def _abrir_resultado(ruta: str):
        if not ruta:
            return
        if os.path.isdir(ruta):
            os.startfile(ruta)
        elif os.path.isfile(ruta):
            os.startfile(ruta)


if __name__ == "__main__":
    ArgosApp().mainloop()
