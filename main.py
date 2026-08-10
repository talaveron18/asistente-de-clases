from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from tkinter import Menu, filedialog, messagebox, simpledialog

import customtkinter as ctk

from biblioteca_medica import BibliotecaMedica, CATEGORIAS, EXTENSIONES_ADMITIDAS
from config import Config
from grabador import (
    UMBRAL_SENAL_UTIL,
    GrabadorAudio,
    recuperar_audio_interrumpido,
)
from interfaz_argos import (
    COLOR_ACENTO,
    COLOR_ALERTA,
    COLOR_BORDE,
    COLOR_EXITO,
    COLOR_PANEL,
    COLOR_PANEL_SUAVE,
    COLOR_PELIGRO,
    COLOR_TEXTO,
    COLOR_TEXTO_SUAVE,
    NavegacionArgos,
    leer_estado_material_clase,
    leer_material_clase,
    preparar_material_para_lectura,
    tarjeta,
    titulo_seccion,
)
from media_utils import eliminar_temporal, preparar_para_transcripcion, tipo_archivo
from repositorio import RepositorioClases, formatear_transcripcion_continua
from transcriptor import TranscriptorClases
from transcripcion_incremental import ResultadoGrabacion, TranscripcionIncremental
from texto_en_directo import actualizar_texto, copiar_texto, hay_seleccion

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def registrar_diagnostico_arranque(
    etapa: str,
    detalle: str = "",
    progreso: float | None = None,
) -> None:
    """Persiste la última etapa de arranque solo cuando CI la solicita."""
    destino = os.environ.get("ARGOS_MODEL_STATUS_FILE", "").strip()
    if not destino:
        return
    datos = {
        "estado": etapa,
        "detalle": detalle,
        "actualizado": time.time(),
    }
    if progreso is not None:
        datos["progreso"] = max(0.0, min(1.0, float(progreso)))
    ruta = Path(destino)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal.write_text(
            json.dumps(datos, ensure_ascii=False), encoding="utf-8"
        )
        temporal.replace(ruta)
    except OSError:
        pass


class AsistenteClasesApp(ctk.CTk):
    def __init__(self):
        registrar_diagnostico_arranque("creando_ventana")
        super().__init__()
        registrar_diagnostico_arranque("ventana_base_creada")
        self.title("ARGOS · Asistente de Clases")
        self.geometry("1120x790")
        self.minsize(940, 670)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)

        self.config_obj = Config()
        self.repositorio = RepositorioClases()
        self.biblioteca_medica = BibliotecaMedica()
        self.transcriptor = None
        self.grabador = None
        self.ruta_archivo = ""
        self._grabando_desde = 0.0
        self._carpeta_grabacion = None
        self._transcripcion_incremental = None
        self._dispositivo_entrada = None
        self._dispositivos_entrada = []
        self._opciones_microfono = {}
        self._seleccion_microfono_manual = False
        self._prueba_microfono_en_curso = False
        self._deteniendo_grabacion = False
        self._grabacion_pausada = False
        self._cerrando = False
        self._recuperacion_grabaciones_activa = False
        self._recarga_modelos_pendiente = False
        self._carga_modelos_en_curso = False
        self._modelo_grabacion_actual = ""
        self._texto_grabar_renderizado = ""
        self._hilo_ui = threading.get_ident()
        self._cola_ui: queue.SimpleQueue[tuple[object, tuple]] = queue.SimpleQueue()
        self._bucle_ui_after = None
        self._nivel_audio_pendiente: float | None = None
        self._nivel_audio_mostrado = 0.0

        registrar_diagnostico_arranque("creando_interfaz")
        self._crear_interfaz()
        registrar_diagnostico_arranque("interfaz_creada")
        # Tk y CustomTkinter solo se actualizan desde el hilo principal. Los
        # workers publican eventos en una cola que se vacía a ritmo limitado;
        # así el callback de PortAudio no fuerza redibujados concurrentes.
        self._bucle_ui_after = self.after(50, self._procesar_cola_ui)
        self._detectar_hardware_audio_async()
        if self.biblioteca_medica.interrumpidos_recuperados:
            total = self.biblioteca_medica.interrumpidos_recuperados
            self.estado_documentos.configure(
                text=f"{total} extracción interrumpida marcada para reintento"
            )
        registrar_diagnostico_arranque("iniciando_modelos")
        self._cargar_modelos()

    def _crear_interfaz(self):
        registrar_diagnostico_arranque("interfaz_navegacion")
        self.tabs = NavegacionArgos(self)
        registrar_diagnostico_arranque("interfaz_paginas")
        self.tab_inicio = self.tabs.add("Inicio")
        self.tab_grabar = self.tabs.add("Grabar clase")
        self.tab_archivo = self.tabs.add("Importar archivo")
        self.tab_clases = self.tabs.add("Mis clases")
        self.tab_detalle = self.tabs.add("Detalle de clase", visible=False)
        self.tab_medica = self.tabs.add("Biblioteca")
        self.tab_config = self.tabs.add("Configuración")

        registrar_diagnostico_arranque("interfaz_cabecera")
        estado_superior = ctk.CTkFrame(
            self.tabs.cabecera, fg_color="transparent"
        )
        estado_superior.pack(side="right", padx=20, pady=10)
        self.estado_modelos = ctk.CTkLabel(
            estado_superior,
            text="Preparando modelos…",
            text_color=COLOR_ALERTA,
            font=ctk.CTkFont(size=12),
        )
        self.estado_modelos.pack(side="right", padx=(16, 0))
        self.btn_detener = ctk.CTkButton(
            estado_superior,
            text="Detener y guardar",
            command=self._detener_grabacion,
            state="disabled",
            width=132,
            height=34,
            fg_color=COLOR_PELIGRO,
            hover_color="#D84855",
        )
        self.btn_detener.pack(side="right", padx=(12, 0))
        self.btn_pausar = ctk.CTkButton(
            estado_superior,
            text="Pausar",
            command=self._alternar_pausa,
            state="disabled",
            width=92,
            height=34,
            fg_color=COLOR_PANEL_SUAVE,
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.btn_pausar.pack(side="right", padx=(12, 0))
        self.reloj = ctk.CTkLabel(
            estado_superior,
            text="00:00:00",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=17, weight="bold"),
            width=80,
        )
        self.reloj.pack(side="right")
        self.estado_grabacion_global = ctk.CTkLabel(
            estado_superior,
            text="●  Sin grabación",
            text_color=COLOR_TEXTO_SUAVE,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.estado_grabacion_global.pack(side="right", padx=(0, 12))

        registrar_diagnostico_arranque("interfaz_inicio")
        self._tab_inicio()
        registrar_diagnostico_arranque("interfaz_grabacion")
        self._tab_grabacion()
        registrar_diagnostico_arranque("interfaz_importacion")
        self._tab_archivo_multimedia()
        registrar_diagnostico_arranque("interfaz_clases")
        self._tab_biblioteca_clases()
        registrar_diagnostico_arranque("interfaz_detalle")
        self._tab_detalle_clase()
        registrar_diagnostico_arranque("interfaz_biblioteca")
        self._tab_biblioteca_medica()
        registrar_diagnostico_arranque("interfaz_configuracion")
        self._tab_configuracion()

        registrar_diagnostico_arranque("interfaz_pie")
        self.estado = ctk.CTkLabel(
            self.tabs.menu_pie,
            text="Inicializando…",
            anchor="w",
            justify="left",
            wraplength=185,
            text_color=COLOR_TEXTO_SUAVE,
            font=ctk.CTkFont(size=11),
        )
        self.estado.pack(side="bottom", fill="x", padx=8, pady=(12, 4))
        self.tabs.set("Inicio")

    def _tab_inicio(self):
        titulo_seccion(
            self.tab_inicio,
            "Tu estudio, en un solo lugar",
            "Graba una clase o importa una grabación. ARGOS conservará el audio, "
            "transcribirá en directo y organizará el material automáticamente.",
        )

        acciones = ctk.CTkFrame(self.tab_inicio, fg_color="transparent")
        acciones.pack(fill="x", padx=24, pady=(2, 18))
        acciones.grid_columnconfigure(0, weight=1)
        acciones.grid_columnconfigure(1, weight=1)

        grabar = tarjeta(acciones)
        grabar.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(
            grabar,
            text="Grabar una clase",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            grabar,
            text="Transcripción y guardado automáticos mientras escuchas.",
            text_color=COLOR_TEXTO_SUAVE,
            anchor="w",
        ).pack(fill="x", padx=18)
        ctk.CTkButton(
            grabar,
            text="Empezar a grabar",
            command=lambda: self.tabs.set("Grabar clase"),
            fg_color=COLOR_ACENTO,
            height=38,
        ).pack(anchor="w", padx=18, pady=18)

        importar = tarjeta(acciones)
        importar.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(
            importar,
            text="Importar audio o vídeo",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(18, 4))
        ctk.CTkLabel(
            importar,
            text="Convierte una clase ya grabada en material de estudio.",
            text_color=COLOR_TEXTO_SUAVE,
            anchor="w",
        ).pack(fill="x", padx=18)
        ctk.CTkButton(
            importar,
            text="Subir archivo",
            command=self._abrir_importador_desde_inicio,
            fg_color=COLOR_PANEL_SUAVE,
            border_width=1,
            border_color=COLOR_BORDE,
            height=38,
        ).pack(anchor="w", padx=18, pady=18)

        recientes = tarjeta(self.tab_inicio)
        recientes.pack(fill="both", expand=True, padx=24, pady=(0, 22))
        cabecera = ctk.CTkFrame(recientes, fg_color="transparent")
        cabecera.pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkLabel(
            cabecera,
            text="Clases recientes",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            cabecera,
            text="Ver todas",
            command=lambda: self.tabs.set("Mis clases"),
            width=84,
            height=30,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDE,
        ).pack(side="right")
        self.lista_inicio = ctk.CTkFrame(recientes, fg_color="transparent")
        self.lista_inicio.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        self._refrescar_inicio()

    def _campos_clase(self, parent):
        marco = tarjeta(parent)
        marco.pack(fill="x", padx=24, pady=(0, 12))
        ctk.CTkLabel(
            marco, text="Materia", text_color=COLOR_TEXTO_SUAVE
        ).grid(row=0, column=0, padx=(16, 6), pady=14)
        materia = ctk.CTkComboBox(marco, values=self.repositorio.materias() or [""], width=260)
        materia.grid(row=0, column=1, padx=6, pady=14, sticky="ew")
        materia.set(self.config_obj.ultima_materia or "")
        ctk.CTkLabel(
            marco, text="Título", text_color=COLOR_TEXTO_SUAVE
        ).grid(row=0, column=2, padx=(18, 6), pady=14)
        titulo = ctk.CTkEntry(marco, placeholder_text="Ej.: Inflamación aguda")
        titulo.grid(row=0, column=3, padx=(6, 16), pady=14, sticky="ew")
        marco.grid_columnconfigure(3, weight=1)
        return materia, titulo

    def _tab_grabacion(self):
        titulo_seccion(
            self.tab_grabar,
            "Grabar clase",
            "ARGOS guarda el audio y la transcripción durante la clase. Puedes "
            "moverte por la aplicación sin perder el control de la grabación.",
        )
        self.materia_grabar, self.titulo_grabar = self._campos_clase(self.tab_grabar)
        panel = tarjeta(self.tab_grabar)
        panel.pack(fill="x", padx=24, pady=(0, 12))
        panel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            panel, text="Micrófono", text_color=COLOR_TEXTO_SUAVE
        ).grid(
            row=0, column=0, padx=(16, 8), pady=(14, 6), sticky="w"
        )
        self.selector_microfono = ctk.CTkComboBox(
            panel,
            values=["Detectando entradas de Windows…"],
            command=self._seleccionar_microfono,
            state="readonly",
            width=520,
        )
        self.selector_microfono.grid(
            row=0, column=1, padx=6, pady=(14, 6), sticky="ew"
        )
        self.btn_actualizar_microfonos = ctk.CTkButton(
            panel,
            text="Actualizar",
            command=lambda: self._detectar_hardware_audio_async(
                mostrar_error=True
            ),
            width=92,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.btn_actualizar_microfonos.grid(
            row=0, column=2, padx=6, pady=(14, 6)
        )
        self.btn_probar_microfono = ctk.CTkButton(
            panel,
            text="Probar",
            command=self._probar_microfono_seleccionado,
            width=92,
            fg_color=COLOR_PANEL_SUAVE,
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.btn_probar_microfono.grid(
            row=0, column=3, padx=(6, 16), pady=(14, 6)
        )
        self.etiqueta_micro = ctk.CTkLabel(
            panel,
            text="Elige una entrada y pulsa Probar mientras hablas.",
            anchor="w",
            text_color=COLOR_TEXTO_SUAVE,
        )
        self.etiqueta_micro.grid(
            row=1,
            column=1,
            columnspan=3,
            padx=(6, 16),
            pady=(0, 12),
            sticky="ew",
        )

        controles = ctk.CTkFrame(self.tab_grabar, fg_color="transparent")
        controles.pack(fill="x", padx=24)
        self.btn_grabar = ctk.CTkButton(
            controles,
            text="●  Iniciar grabación",
            command=self._iniciar_grabacion,
            fg_color=COLOR_PELIGRO,
            hover_color="#D84855",
            width=180,
            height=42,
        )
        self.btn_grabar.pack(side="left", padx=(0, 8))
        self.btn_otra_entrada = ctk.CTkButton(
            controles,
            text="Probar otra entrada",
            command=self._probar_otra_entrada,
            state="disabled",
            width=150,
            height=42,
            fg_color=COLOR_PANEL_SUAVE,
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.btn_otra_entrada.pack(side="left", padx=8)
        ctk.CTkButton(
            controles,
            text="Permisos de Windows",
            command=self._abrir_ajustes_microfono,
            width=150,
            height=42,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDE,
        ).pack(side="left", padx=8)
        ctk.CTkLabel(
            controles,
            text="El selector fija la ruta exacta; ARGOS no la cambiará solo.",
            text_color=COLOR_TEXTO_SUAVE,
        ).pack(side="left", padx=8)
        fila_nivel = ctk.CTkFrame(self.tab_grabar, fg_color="transparent")
        fila_nivel.pack(fill="x", padx=24, pady=12)
        self.nivel = ctk.CTkProgressBar(fila_nivel)
        self.nivel.pack(side="left", fill="x", expand=True)
        self.nivel.set(0)
        self.etiqueta_nivel = ctk.CTkLabel(
            fila_nivel, text="Señal: 0 %", width=100, anchor="e"
        )
        self.etiqueta_nivel.pack(side="right", padx=(10, 0))
        self.progreso_grabar = ctk.CTkProgressBar(self.tab_grabar)
        self.progreso_grabar.pack(fill="x", padx=24, pady=(0, 10))
        self.progreso_grabar.set(0)
        cabecera_transcripcion = ctk.CTkFrame(
            self.tab_grabar, fg_color="transparent"
        )
        cabecera_transcripcion.pack(fill="x", padx=24, pady=(2, 6))
        ctk.CTkLabel(
            cabecera_transcripcion,
            text="Transcripción en directo",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self.btn_copiar_transcripcion = ctk.CTkButton(
            cabecera_transcripcion,
            text="Copiar todo",
            command=self._copiar_transcripcion_directo,
            width=105,
            height=30,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.btn_copiar_transcripcion.pack(side="right")
        self.texto_grabar = ctk.CTkTextbox(
            self.tab_grabar,
            font=ctk.CTkFont(size=14),
            fg_color=COLOR_PANEL,
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.texto_grabar.pack(fill="both", expand=True, padx=24, pady=(0, 10))
        self.texto_grabar.configure(state="disabled")
        self.texto_grabar.bind(
            "<Button-3>", self._abrir_menu_transcripcion, add="+"
        )
        ctk.CTkLabel(
            self.tab_grabar,
            text=(
                "El audio se guarda continuamente y la transcripción se actualiza "
                "automáticamente durante la grabación. Puedes seleccionar texto y "
                "copiarlo con Ctrl+C sin detenerla."
            ),
            text_color="#aaaaaa",
            anchor="w",
        ).pack(fill="x", padx=28, pady=(0, 12))

    def _tab_archivo_multimedia(self):
        titulo_seccion(
            self.tab_archivo,
            "Importar una clase",
            "Selecciona un audio o vídeo. El original no se modifica y ARGOS "
            "conserva la transcripción dentro de tu repositorio.",
        )
        self.materia_archivo, self.titulo_archivo = self._campos_clase(self.tab_archivo)
        panel = tarjeta(self.tab_archivo)
        panel.pack(fill="x", padx=24, pady=(0, 12))
        self.etiqueta_archivo = ctk.CTkLabel(panel, text="Ningún audio o vídeo seleccionado", anchor="w")
        self.etiqueta_archivo.pack(side="left", fill="x", expand=True, padx=16, pady=14)
        self.btn_seleccionar_archivo = ctk.CTkButton(
            panel,
            text="Seleccionar audio, vídeo o documento",
            command=self._seleccionar_archivo,
            fg_color=COLOR_PANEL_SUAVE,
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.btn_seleccionar_archivo.pack(side="left", padx=6)
        self.btn_transcribir_archivo = ctk.CTkButton(
            panel,
            text="Transcribir y guardar",
            command=self._transcribir_archivo,
            fg_color=COLOR_ACENTO,
        )
        self.btn_transcribir_archivo.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(
            self.tab_archivo,
            text="Admite vídeos largos. Solo usa su audio y no copia el vídeo original.",
            text_color="#aaaaaa", anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 8))
        self.progreso_archivo = ctk.CTkProgressBar(self.tab_archivo)
        self.progreso_archivo.pack(fill="x", padx=24, pady=(0, 10))
        self.progreso_archivo.set(0)
        self.texto_archivo = ctk.CTkTextbox(
            self.tab_archivo,
            font=ctk.CTkFont(size=14),
            fg_color=COLOR_PANEL,
            border_width=1,
            border_color=COLOR_BORDE,
        )
        self.texto_archivo.pack(fill="both", expand=True, padx=24, pady=(0, 18))

    def _tab_biblioteca_clases(self):
        titulo_seccion(
            self.tab_clases,
            "Mis clases",
            "Consulta el material generado sin salir de ARGOS.",
        )
        superior = tarjeta(self.tab_clases)
        superior.pack(fill="x", padx=24, pady=(0, 12))
        self.buscar_clases = ctk.CTkEntry(superior, placeholder_text="Buscar por materia, título o fecha...")
        self.buscar_clases.pack(side="left", fill="x", expand=True, padx=(16, 6), pady=14)
        self.buscar_clases.bind("<Return>", lambda _e: self._refrescar_clases())
        ctk.CTkButton(
            superior,
            text="Buscar",
            command=self._refrescar_clases,
            width=90,
            fg_color=COLOR_ACENTO,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            superior,
            text="Abrir repositorio",
            command=self.repositorio.abrir_raiz,
            width=135,
            fg_color=COLOR_PANEL_SUAVE,
            border_width=1,
            border_color=COLOR_BORDE,
        ).pack(side="left", padx=(6, 16))
        self.lista_clases = ctk.CTkScrollableFrame(
            self.tab_clases, fg_color="transparent"
        )
        self.lista_clases.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self._refrescar_clases()

    def _refrescar_clases(self):
        for widget in self.lista_clases.winfo_children():
            widget.destroy()
        filtro = self.buscar_clases.get() if hasattr(self, "buscar_clases") else ""
        clases = self.repositorio.listar_clases(filtro)
        if not clases:
            ctk.CTkLabel(
                self.lista_clases,
                text="Todavía no hay clases guardadas.",
                text_color=COLOR_TEXTO_SUAVE,
            ).pack(pady=30)
            self._refrescar_inicio()
            return
        for clase in clases:
            self._crear_tarjeta_clase(self.lista_clases, clase)
        self._refrescar_inicio()

    def _refrescar_inicio(self):
        if not hasattr(self, "lista_inicio"):
            return
        for widget in self.lista_inicio.winfo_children():
            widget.destroy()
        clases = self.repositorio.listar_clases("")[:4]
        if not clases:
            ctk.CTkLabel(
                self.lista_inicio,
                text="Tus próximas clases aparecerán aquí.",
                text_color=COLOR_TEXTO_SUAVE,
            ).pack(anchor="w", pady=12)
            return
        for clase in clases:
            self._crear_tarjeta_clase(
                self.lista_inicio, clase, compacta=True
            )

    def _crear_tarjeta_clase(self, parent, clase, compacta: bool = False):
        fila = tarjeta(parent, corner_radius=11)
        fila.pack(fill="x", pady=4)
        fecha = clase.get("fecha_iso", "").replace("T", " ")[:16]
        bloque = ctk.CTkFrame(fila, fg_color="transparent")
        bloque.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        ctk.CTkLabel(
            bloque,
            text=clase.get("titulo", "Clase sin título"),
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).pack(fill="x")
        detalle = (
            f"{clase.get('materia', '')}  ·  Clase {clase.get('numero', 0):03d}"
            + (f"  ·  {fecha}" if fecha else "")
        )
        if clase.get("audio_disponible"):
            detalle += "  ·  Audio guardado"
        estado_material = leer_estado_material_clase(clase["ruta"])
        detalle += f"  ·  {estado_material.etiqueta}"
        ctk.CTkLabel(
            bloque,
            text=detalle,
            text_color=COLOR_TEXTO_SUAVE,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))
        ctk.CTkButton(
            fila,
            text="Ver clase",
            width=88,
            height=32,
            fg_color=COLOR_ACENTO if not compacta else COLOR_PANEL_SUAVE,
            command=lambda r=clase["ruta"]: self._abrir_clase_en_argos(r),
        ).pack(side="right", padx=12)
        if not compacta:
            ctk.CTkButton(
                fila,
                text="Eliminar",
                width=76,
                height=32,
                fg_color="transparent",
                border_width=1,
                border_color=COLOR_PELIGRO,
                text_color=COLOR_PELIGRO,
                command=lambda r=clase["ruta"]: self._eliminar_clase(r),
            ).pack(side="right", padx=(4, 0))
            ctk.CTkButton(
                fila,
                text="Renombrar",
                width=84,
                height=32,
                fg_color=COLOR_PANEL_SUAVE,
                command=lambda r=clase["ruta"]: self._renombrar_clase(r),
            ).pack(side="right", padx=(4, 0))

    def _tab_detalle_clase(self):
        superior = ctk.CTkFrame(self.tab_detalle, fg_color="transparent")
        superior.pack(fill="x", padx=24, pady=(20, 10))
        ctk.CTkButton(
            superior,
            text="←  Mis clases",
            width=105,
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDE,
            command=lambda: self.tabs.set("Mis clases"),
        ).pack(side="left")
        self.btn_abrir_carpeta_detalle = ctk.CTkButton(
            superior,
            text="Abrir carpeta",
            width=105,
            height=32,
            fg_color=COLOR_PANEL_SUAVE,
        )
        self.btn_abrir_carpeta_detalle.pack(side="right")
        self.btn_reproducir_audio_detalle = ctk.CTkButton(
            superior,
            text="▶  Reproducir audio",
            width=132,
            height=32,
            fg_color=COLOR_EXITO,
            state="disabled",
        )
        self.btn_reproducir_audio_detalle.pack(side="right", padx=8)
        self.btn_eliminar_detalle = ctk.CTkButton(
            superior,
            text="Eliminar",
            width=82,
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_PELIGRO,
            text_color=COLOR_PELIGRO,
            command=lambda: self._eliminar_clase(self._ruta_detalle),
        )
        self.btn_eliminar_detalle.pack(side="right", padx=8)
        self.btn_renombrar_detalle = ctk.CTkButton(
            superior,
            text="Renombrar",
            width=90,
            height=32,
            fg_color=COLOR_PANEL_SUAVE,
            command=lambda: self._renombrar_clase(self._ruta_detalle),
        )
        self.btn_renombrar_detalle.pack(side="right")
        self.btn_reprocesar_detalle = ctk.CTkButton(
            superior,
            text="Actualizar material",
            width=130,
            height=32,
            fg_color=COLOR_ACENTO,
            command=self._reprocesar_clase_detalle,
        )
        self.btn_reprocesar_detalle.pack(side="right", padx=8)

        self.titulo_detalle = ctk.CTkLabel(
            self.tab_detalle,
            text="Clase",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        )
        self.titulo_detalle.pack(fill="x", padx=24)
        self.meta_detalle = ctk.CTkLabel(
            self.tab_detalle,
            text="",
            text_color=COLOR_TEXTO_SUAVE,
            anchor="w",
        )
        self.meta_detalle.pack(fill="x", padx=24, pady=(3, 12))
        self.estado_material_detalle = ctk.CTkLabel(
            self.tab_detalle,
            text="",
            text_color=COLOR_TEXTO_SUAVE,
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.estado_material_detalle.pack(fill="x", padx=24, pady=(0, 10))

        fila_fuentes = ctk.CTkFrame(self.tab_detalle, fg_color="transparent")
        fila_fuentes.pack(fill="x", padx=24, pady=(0, 10))
        self.fuentes_detalle = ctk.CTkLabel(
            fila_fuentes,
            text="Sin apuntes del profesor vinculados.",
            text_color=COLOR_TEXTO_SUAVE,
            anchor="w",
        )
        self.fuentes_detalle.pack(side="left", fill="x", expand=True)
        self.btn_vincular_fuentes = ctk.CTkButton(
            fila_fuentes,
            text="Vincular PDF o apuntes",
            width=165,
            height=32,
            fg_color=COLOR_PANEL_SUAVE,
            border_width=1,
            border_color=COLOR_BORDE,
            command=self._vincular_fuentes_clase,
        )
        self.btn_vincular_fuentes.pack(side="right")
        self.btn_abrir_word_detalle = ctk.CTkButton(
            fila_fuentes,
            text="Abrir apuntes Word",
            width=145,
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDE,
            state="disabled",
        )
        self.btn_abrir_word_detalle.pack(side="right", padx=8)
        self.btn_copiar_detalle = ctk.CTkButton(
            fila_fuentes,
            text="Copiar sección",
            width=115,
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDE,
            command=self._copiar_seccion_detalle,
        )
        self.btn_copiar_detalle.pack(side="right")

        registrar_diagnostico_arranque("detalle_selector")
        self.selector_detalle = ctk.CTkSegmentedButton(
            self.tab_detalle,
            values=[
                "Resumen",
                "Apuntes",
                "Transcripción",
                "Preguntas",
                "Tarjetas",
                "Fuentes",
            ],
            command=self._mostrar_seccion_detalle,
            selected_color=COLOR_ACENTO,
            selected_hover_color=COLOR_ACENTO,
        )
        self.selector_detalle.pack(fill="x", padx=24, pady=(0, 10))
        registrar_diagnostico_arranque("detalle_texto")
        self.texto_detalle = ctk.CTkTextbox(
            self.tab_detalle,
            font=ctk.CTkFont(size=14),
            fg_color=COLOR_PANEL,
            border_width=1,
            border_color=COLOR_BORDE,
            wrap="word",
        )
        self.texto_detalle.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        registrar_diagnostico_arranque("detalle_estilos")
        self.texto_detalle.tag_config(
            "titulo1", foreground=COLOR_TEXTO, spacing1=12, spacing3=8
        )
        self.texto_detalle.tag_config(
            "titulo2", foreground=COLOR_ACENTO, spacing1=12, spacing3=6
        )
        self.texto_detalle.tag_config(
            "titulo3", foreground=COLOR_TEXTO, spacing1=8, spacing3=4
        )
        self.texto_detalle.tag_config(
            "nota", foreground=COLOR_TEXTO_SUAVE, lmargin1=14, lmargin2=14, spacing3=5
        )
        self.texto_detalle.tag_config(
            "tabla", foreground="#D8E4F5", background=COLOR_PANEL_SUAVE, lmargin1=8, lmargin2=8, spacing1=2, spacing3=2
        )
        self.texto_detalle.tag_config(
            "lista", foreground=COLOR_TEXTO, lmargin1=12, lmargin2=26, spacing3=3
        )
        self.texto_detalle.tag_config(
            "pregunta", foreground=COLOR_ALERTA, spacing3=4
        )
        registrar_diagnostico_arranque("detalle_listo")
        self._contenido_detalle_actual = ""
        self._ruta_detalle = None

    def _abrir_clase_en_argos(self, ruta):
        carpeta = Path(ruta)
        self._ruta_detalle = carpeta
        ficha = {}
        try:
            ficha = json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.titulo_detalle.configure(
            text=ficha.get("titulo") or carpeta.name
        )
        fecha = str(ficha.get("fecha_iso", "")).replace("T", " ")[:16]
        meta = f"{ficha.get('materia', '')}"
        if ficha.get("numero"):
            meta += f"  ·  Clase {int(ficha['numero']):03d}"
        if fecha:
            meta += f"  ·  {fecha}"
        estado_material = leer_estado_material_clase(carpeta)
        colores_estado = {
            "listo": COLOR_EXITO,
            "procesando": COLOR_ALERTA,
            "error": COLOR_PELIGRO,
            "incompleto": COLOR_PELIGRO,
        }
        self.estado_material_detalle.configure(
            text=f"{estado_material.etiqueta} · {estado_material.detalle}",
            text_color=colores_estado.get(
                estado_material.clave, COLOR_TEXTO_SUAVE
            ),
        )
        vinculados = ficha.get("documentos_vinculados", [])
        total_vinculados = len(vinculados) if isinstance(vinculados, list) else 0
        self.fuentes_detalle.configure(
            text=(
                f"{total_vinculados} fuente(s) del profesor vinculada(s). "
                "ARGOS las prioriza frente a la biblioteca general."
                if total_vinculados
                else "Sin apuntes del profesor vinculados."
            )
        )
        audio = None
        try:
            audio = self.repositorio.obtener_audio_clase(carpeta)
        except (OSError, ValueError):
            pass
        if audio:
            duracion = ficha.get("audio_duracion_segundos")
            if isinstance(duracion, (int, float)):
                minutos, segundos = divmod(int(round(duracion)), 60)
                meta += f"  ·  Audio {minutos:02d}:{segundos:02d}"
            else:
                meta += "  ·  Audio guardado"
            self.btn_reproducir_audio_detalle.configure(
                state="normal",
                command=lambda r=carpeta: self._reproducir_audio_clase(r),
            )
        else:
            self.btn_reproducir_audio_detalle.configure(
                state="disabled", command=lambda: None
            )
        word = carpeta / "apuntes_argos.docx"
        if word.is_file():
            self.btn_abrir_word_detalle.configure(
                state="normal", command=lambda r=word: os.startfile(r)
            )
        else:
            self.btn_abrir_word_detalle.configure(
                state="disabled", command=lambda: None
            )
        self.meta_detalle.configure(text=meta)
        self.btn_abrir_carpeta_detalle.configure(
            command=lambda r=carpeta: self.repositorio.abrir_carpeta(r)
        )
        self.selector_detalle.set("Resumen")
        self._mostrar_seccion_detalle("Resumen")
        self.tabs.set("Detalle de clase")

    def _vincular_fuentes_clase(self):
        if not self._ruta_detalle:
            return
        rutas = filedialog.askopenfilenames(
            title="Vincular PDF o apuntes a esta clase",
            filetypes=[
                ("Documentos", "*.pdf *.docx *.txt *.md"),
                ("PDF", "*.pdf"),
                ("Todos", "*.*"),
            ],
        )
        if not rutas:
            return
        carpeta = Path(self._ruta_detalle)
        self.btn_vincular_fuentes.configure(state="disabled", text="Procesando…")
        self.estado.configure(
            text=f"Preparando {len(rutas)} fuente(s) para esta clase…"
        )

        def worker():
            documentos = []
            errores = []
            for ruta in rutas:
                try:
                    item, _creado = self.biblioteca_medica.importar_archivo(
                        ruta, "Apuntes"
                    )
                    if item.get("estado_indice_ia") != "texto_extraido":
                        item = self.biblioteca_medica.procesar_documento(item["id"])
                    documentos.append(item)
                    if item.get("requiere_ocr"):
                        errores.append(
                            f"{item.get('nombre')}: el PDF parece escaneado y requiere OCR."
                        )
                except Exception as exc:
                    errores.append(f"{Path(ruta).name}: {exc}")
            if documentos:
                self.repositorio.vincular_documentos(carpeta, documentos)
            self._enviar_ui(
                self._fin_vincular_fuentes, carpeta, documentos, errores
            )

        threading.Thread(
            target=worker,
            daemon=True,
            name="argos-vincular-fuentes-clase",
        ).start()

    def _fin_vincular_fuentes(self, carpeta, documentos, errores):
        self.btn_vincular_fuentes.configure(
            state="normal", text="Vincular PDF o apuntes"
        )
        self._abrir_clase_en_argos(carpeta)
        if documentos and hasattr(self, "_encolar_pipeline"):
            self.estado.configure(
                text="Fuentes vinculadas. Actualizando el material de la clase…"
            )
            self._encolar_pipeline(carpeta, automatico=True)
        if errores:
            messagebox.showwarning(
                "Fuentes de la clase",
                "Algunas fuentes necesitan revisión:\n\n" + "\n".join(errores),
            )

    def _reproducir_audio_clase(self, ruta):
        try:
            self.repositorio.abrir_audio_clase(ruta)
        except Exception as exc:
            messagebox.showerror("Audio de la clase", str(exc))

    def _mostrar_seccion_detalle(self, seccion):
        if not self._ruta_detalle:
            return
        _archivo, contenido = leer_material_clase(self._ruta_detalle, seccion)
        self._contenido_detalle_actual = contenido
        self.texto_detalle.configure(state="normal")
        self.texto_detalle.delete("1.0", "end")
        for texto, etiqueta in preparar_material_para_lectura(contenido, seccion):
            if texto:
                self.texto_detalle.insert("end", texto, etiqueta)
        self.texto_detalle.configure(state="disabled")

    def _copiar_seccion_detalle(self):
        contenido = self._contenido_detalle_actual.strip()
        if not contenido:
            self.estado.configure(text="No hay contenido que copiar en esta sección.")
            return
        self.clipboard_clear()
        self.clipboard_append(contenido)
        self.estado.configure(text="Sección copiada al portapapeles.")

    def _reprocesar_clase_detalle(self):
        if not self._ruta_detalle:
            return
        if hasattr(self, "_encolar_pipeline"):
            self._encolar_pipeline(self._ruta_detalle, automatico=False)
            self.tabs.set("Procesar clase")
            return
        messagebox.showinfo(
            "ARGOS", "El procesamiento estará disponible al terminar de iniciar."
        )

    def _renombrar_clase(self, ruta):
        if not ruta:
            return
        carpeta = Path(ruta)
        actual = carpeta.name.split(" · ", 2)[-1]
        try:
            ficha = json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))
            actual = ficha.get("titulo") or actual
        except (OSError, ValueError):
            pass
        nuevo = simpledialog.askstring(
            "Renombrar clase",
            "Nuevo nombre de la clase:",
            initialvalue=actual,
            parent=self,
        )
        if nuevo is None:
            return
        try:
            destino = self.repositorio.renombrar_clase(carpeta, nuevo)
        except Exception as exc:
            messagebox.showerror("Renombrar clase", str(exc))
            return
        if self._ruta_detalle and Path(self._ruta_detalle) == carpeta:
            self._abrir_clase_en_argos(destino)
        self._refrescar_clases()
        if hasattr(self, "_reconstruir_indice"):
            self._reconstruir_indice()

    def _eliminar_clase(self, ruta):
        if not ruta:
            return
        carpeta = Path(ruta)
        titulo = carpeta.name.split(" · ", 2)[-1]
        if not messagebox.askyesno(
            "Eliminar clase",
            f"¿Mover «{titulo}» a la Papelera ARGOS?\n\n"
            "Se conservarán el audio, la transcripción y los materiales.",
        ):
            return
        try:
            self.repositorio.eliminar_clase(carpeta)
        except Exception as exc:
            messagebox.showerror("Eliminar clase", str(exc))
            return
        if self._ruta_detalle and Path(self._ruta_detalle) == carpeta:
            self._ruta_detalle = None
            self.tabs.set("Mis clases")
        self._refrescar_clases()
        if hasattr(self, "_reconstruir_indice"):
            self._reconstruir_indice()

    def _tab_biblioteca_medica(self):
        titulo_seccion(
            self.tab_medica,
            "Biblioteca",
            "Añade tratados, apuntes, exámenes y artículos para que ARGOS pueda "
            "utilizarlos como fuentes locales.",
        )
        superior = tarjeta(self.tab_medica)
        superior.pack(fill="x", padx=24, pady=(0, 12))

        self.buscar_documentos = ctk.CTkEntry(superior, placeholder_text="Buscar tratado, apunte, examen...")
        self.buscar_documentos.pack(side="left", fill="x", expand=True, padx=(16, 6), pady=14)
        self.categoria_documentos = ctk.CTkComboBox(superior, values=["Todas", *CATEGORIAS], width=130)
        self.categoria_documentos.set("Todas")
        self.categoria_documentos.pack(side="left", padx=6)
        ctk.CTkButton(superior, text="Buscar", command=self._refrescar_documentos, width=80).pack(side="left", padx=6)
        ctk.CTkButton(superior, text="Importar", command=self._importar_documentos, width=90).pack(side="left", padx=6)
        ctk.CTkButton(
            superior, text="Abrir carpeta", command=self.biblioteca_medica.abrir_raiz, width=110
        ).pack(side="left", padx=(6, 16))

        acciones = ctk.CTkFrame(self.tab_medica, fg_color="transparent")
        acciones.pack(fill="x", padx=24, pady=(0, 8))
        ctk.CTkButton(
            acciones, text="Extraer texto pendiente", command=self._procesar_documentos_pendientes
        ).pack(side="left")
        self.progreso_documentos = ctk.CTkProgressBar(acciones)
        self.progreso_documentos.pack(side="left", fill="x", expand=True, padx=12)
        self.progreso_documentos.set(0)
        self.estado_documentos = ctk.CTkLabel(acciones, text="Sin documentos procesándose", width=230, anchor="e")
        self.estado_documentos.pack(side="right")

        ctk.CTkLabel(
            self.tab_medica,
            text="Los PDFs digitales se indexan por página. Los escaneados se marcarán como «requiere OCR».",
            text_color="#aaaaaa", anchor="w"
        ).pack(fill="x", padx=28, pady=(0, 8))

        self.lista_documentos = ctk.CTkScrollableFrame(
            self.tab_medica, fg_color="transparent"
        )
        self.lista_documentos.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        self._refrescar_documentos()

    def _refrescar_documentos(self):
        for widget in self.lista_documentos.winfo_children():
            widget.destroy()
        filtro = self.buscar_documentos.get() if hasattr(self, "buscar_documentos") else ""
        categoria = self.categoria_documentos.get() if hasattr(self, "categoria_documentos") else "Todas"
        items = self.biblioteca_medica.listar(filtro, categoria)
        if not items:
            ctk.CTkLabel(self.lista_documentos, text="Todavía no hay documentos médicos importados.").pack(pady=30)
            return

        nombres_estado = {
            "pendiente": "Pendiente",
            "procesando": "Procesando",
            "texto_extraido": "Texto extraído",
            "requiere_ocr": "Requiere OCR",
            "error": "Error",
        }
        for item in items:
            fila = ctk.CTkFrame(self.lista_documentos)
            fila.pack(fill="x", pady=4)
            estado = nombres_estado.get(item.get("estado_indice_ia"), item.get("estado_indice_ia", ""))
            paginas = item.get("total_paginas")
            detalle = f"{item.get('categoria')} · {estado}"
            if paginas:
                detalle += f" · {paginas} pág."
            bloque = ctk.CTkFrame(fila, fg_color="transparent")
            bloque.pack(side="left", fill="x", expand=True, padx=12, pady=8)
            ctk.CTkLabel(bloque, text=item.get("nombre", ""), anchor="w", font=ctk.CTkFont(weight="bold")).pack(fill="x")
            ctk.CTkLabel(bloque, text=detalle, anchor="w", text_color="#aaaaaa").pack(fill="x")
            ctk.CTkButton(
                fila, text="Abrir", width=70,
                command=lambda r=item["ruta"]: self.biblioteca_medica.abrir_archivo(r)
            ).pack(side="right", padx=(4, 10))
            if item.get("estado_indice_ia") in {"pendiente", "error"}:
                ctk.CTkButton(
                    fila, text="Extraer", width=75,
                    command=lambda i=item["id"]: self._procesar_un_documento(i)
                ).pack(side="right", padx=4)

    def _importar_documentos(self):
        categoria = self.categoria_documentos.get()
        if categoria == "Todas":
            categoria = "Tratados"
        rutas = filedialog.askopenfilenames(
            title="Importar documentos médicos",
            filetypes=[
                ("Documentos", "*.pdf *.docx *.txt *.md"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("Todos", "*.*"),
            ],
        )
        if not rutas:
            return
        self._importar_y_procesar_documentos(rutas, categoria)

    def _importar_y_procesar_documentos(self, rutas, categoria="Tratados"):
        nuevos, repetidos, errores, ids_nuevos = 0, 0, [], []
        for ruta in rutas:
            try:
                item, creado = self.biblioteca_medica.importar_archivo(
                    ruta, categoria
                )
                nuevos += int(creado)
                repetidos += int(not creado)
                if creado or item.get("estado_indice_ia") in {
                    "pendiente",
                    "error",
                    "procesando",
                }:
                    ids_nuevos.append(item["id"])
            except Exception as exc:
                errores.append(f"{Path(ruta).name}: {exc}")
        self._refrescar_documentos()
        mensaje = f"Importados: {nuevos}. Ya existentes: {repetidos}."
        if errores:
            mensaje += "\n\nErrores:\n" + "\n".join(errores[:5])
        if not ids_nuevos:
            messagebox.showinfo("Biblioteca médica", mensaje)
            return
        self.estado_documentos.configure(
            text=f"Extrayendo texto de {len(ids_nuevos)} documento(s)…"
        )

        def worker():
            errores_extraccion = []
            total = len(ids_nuevos)
            for posicion, item_id in enumerate(ids_nuevos, 1):
                try:
                    self.biblioteca_medica.procesar_documento(
                        item_id,
                        lambda msg, p, pos=posicion: self._enviar_ui(
                            self._actualizar_progreso_documentos,
                            msg,
                            ((pos - 1) + p) / total,
                        ),
                    )
                except Exception as exc:
                    errores_extraccion.append(str(exc))
            self._enviar_ui(self._refrescar_documentos)
            self._enviar_ui(
                self._fin_importacion_documentos,
                mensaje,
                errores_extraccion,
            )

        threading.Thread(
            target=worker, daemon=True, name="argos-importacion-documentos"
        ).start()

    def _fin_importacion_documentos(self, mensaje, errores):
        self._actualizar_progreso_documentos("Finalizado", 0)
        if errores:
            mensaje += "\n\nErrores de extracción:\n" + "\n".join(errores[:5])
        messagebox.showinfo("Biblioteca médica", mensaje)
        if not errores and hasattr(self, "_reconstruir_indice"):
            self._reconstruir_indice()

    def _procesar_un_documento(self, item_id):
        def worker():
            try:
                self.biblioteca_medica.procesar_documento(
                    item_id,
                    lambda msg, p: self._enviar_ui(
                        self._actualizar_progreso_documentos, msg, p
                    )
                )
                self._enviar_ui(self._refrescar_documentos)
            except Exception as exc:
                self._enviar_ui(
                    messagebox.showerror, "Extracción documental", str(exc)
                )
            finally:
                self._enviar_ui(
                    self._actualizar_progreso_documentos, "Finalizado", 0
                )
        threading.Thread(target=worker, daemon=True).start()

    def _procesar_documentos_pendientes(self):
        def worker():
            try:
                self.biblioteca_medica.procesar_pendientes(
                    lambda msg, p: self._enviar_ui(
                        self._actualizar_progreso_documentos, msg, p
                    )
                )
                self._enviar_ui(self._refrescar_documentos)
                self._enviar_ui(
                    messagebox.showinfo,
                    "Biblioteca médica",
                    "Extracción de texto completada.",
                )
            except Exception as exc:
                self._enviar_ui(
                    messagebox.showerror, "Extracción documental", str(exc)
                )
            finally:
                self._enviar_ui(
                    self._actualizar_progreso_documentos, "Finalizado", 0
                )
        threading.Thread(target=worker, daemon=True).start()

    def _actualizar_progreso_documentos(self, mensaje, valor):
        self.estado_documentos.configure(text=mensaje)
        self.progreso_documentos.set(valor)

    def _tab_configuracion(self):
        titulo_seccion(
            self.tab_config,
            "Configuración",
            "Ajustes del motor local de transcripción.",
        )
        marco = ctk.CTkScrollableFrame(
            self.tab_config, fg_color=COLOR_PANEL
        )
        marco.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        ctk.CTkLabel(
            marco,
            text=(
                "Token de Hugging Face (solo desarrollo; la diarización no "
                "está incluida en el instalador básico)"
            ),
            anchor="w",
        ).pack(fill="x", pady=(8, 4))
        self.token = ctk.CTkEntry(marco, show="*")
        self.token.pack(fill="x", pady=(0, 12))
        self.token.insert(0, self.config_obj.hf_token)
        ctk.CTkLabel(marco, text="Modelo Whisper", anchor="w").pack(fill="x")
        self.modelo = ctk.CTkComboBox(
            marco,
            values=[
                "tiny",
                "base",
                "small",
                "medium",
                "large-v3-turbo",
                "large-v3",
            ],
        )
        self.modelo.pack(fill="x", pady=(4, 12))
        self.modelo.set(self.config_obj.whisper_model)
        ctk.CTkLabel(marco, text="Idioma", anchor="w").pack(fill="x")
        self.idioma = ctk.CTkComboBox(marco, values=["es", "en", "fr", "de", "it", "pt", "auto"])
        self.idioma.pack(fill="x", pady=(4, 12))
        self.idioma.set(self.config_obj.idioma)
        self.gpu = ctk.CTkSwitch(marco, text="Usar GPU NVIDIA cuando esté disponible")
        self.gpu.pack(fill="x", pady=8)
        if self.config_obj.usar_gpu:
            self.gpu.select()
        ctk.CTkButton(marco, text="Guardar y recargar modelos", command=self._guardar_config).pack(pady=18)

    def _datos_clase(self, materia, titulo):
        m, t = materia.get().strip(), titulo.get().strip()
        if not m or not t:
            messagebox.showwarning("Datos de la clase", "Indica la materia y el título antes de continuar.")
            return None
        return m, t

    def _detectar_hardware_audio(self, mostrar_error: bool = False):
        try:
            dispositivos = GrabadorAudio.detectar_dispositivos_entrada(
                self.config_obj.sample_rate,
                self.config_obj.dispositivo_audio,
            )
            return self._aplicar_dispositivos_audio(dispositivos)
        except Exception as exc:
            self._aplicar_error_dispositivos_audio(str(exc), mostrar_error)
            return None

    def _detectar_hardware_audio_async(
        self, mostrar_error: bool = False
    ) -> None:
        """Enumera PortAudio sin bloquear la construcción ni el repintado."""
        if hasattr(self, "selector_microfono"):
            self.selector_microfono.configure(
                values=["Detectando entradas de Windows…"], state="disabled"
            )
            self.selector_microfono.set("Detectando entradas de Windows…")
        if hasattr(self, "etiqueta_micro"):
            self.etiqueta_micro.configure(
                text="Consultando los dispositivos de entrada de Windows…",
                text_color=COLOR_TEXTO_SUAVE,
            )

        def worker():
            try:
                dispositivos = GrabadorAudio.detectar_dispositivos_entrada(
                    self.config_obj.sample_rate,
                    self.config_obj.dispositivo_audio,
                )
                self._enviar_ui(
                    self._aplicar_dispositivos_audio, dispositivos
                )
            except Exception as exc:
                self._enviar_ui(
                    self._aplicar_error_dispositivos_audio,
                    str(exc),
                    mostrar_error,
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="argos-deteccion-audio",
        ).start()

    def _aplicar_dispositivos_audio(self, dispositivos):
        indice_previo = (
            self._dispositivo_entrada.indice
            if self._dispositivo_entrada is not None
            else None
        )
        try:
            indice_guardado = int(self.config_obj.dispositivo_audio)
        except (TypeError, ValueError):
            indice_guardado = None
        dispositivo = next(
            (
                entrada
                for entrada in dispositivos
                if entrada.indice in (indice_previo, indice_guardado)
            ),
            dispositivos[0],
        )
        self._dispositivos_entrada = dispositivos
        self._dispositivo_entrada = dispositivo
        self._opciones_microfono = {
            self._texto_opcion_microfono(entrada): entrada
            for entrada in dispositivos
        }
        if hasattr(self, "selector_microfono"):
            self.selector_microfono.configure(
                values=list(self._opciones_microfono), state="readonly"
            )
            self.selector_microfono.set(
                self._texto_opcion_microfono(dispositivo)
            )
        if hasattr(self, "etiqueta_micro"):
            self.etiqueta_micro.configure(
                text=(
                    "Entrada seleccionada. Pulsa Probar y habla para confirmar "
                    "que Windows entrega señal."
                ),
                text_color=COLOR_TEXTO_SUAVE,
            )
        return dispositivo

    def _aplicar_error_dispositivos_audio(
        self, error: str, mostrar_error: bool = False
    ) -> None:
        self._dispositivos_entrada = []
        self._dispositivo_entrada = None
        self._opciones_microfono = {}
        if hasattr(self, "selector_microfono"):
            self.selector_microfono.configure(
                values=["No hay entradas disponibles"], state="disabled"
            )
            self.selector_microfono.set("No hay entradas disponibles")
        if hasattr(self, "etiqueta_micro"):
            self.etiqueta_micro.configure(
                text="No se encontró una entrada de audio utilizable",
                text_color="#ef5350",
            )
        if mostrar_error:
            messagebox.showerror("Hardware de audio", error)

    @staticmethod
    def _texto_opcion_microfono(entrada) -> str:
        host = entrada.hostapi or "PortAudio"
        return f"{entrada.nombre} · {host} · entrada #{entrada.indice}"

    def _seleccionar_microfono(self, opcion: str) -> None:
        dispositivo = self._opciones_microfono.get(opcion)
        if dispositivo is None:
            return
        self._dispositivo_entrada = dispositivo
        self._seleccion_microfono_manual = True
        self.config_obj.dispositivo_audio = str(dispositivo.indice)
        self.config_obj.sample_rate = dispositivo.sample_rate
        self.config_obj.guardar()
        self.etiqueta_micro.configure(
            text="Entrada elegida. Pulsa Probar y habla para comprobarla.",
            text_color=COLOR_TEXTO_SUAVE,
        )
        if self.grabador and self.grabador.esta_grabando():
            self._cambiar_microfono_durante_grabacion(dispositivo)

    def _probar_microfono_seleccionado(self) -> None:
        if self._prueba_microfono_en_curso:
            return
        if self.grabador and self.grabador.esta_grabando():
            self.estado.configure(
                text="Selecciona otra entrada en la lista para cambiarla durante la grabación."
            )
            return
        dispositivo = self._dispositivo_entrada
        if dispositivo is None:
            dispositivo = self._detectar_hardware_audio(mostrar_error=True)
        if dispositivo is None:
            return

        self._prueba_microfono_en_curso = True
        self._seleccion_microfono_manual = True
        self.btn_probar_microfono.configure(state="disabled", text="Escuchando…")
        self.btn_actualizar_microfonos.configure(state="disabled")
        self.selector_microfono.configure(state="disabled")
        self._nivel_audio_pendiente = None
        self.nivel.set(0)
        self._nivel_audio_mostrado = 0.0
        self.etiqueta_nivel.configure(text="Señal: 0 %")
        self.etiqueta_micro.configure(
            text="Habla ahora durante unos segundos…",
            text_color=COLOR_ALERTA,
        )

        def worker():
            try:
                nivel = GrabadorAudio.medir_senal(
                    dispositivo,
                    duracion=4.0,
                    callback_nivel=self._publicar_nivel_audio,
                )
                self._enviar_ui(
                    self._fin_prueba_microfono, dispositivo, nivel, None
                )
            except Exception as exc:
                self._enviar_ui(
                    self._fin_prueba_microfono, dispositivo, 0.0, str(exc)
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="argos-prueba-manual-microfono",
        ).start()

    def _fin_prueba_microfono(
        self, dispositivo, nivel: float, error: str | None
    ) -> None:
        self._prueba_microfono_en_curso = False
        self.btn_probar_microfono.configure(state="normal", text="Probar")
        self.btn_actualizar_microfonos.configure(state="normal")
        self.selector_microfono.configure(state="readonly")
        if error:
            self.etiqueta_micro.configure(
                text=f"Windows no pudo abrir esta entrada: {error}",
                text_color=COLOR_PELIGRO,
            )
            return
        if nivel >= UMBRAL_SENAL_UTIL:
            self._dispositivo_entrada = dispositivo
            self.config_obj.dispositivo_audio = str(dispositivo.indice)
            self.config_obj.sample_rate = dispositivo.sample_rate
            self.config_obj.guardar()
            self.etiqueta_micro.configure(
                text=(
                    f"Micrófono confirmado: recibe señal ({nivel * 100:.1f} %). "
                    "Ya puedes iniciar la grabación."
                ),
                text_color=COLOR_EXITO,
            )
        else:
            self.etiqueta_micro.configure(
                text=(
                    "Esta entrada abre, pero no recibe tu voz. Elige otra en la "
                    "lista o revisa Permisos de Windows."
                ),
                text_color=COLOR_PELIGRO,
            )

    def _cambiar_microfono_durante_grabacion(self, dispositivo) -> None:
        self.etiqueta_micro.configure(
            text=f"Cambiando a {dispositivo.nombre}…",
            text_color=COLOR_ALERTA,
        )

        def worker():
            cambiado = bool(
                self.grabador
                and self.grabador.seleccionar_entrada(dispositivo.indice)
            )
            error = self.grabador.ultimo_error if self.grabador else None
            self._enviar_ui(
                self._fin_seleccion_microfono_grabando,
                dispositivo,
                cambiado,
                error,
            )

        threading.Thread(
            target=worker,
            daemon=True,
            name="argos-seleccion-manual-microfono",
        ).start()

    def _fin_seleccion_microfono_grabando(
        self, dispositivo, cambiado: bool, error: str | None
    ) -> None:
        if cambiado:
            self.etiqueta_micro.configure(
                text=f"Grabando con {dispositivo.nombre}. Habla para verificar la señal.",
                text_color=COLOR_EXITO,
            )
        else:
            self.etiqueta_micro.configure(
                text=f"No se pudo usar esa entrada: {error or 'error desconocido'}",
                text_color=COLOR_PELIGRO,
            )

    def _iniciar_grabacion(self):
        datos = self._datos_clase(self.materia_grabar, self.titulo_grabar)
        if not datos:
            return
        if not self.transcriptor or not self.transcriptor.modelos_cargados:
            messagebox.showwarning("Modelos", "Los modelos todavía no están listos.")
            return
        dispositivo = self._dispositivo_entrada
        if dispositivo is None:
            dispositivo = self._detectar_hardware_audio(mostrar_error=True)
        if not dispositivo:
            return
        candidatos = [dispositivo] + [
            entrada
            for entrada in self._dispositivos_entrada
            if entrada.indice != dispositivo.indice
        ]
        materia, titulo = datos
        try:
            carpeta = self.repositorio.iniciar_grabacion(
                materia,
                titulo,
                dispositivo.sample_rate,
                f"{dispositivo.indice}: {dispositivo.nombre}",
            )
        except Exception as exc:
            messagebox.showerror("Grabación", f"No se pudo preparar la clase: {exc}")
            return

        self._carpeta_grabacion = carpeta
        self._registrar_diagnostico_audio(
            "candidatos",
            candidatos=[
                {
                    "indice": entrada.indice,
                    "nombre": entrada.nombre,
                    "frecuencia_nativa": entrada.sample_rate,
                    "canales": entrada.canales,
                    "hostapi": entrada.hostapi,
                }
                for entrada in candidatos
            ],
        )

        self._transcripcion_incremental = TranscripcionIncremental(
            self.transcriptor,
            self.repositorio,
            carpeta,
            callback_segmentos=lambda segmentos: self._enviar_ui(
                self._mostrar_transcripcion_incremental, segmentos
            ),
            callback_estado=lambda mensaje: self._enviar_ui(
                self.estado.configure, {"text": mensaje}
            ),
            consolidar_audio_completo=True,
            min_hablantes=self.config_obj.min_hablantes,
            max_hablantes=self.config_obj.max_hablantes,
        )
        self._modelo_grabacion_actual = self.transcriptor.model_size
        self.grabador = GrabadorAudio(dispositivo.sample_rate, dispositivo.indice)
        ok = self.grabador.iniciar(
            self._publicar_nivel_audio,
            str(carpeta / "audio.wav"),
            str(carpeta / "fragmentos_audio"),
            lambda fragmento: self._transcripcion_incremental.encolar(fragmento),
            candidatos_entrada=candidatos,
            callback_dispositivo=lambda entrada, motivo: self._enviar_ui(
                self._actualizar_dispositivo_grabacion, entrada, motivo
            ),
            duracion_fragmento=10.0,
            segundos_sin_senal=2.5,
            priorizar_senal_inicial=False,
            supervisar_entrada=False,
        )
        self._registrar_diagnostico_audio(
            "prueba_inicial_senal",
            resultados=self.grabador.pruebas_senal,
        )
        if not ok:
            self._transcripcion_incremental.cerrar_sin_esperar()
            self._transcripcion_incremental = None
            self._carpeta_grabacion = None
            self.repositorio.marcar_estado_grabacion(
                carpeta,
                "error",
                self.grabador.ultimo_error or "No se pudo abrir el micrófono.",
            )
            messagebox.showerror("Audio", self.grabador.ultimo_error or "No se pudo iniciar la grabación.")
            return
        dispositivo = next(
            (
                entrada
                for entrada in self._dispositivos_entrada
                if entrada.indice == self.grabador.dispositivo
            ),
            dispositivo,
        )
        self._dispositivo_entrada = dispositivo
        self.config_obj.dispositivo_audio = str(dispositivo.indice)
        self.config_obj.sample_rate = dispositivo.sample_rate
        self.config_obj.ultima_materia = materia
        self.config_obj.guardar()
        self._grabando_desde = time.time()
        self._deteniendo_grabacion = False
        self._grabacion_pausada = False
        self._nivel_audio_pendiente = None
        self._nivel_audio_mostrado = 0.0
        self._texto_grabar_renderizado = actualizar_texto(
            self.texto_grabar,
            "Escuchando… El primer texto aparecerá automáticamente en unos segundos.",
            "",
        )
        self.btn_grabar.configure(state="disabled")
        self.btn_otra_entrada.configure(state="normal")
        self.btn_probar_microfono.configure(state="disabled")
        self.btn_actualizar_microfonos.configure(state="disabled")
        self.selector_microfono.configure(state="readonly")
        self.btn_pausar.configure(state="normal", text="Pausar")
        self.btn_detener.configure(state="normal")
        self.estado_grabacion_global.configure(
            text="●  Grabando", text_color=COLOR_PELIGRO
        )
        self.estado.configure(
            text=f"Grabando con {dispositivo.nombre}; audio protegido en {carpeta.name}."
        )
        self._actualizar_reloj()

    def _actualizar_nivel_audio(self, nivel: float) -> None:
        nivel = max(0.0, min(1.0, float(nivel)))
        self.nivel.set(nivel)
        self._nivel_audio_mostrado = nivel
        if hasattr(self, "etiqueta_nivel"):
            self.etiqueta_nivel.configure(text=f"Señal: {nivel * 100:.1f} %")

    def _publicar_nivel_audio(self, nivel: float) -> None:
        """Conserva solo la lectura más reciente sin tocar Tk desde PortAudio."""
        try:
            self._nivel_audio_pendiente = max(0.0, min(1.0, float(nivel)))
        except (TypeError, ValueError):
            return

    def _actualizar_dispositivo_grabacion(self, entrada, motivo: str) -> None:
        self._dispositivo_entrada = entrada
        self.config_obj.dispositivo_audio = str(entrada.indice)
        self.config_obj.sample_rate = entrada.sample_rate
        self.config_obj.guardar()
        self._registrar_diagnostico_audio(
            motivo,
            indice=entrada.indice,
            nombre=entrada.nombre,
            frecuencia_nativa=entrada.sample_rate,
            frecuencia_wav=self.grabador.sample_rate if self.grabador else None,
            canales=entrada.canales,
            hostapi=entrada.hostapi,
        )
        detalle_host = f" · {entrada.hostapi}" if entrada.hostapi else ""
        self.etiqueta_micro.configure(
            text=(
                f"{entrada.nombre} · {entrada.sample_rate} Hz · "
                f"{entrada.canales} canal(es){detalle_host}"
            ),
            text_color="#4caf50" if motivo != "sin_senal" else "#ef5350",
        )
        opcion = next(
            (
                texto
                for texto, candidato in self._opciones_microfono.items()
                if candidato.indice == entrada.indice
            ),
            None,
        )
        if opcion:
            self.selector_microfono.set(opcion)
        if motivo == "cambio_automatico":
            self.estado.configure(
                text=(
                    "La primera ruta no entregó señal; ARGOS ha cambiado "
                    f"automáticamente a {entrada.nombre}. Habla para verificarla."
                )
            )
        elif motivo == "cambio_manual":
            self.estado.configure(
                text=f"Probando manualmente {entrada.nombre}. Habla ahora."
            )
        elif motivo == "seleccion_manual":
            self.estado.configure(
                text=f"Entrada fijada en {entrada.nombre}. Habla para verificarla."
            )
        elif motivo == "sin_senal":
            self.estado.configure(
                text=(
                    "Windows no entrega señal por ninguna entrada compatible. "
                    "Revisa Privacidad > Micrófono y que el micrófono no esté silenciado."
                )
            )

    def _probar_otra_entrada(self) -> None:
        if not self.grabador or not self.grabador.esta_grabando():
            return
        self.btn_otra_entrada.configure(state="disabled", text="Cambiando…")

        def worker():
            cambiado = self.grabador.probar_siguiente_entrada()
            self._enviar_ui(self._fin_cambio_manual, cambiado)

        threading.Thread(
            target=worker, daemon=True, name="argos-cambio-manual-microfono"
        ).start()

    def _alternar_pausa(self) -> None:
        if not self.grabador or not self.grabador.esta_grabando():
            return
        if self.grabador.esta_pausado():
            if not self.grabador.reanudar():
                return
            self._grabacion_pausada = False
            self.btn_pausar.configure(text="Pausar")
            self.btn_otra_entrada.configure(state="normal")
            self.selector_microfono.configure(state="readonly")
            self.estado_grabacion_global.configure(
                text="●  Grabando", text_color=COLOR_PELIGRO
            )
            self.estado.configure(text="Grabación reanudada; escuchando la habitación.")
        else:
            if not self.grabador.pausar():
                return
            self._grabacion_pausada = True
            self.btn_pausar.configure(text="Reanudar")
            self.btn_otra_entrada.configure(state="disabled")
            self.selector_microfono.configure(state="disabled")
            self._nivel_audio_pendiente = None
            self.nivel.set(0)
            self._nivel_audio_mostrado = 0.0
            self.etiqueta_nivel.configure(text="Señal: en pausa")
            self.estado_grabacion_global.configure(
                text="Ⅱ  En pausa", text_color=COLOR_ALERTA
            )
            self.estado.configure(
                text="Grabación pausada. El audio anterior está guardado; pulsa Reanudar para continuar."
            )

    def _fin_cambio_manual(self, cambiado: bool) -> None:
        self.btn_otra_entrada.configure(state="normal", text="Probar otra entrada")
        if not cambiado:
            self.estado.configure(
                text=(
                    "No quedan entradas nuevas. Abre «Permisos de Windows», "
                    "habilita el micrófono para aplicaciones de escritorio y reinicia la grabación."
                )
            )

    @staticmethod
    def _abrir_ajustes_microfono() -> None:
        try:
            if os.name == "nt":
                os.startfile("ms-settings:privacy-microphone")
        except OSError as exc:
            messagebox.showerror("Micrófono de Windows", str(exc))

    def _registrar_diagnostico_audio(self, evento: str, **datos) -> None:
        """Conserva evidencia local de qué ruta probó Windows realmente."""
        carpeta = self._carpeta_grabacion
        if not carpeta:
            return
        registro = {
            "timestamp": time.time(),
            "evento": evento,
            **datos,
        }
        try:
            with (Path(carpeta) / "diagnostico_audio.jsonl").open(
                "a", encoding="utf-8"
            ) as archivo:
                archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _actualizar_reloj(self):
        if not self.grabador or not self.grabador.esta_grabando():
            return
        segundos = int(self.grabador.obtener_duracion())
        h, resto = divmod(segundos, 3600)
        m, s = divmod(resto, 60)
        self.reloj.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        if (
            not self.grabador.esta_pausado()
            and segundos >= 5
            and self.grabador.nivel_maximo < UMBRAL_SENAL_UTIL
        ):
            self.estado.configure(
                text=(
                    "ARGOS está grabando, pero no recibe señal del micrófono. "
                    "Comprueba los permisos o el dispositivo predeterminado de Windows."
                )
            )
        self.after(1000, self._actualizar_reloj)

    def _procesar_cola_ui(self) -> None:
        """Aplica eventos de workers sin permitir llamadas concurrentes a Tk."""
        if self._cerrando:
            return
        procesados = 0
        while procesados < 64:
            try:
                callback, args = self._cola_ui.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args)
            except Exception as exc:
                # Un evento visual fallido no debe detener los siguientes ni
                # bloquear el cierre seguro de una grabación.
                print(f"Error al actualizar la interfaz: {exc}")
            procesados += 1

        nivel = self._nivel_audio_pendiente
        self._nivel_audio_pendiente = None
        if nivel is not None and (
            nivel == 0.0
            or abs(nivel - self._nivel_audio_mostrado) >= 0.003
        ):
            self._actualizar_nivel_audio(nivel)

        try:
            self._bucle_ui_after = self.after(50, self._procesar_cola_ui)
        except Exception:
            self._bucle_ui_after = None

    def _enviar_ui(self, callback, *args) -> None:
        if self._cerrando:
            return
        if threading.get_ident() == self._hilo_ui:
            callback(*args)
            return
        self._cola_ui.put((callback, args))

    def _detener_grabacion(self):
        if self._deteniendo_grabacion:
            return
        self._deteniendo_grabacion = True
        carpeta = self._carpeta_grabacion
        grabador = self.grabador
        incremental = self._transcripcion_incremental
        if carpeta:
            self.repositorio.marcar_estado_grabacion(carpeta, "deteniendo")
        self.btn_detener.configure(state="disabled")
        self.btn_detener.configure(text="Guardando texto pendiente…")
        self.estado_grabacion_global.configure(
            text="●  Guardando", text_color=COLOR_ALERTA
        )
        self.estado.configure(
            text=(
                "Deteniendo el micrófono; cerrando los fragmentos y preparando "
                "la transcripción definitiva…"
            )
        )

        def worker():
            try:
                ruta = grabador.detener() if grabador else None
                if not ruta or not incremental:
                    raise RuntimeError("No se pudo conservar el audio de la grabación.")
                resultado = incremental.finalizar()
                self._enviar_ui(
                    self._grabacion_incremental_finalizada,
                    resultado,
                    grabador.nivel_maximo,
                )
            except Exception as exc:
                if carpeta:
                    self.repositorio.marcar_estado_grabacion(
                        carpeta, "transcripcion_incompleta", str(exc)
                    )
                self._enviar_ui(self._error_final_grabacion, str(exc))

        threading.Thread(
            target=worker, daemon=True, name="argos-cierre-grabacion"
        ).start()

    def _mostrar_transcripcion_incremental(self, segmentos):
        if self._cerrando:
            return
        texto = formatear_transcripcion_continua(segmentos)
        self._texto_grabar_renderizado = actualizar_texto(
            self.texto_grabar,
            texto,
            self._texto_grabar_renderizado,
            seguir_final=not hay_seleccion(self.texto_grabar),
        )

    def _copiar_transcripcion_directo(self) -> None:
        texto = copiar_texto(self, self.texto_grabar)
        self.estado.configure(
            text=(
                "Transcripción copiada al portapapeles."
                if texto
                else "Todavía no hay transcripción que copiar."
            )
        )

    def _abrir_menu_transcripcion(self, evento) -> None:
        menu = Menu(self, tearoff=False)
        seleccion = hay_seleccion(self.texto_grabar)
        menu.add_command(
            label="Copiar selección",
            state="normal" if seleccion else "disabled",
            command=lambda: copiar_texto(
                self, self.texto_grabar, solo_seleccion=True
            ),
        )
        menu.add_command(
            label="Copiar toda la transcripción",
            command=self._copiar_transcripcion_directo,
        )
        try:
            menu.tk_popup(evento.x_root, evento.y_root)
        finally:
            menu.grab_release()

    def _grabacion_incremental_finalizada(
        self, resultado: ResultadoGrabacion, nivel_maximo: float
    ):
        self._restablecer_controles_grabacion()
        if resultado.errores:
            self.estado.configure(
                text="Audio guardado; quedan fragmentos pendientes de recuperar."
            )
            messagebox.showwarning(
                "Grabación protegida",
                "El audio está guardado, pero una parte no pudo transcribirse ahora. "
                "ARGOS la recuperará automáticamente al volver a abrir.\n\n"
                + "\n".join(resultado.errores),
            )
            return
        if not resultado.segmentos:
            self._texto_grabar_renderizado = actualizar_texto(
                self.texto_grabar,
                "No se detectó voz. El audio sí se ha guardado para poder revisarlo.",
                self._texto_grabar_renderizado,
            )
            self.estado.configure(text="Grabación guardada sin voz reconocible.")
            diagnostico = (
                "ARGOS apenas recibió señal del micrófono. Revisa el permiso de "
                "Windows y habla comprobando que la barra azul se mueve."
                if nivel_maximo < UMBRAL_SENAL_UTIL
                else "Llegó señal, pero Whisper no reconoció habla inteligible."
            )
            messagebox.showwarning(
                "No se detectó voz",
                f"{diagnostico}\n\nEl audio está conservado en:\n{resultado.carpeta}",
            )
            self._refrescar_clases()
            return
        self._mostrar_resultados(
            self.texto_grabar, resultado.segmentos, resultado.carpeta
        )

    def _error_final_grabacion(self, error: str):
        self._restablecer_controles_grabacion()
        self.estado.configure(text=f"Audio protegido; cierre incompleto: {error}")
        messagebox.showerror(
            "Grabación",
            f"El audio ya grabado se conserva, pero no pudo cerrarse la clase:\n{error}",
        )

    def _restablecer_controles_grabacion(self):
        self.btn_grabar.configure(state="normal")
        self.btn_otra_entrada.configure(state="disabled", text="Probar otra entrada")
        self.btn_probar_microfono.configure(state="normal", text="Probar")
        self.btn_actualizar_microfonos.configure(state="normal")
        self.selector_microfono.configure(state="readonly")
        self.btn_pausar.configure(state="disabled", text="Pausar")
        self.btn_detener.configure(state="disabled", text="Detener y guardar")
        self.estado_grabacion_global.configure(
            text="●  Sin grabación", text_color=COLOR_TEXTO_SUAVE
        )
        self.reloj.configure(text="00:00:00")
        self._nivel_audio_pendiente = None
        self.nivel.set(0)
        self._nivel_audio_mostrado = 0.0
        if hasattr(self, "etiqueta_nivel"):
            self.etiqueta_nivel.configure(text="Señal: 0 %")
        self._deteniendo_grabacion = False
        self._grabacion_pausada = False
        self._carpeta_grabacion = None
        self._transcripcion_incremental = None
        self._modelo_grabacion_actual = ""
        if (
            self._recarga_modelos_pendiente
            and not self._carga_modelos_en_curso
        ):
            self._recarga_modelos_pendiente = False
            self.after(10, self._cargar_modelos)

    def _abrir_importador_desde_inicio(self):
        self.tabs.set("Importar archivo")
        self.after(50, self._seleccionar_archivo)

    def _seleccionar_archivo(self):
        ruta = filedialog.askopenfilename(
            title="Seleccionar audio, vídeo o documento",
            filetypes=[
                ("Archivos compatibles", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.aac *.opus *.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.mpeg *.mpg *.ts *.pdf *.docx *.txt *.md"),
                ("Vídeos", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.mpeg *.mpg *.ts"),
                ("Audios", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.aac *.opus"),
                ("Documentos", "*.pdf *.docx *.txt *.md"),
                ("Todos", "*.*"),
            ],
        )
        if ruta:
            if Path(ruta).suffix.lower() in EXTENSIONES_ADMITIDAS:
                self.tabs.set("Biblioteca")
                categoria = self.categoria_documentos.get()
                if categoria == "Todas":
                    categoria = "Tratados"
                self._importar_y_procesar_documentos([ruta], categoria)
                return
            if tipo_archivo(ruta) == "desconocido":
                messagebox.showerror(
                    "Importar archivo", "Ese formato no es compatible con ARGOS."
                )
                return
            self.ruta_archivo = ruta
            etiqueta = "Vídeo" if tipo_archivo(ruta) == "video" else "Audio"
            self.etiqueta_archivo.configure(text=f"{etiqueta}: {ruta}")
            if not self.titulo_archivo.get():
                self.titulo_archivo.insert(0, Path(ruta).stem)

    def _transcribir_archivo(self):
        datos = self._datos_clase(self.materia_archivo, self.titulo_archivo)
        if not datos:
            return
        if not self.ruta_archivo:
            messagebox.showinfo("Archivo", "Selecciona primero un audio o un vídeo.")
            return
        self._procesar(self.ruta_archivo, "archivo", *datos)

    def _procesar(self, ruta, tab, materia, titulo):
        if not self.transcriptor or not self.transcriptor.modelos_cargados:
            messagebox.showwarning("Modelos", "Los modelos todavía no están listos.")
            return
        barra = self.progreso_grabar if tab == "grabar" else self.progreso_archivo
        caja = self.texto_grabar if tab == "grabar" else self.texto_archivo
        if caja is self.texto_grabar:
            self._texto_grabar_renderizado = actualizar_texto(
                caja, "", self._texto_grabar_renderizado
            )
        else:
            caja.delete("1.0", "end")
        if tab == "archivo":
            self.btn_seleccionar_archivo.configure(state="disabled")
            self.btn_transcribir_archivo.configure(state="disabled")
            self.estado.configure(text="Preparando el archivo para transcribir…")

        def callback_media(msg, progreso):
            self._enviar_ui(self._progreso, barra, msg, progreso)

        def worker():
            temporal = False
            ruta_procesable = ruta
            tipo_original = "audio"
            try:
                ruta_procesable, temporal, tipo_original = preparar_para_transcripcion(ruta, callback_media)
                segmentos = self.transcriptor.transcribir_archivo(
                    ruta_procesable,
                    callback_progreso=lambda msg, p: self._enviar_ui(
                        self._progreso, barra, msg, max(0.08, p)
                    ),
                    min_hablantes=self.config_obj.min_hablantes,
                    max_hablantes=self.config_obj.max_hablantes,
                )
                # Si el origen era un vídeo, ``ruta_procesable`` es el WAV
                # temporal extraído por FFmpeg. Se copia antes de eliminarlo
                # para que toda clase conserve siempre su fuente de audio.
                fuente_archivable = ruta if tipo_original == "audio" else ruta_procesable
                carpeta = self.repositorio.guardar_clase(materia, titulo, segmentos, fuente_archivable)
                self.config_obj.ultima_materia = materia
                self.config_obj.guardar()
                self._enviar_ui(
                    self._mostrar_resultados, caja, segmentos, carpeta
                )
            except Exception as exc:
                self._enviar_ui(messagebox.showerror, "Transcripción", str(exc))
                self._enviar_ui(barra.set, 0)
            finally:
                if temporal:
                    eliminar_temporal(ruta_procesable)
                if tab == "archivo":
                    self._enviar_ui(
                        self.btn_seleccionar_archivo.configure, {"state": "normal"}
                    )
                    self._enviar_ui(
                        self.btn_transcribir_archivo.configure, {"state": "normal"}
                    )
        threading.Thread(target=worker, daemon=True).start()

    def _progreso(self, barra, mensaje, valor):
        barra.set(valor)
        self.estado.configure(text=mensaje)

    def _mostrar_resultados(self, caja, segmentos, carpeta):
        texto = (
            formatear_transcripcion_continua(segmentos)
            if segmentos
            else "No se detectó voz."
        )
        if caja is self.texto_grabar:
            self._texto_grabar_renderizado = actualizar_texto(
                caja, texto, self._texto_grabar_renderizado
            )
        else:
            caja.delete("1.0", "end")
            caja.insert("end", texto)
        self.progreso_grabar.set(0)
        self.progreso_archivo.set(0)
        self.estado.configure(text=f"Clase guardada: {carpeta}")
        self._refrescar_clases()
        audio = self.repositorio.obtener_audio_clase(carpeta)
        mensaje_audio = (
            "\n\nEl audio completo también está guardado y puede reproducirse "
            "desde «Mis clases»."
            if audio
            else ""
        )
        messagebox.showinfo(
            "Clase guardada",
            f"Se ha archivado correctamente en:\n{carpeta}{mensaje_audio}",
        )

    def _guardar_config(self):
        self.config_obj.hf_token = self.token.get().strip()
        self.config_obj.whisper_model = self.modelo.get()
        self.config_obj.idioma = self.idioma.get()
        self.config_obj.usar_gpu = bool(self.gpu.get())
        valido, mensaje = self.config_obj.validar()
        if not valido:
            messagebox.showerror("Configuración", mensaje)
            return
        self.config_obj.guardar()
        if self.grabador and self.grabador.esta_grabando():
            self._recarga_modelos_pendiente = True
            actual = (
                self.transcriptor.model_size
                if self.transcriptor is not None
                else "modelo actual"
            )
            self.estado_modelos.configure(
                text=(
                    f"Usando {actual} · {self.config_obj.whisper_model} "
                    "se cargará al terminar"
                ),
                text_color=COLOR_ALERTA,
            )
            self.estado.configure(
                text="Configuración guardada; la grabación continúa sin cambiar de motor."
            )
            return
        self._cargar_modelos()

    def _cargar_modelos(self):
        objetivo = self.config_obj.whisper_model
        if self._carga_modelos_en_curso:
            self._recarga_modelos_pendiente = True
            actual = (
                self._modelo_grabacion_actual
                or getattr(self.transcriptor, "model_size", "modelo actual")
            )
            self.estado_modelos.configure(
                text=f"Usando {actual} · {objetivo} pendiente",
                text_color=COLOR_ALERTA,
            )
            return
        self._carga_modelos_en_curso = True
        solicitud = (
            self.config_obj.hf_token,
            objetivo,
            self.config_obj.usar_gpu,
            self.config_obj.idioma,
        )
        actual = getattr(self.transcriptor, "model_size", "")
        texto_carga = (
            f"Usando {actual} · cargando {objetivo}…"
            if actual
            else f"Cargando {objetivo}…"
        )
        self.estado_modelos.configure(
            text=texto_carga, text_color=COLOR_ALERTA
        )

        def worker():
            try:
                motor = TranscriptorClases(*solicitud)

                def informar_carga(mensaje, progreso):
                    if not (self.grabador and self.grabador.esta_grabando()):
                        self._enviar_ui(
                            self.estado.configure, {"text": mensaje}
                        )
                    self._registrar_progreso_modelos(mensaje, progreso)

                motor.cargar_modelos(informar_carga)
                texto = f"Listo · {motor.dispositivo_real.upper()}" + (
                    " · diarización" if motor.diarizacion_disponible else ""
                )
                self._registrar_resultado_modelos(True, texto)
                self._enviar_ui(
                    self._fin_carga_modelos, motor, None, solicitud
                )
            except Exception as exc:
                self._registrar_resultado_modelos(False, str(exc))
                self._enviar_ui(
                    self._fin_carga_modelos, None, str(exc), solicitud
                )
        threading.Thread(target=worker, daemon=True).start()

    def _fin_carga_modelos(self, motor, error: str | None, solicitud) -> None:
        self._carga_modelos_en_curso = False
        grabando = bool(self.grabador and self.grabador.esta_grabando())
        if error:
            actual = getattr(self.transcriptor, "model_size", "")
            self.estado_modelos.configure(
                text=(f"Usando {actual} · error al cargar" if actual else "Error"),
                text_color=COLOR_PELIGRO,
            )
            if not grabando:
                self.estado.configure(text=error)
        else:
            self.transcriptor = motor
            if grabando and self._modelo_grabacion_actual:
                texto = (
                    f"Grabando con {self._modelo_grabacion_actual} · "
                    f"{motor.model_size} listo para la próxima clase"
                )
            else:
                texto = f"Listo · {motor.model_size} · {motor.dispositivo_real.upper()}" + (
                    " · diarización" if motor.diarizacion_disponible else ""
                )
            self.estado_modelos.configure(
                text=texto, text_color=COLOR_EXITO
            )
            if not grabando:
                self.estado.configure(text="Listo para grabar o transcribir.")
                self._recuperar_grabaciones_interrumpidas()

        actual_solicitado = (
            self.config_obj.hf_token,
            self.config_obj.whisper_model,
            self.config_obj.usar_gpu,
            self.config_obj.idioma,
        )
        if self._recarga_modelos_pendiente and actual_solicitado != solicitud:
            if grabando:
                return
            self._recarga_modelos_pendiente = False
            self.after(10, self._cargar_modelos)
        elif actual_solicitado == solicitud:
            self._recarga_modelos_pendiente = False

    def _recuperar_grabaciones_interrumpidas(self):
        if self._recuperacion_grabaciones_activa or not self.transcriptor:
            return
        pendientes = self.repositorio.grabaciones_interrumpidas()
        if not pendientes:
            return
        self._recuperacion_grabaciones_activa = True
        self.estado.configure(
            text=(
                f"Recuperando automáticamente {len(pendientes)} grabación(es) "
                "interrumpida(s)…"
            )
        )

        def worker():
            recuperadas = 0
            errores = []
            for carpeta in pendientes:
                try:
                    ficha = json.loads(
                        (carpeta / "ficha.json").read_text(encoding="utf-8")
                    )
                    sample_rate = int(
                        ficha.get("sample_rate", self.config_obj.sample_rate)
                    )
                    recuperar_audio_interrumpido(
                        carpeta / "audio.wav",
                        carpeta / "fragmentos_audio",
                        sample_rate,
                        10.0,
                    )
                    incremental = TranscripcionIncremental(
                        self.transcriptor,
                        self.repositorio,
                        carpeta,
                        callback_estado=lambda mensaje: self._enviar_ui(
                            self.estado.configure, {"text": mensaje}
                        ),
                        consolidar_audio_completo=True,
                        min_hablantes=self.config_obj.min_hablantes,
                        max_hablantes=self.config_obj.max_hablantes,
                    )
                    incremental.encolar_varios(
                        self.repositorio.fragmentos_pendientes(carpeta)
                    )
                    resultado = incremental.finalizar()
                    if resultado.completa:
                        recuperadas += 1
                        self._enviar_ui(self._grabacion_recuperada, resultado)
                    else:
                        errores.extend(resultado.errores)
                except Exception as exc:
                    errores.append(f"{carpeta.name}: {exc}")
                    self.repositorio.marcar_estado_grabacion(
                        carpeta, "transcripcion_incompleta", str(exc)
                    )
            self._enviar_ui(
                self._fin_recuperacion_grabaciones,
                recuperadas,
                errores,
            )

        threading.Thread(
            target=worker, daemon=True, name="argos-recuperacion-grabaciones"
        ).start()

    def _grabacion_recuperada(self, resultado: ResultadoGrabacion):
        self._refrescar_clases()
        if resultado.segmentos and hasattr(self, "_encolar_pipeline"):
            self._actualizar_selector_pipeline()
            self._encolar_pipeline(resultado.carpeta, automatico=True)

    def _fin_recuperacion_grabaciones(self, recuperadas: int, errores: list[str]):
        self._recuperacion_grabaciones_activa = False
        if errores:
            self.estado.configure(
                text=(
                    f"Se recuperaron {recuperadas} grabaciones; "
                    f"{len(errores)} siguen pendientes."
                )
            )
            return
        self.estado.configure(
            text=f"Grabaciones recuperadas automáticamente: {recuperadas}."
        )

    @staticmethod
    def _registrar_progreso_modelos(detalle: str, progreso: float) -> None:
        """Deja diagnóstico de arranque para CI sin alterar la señal final."""
        registrar_diagnostico_arranque(
            "cargando_modelos", detalle, progreso
        )

    @staticmethod
    def _registrar_resultado_modelos(exito: bool, detalle: str) -> None:
        """Expone al smoke test de Windows el resultado real de la carga."""
        destino = os.environ.get("ARGOS_READY_FILE", "").strip()
        if not destino:
            return
        AsistenteClasesApp._escribir_estado_modelos(
            Path(destino),
            {"modelos_cargados": exito, "detalle": detalle},
        )

    @staticmethod
    def _escribir_estado_modelos(ruta: Path, datos: dict) -> None:
        temporal = ruta.with_suffix(ruta.suffix + ".tmp")
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            temporal.write_text(
                json.dumps(datos, ensure_ascii=False),
                encoding="utf-8",
            )
            temporal.replace(ruta)
        except OSError:
            pass

    def _cerrar(self):
        self._cerrando = True
        if self._bucle_ui_after is not None:
            try:
                self.after_cancel(self._bucle_ui_after)
            except Exception:
                pass
            self._bucle_ui_after = None
        if self.grabador and self.grabador.esta_grabando():
            if self._carpeta_grabacion:
                self.repositorio.marcar_estado_grabacion(
                    self._carpeta_grabacion,
                    "interrumpida",
                    "ARGOS se cerró durante la grabación; recuperación pendiente.",
                )
            self.grabador.detener()
        if self._transcripcion_incremental:
            self._transcripcion_incremental.cerrar_sin_esperar()
        self.destroy()
