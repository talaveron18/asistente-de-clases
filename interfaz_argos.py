from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

import customtkinter as ctk


COLOR_FONDO = "#0B1120"
COLOR_BARRA = "#111827"
COLOR_PANEL = "#151E2E"
COLOR_PANEL_SUAVE = "#1B2638"
COLOR_BORDE = "#273449"
COLOR_TEXTO = "#F3F6FA"
COLOR_TEXTO_SUAVE = "#9EACC0"
COLOR_ACENTO = "#4F8EF7"
COLOR_ACENTO_HOVER = "#3978DD"
COLOR_EXITO = "#35C48D"
COLOR_ALERTA = "#F5B942"
COLOR_PELIGRO = "#EF5A67"

MATERIALES_CLASE = {
    "Resumen": ("repaso_rapido.md", "analisis_clase.md"),
    "Apuntes": (
        "apuntes_estudio_argos.md",
        "apuntes_argos_enriquecidos.md",
        "apuntes_argos.md",
    ),
    "Transcripción": (
        "transcripcion_medica_revisada.txt",
        "transcripcion.txt",
    ),
    "Preguntas": ("preguntas_repaso.md",),
    "Tarjetas": ("flashcards_argos.tsv",),
    "Fuentes": ("trazabilidad_argos.md",),
}

ARCHIVOS_MATERIAL_COMPLETO = (
    "apuntes_estudio_argos.md",
    "preguntas_repaso.md",
    "flashcards_argos.tsv",
    "repaso_rapido.md",
    "trazabilidad_argos.json",
    "trazabilidad_argos.md",
)


@dataclass(frozen=True)
class EstadoMaterialClase:
    clave: str
    etiqueta: str
    detalle: str


def leer_estado_material_clase(carpeta: str | Path) -> EstadoMaterialClase:
    """Resume el estado persistente sin confundir archivos parciales con éxito."""
    carpeta = Path(carpeta)
    estado = {}
    try:
        estado = json.loads(
            (carpeta / "estado_argos.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        pass

    clave = estado.get("estado")
    if clave == "procesando":
        pasos = estado.get("pasos") or []
        paso = next(
            (
                str(item.get("nombre", ""))
                for item in reversed(pasos)
                if item.get("estado") == "procesando"
            ),
            "",
        )
        detalle = f"Paso actual: {paso.replace('_', ' ')}." if paso else "Procesamiento en curso."
        return EstadoMaterialClase("procesando", "Procesando material", detalle)
    if clave == "error":
        error = estado.get("error") or {}
        return EstadoMaterialClase(
            "error",
            "Requiere revisión",
            str(error.get("mensaje") or "El procesamiento no terminó."),
        )

    completos = all((carpeta / nombre).is_file() for nombre in ARCHIVOS_MATERIAL_COMPLETO)
    if completos:
        detalle = "Apuntes, repaso, preguntas, tarjetas y fuentes disponibles."
        try:
            trazabilidad = json.loads(
                (carpeta / "trazabilidad_argos.json").read_text(encoding="utf-8")
            )
            metricas = trazabilidad.get("metricas", {})
            cobertura = metricas.get("cobertura_documental_porcentaje")
            contestadas = metricas.get("preguntas_con_respuesta_explicitada")
            preguntas = metricas.get("preguntas")
            if isinstance(cobertura, (int, float)):
                detalle += f" Cobertura documental: {cobertura:g} %."
            if isinstance(contestadas, int) and isinstance(preguntas, int):
                detalle += (
                    f" Respuestas explícitas localizadas: {contestadas} de {preguntas}."
                )
        except (OSError, json.JSONDecodeError):
            pass
        return EstadoMaterialClase(
            "listo",
            "Material listo",
            detalle,
        )
    if clave == "completado":
        return EstadoMaterialClase(
            "incompleto",
            "Material incompleto",
            "El proceso terminó, pero falta algún archivo obligatorio.",
        )

    transcripcion = carpeta / "transcripcion.txt"
    try:
        tiene_texto = transcripcion.is_file() and bool(
            transcripcion.read_text(encoding="utf-8", errors="replace").strip()
        )
    except OSError:
        tiene_texto = False
    if tiene_texto:
        return EstadoMaterialClase(
            "pendiente",
            "Pendiente de procesar",
            "La transcripción está guardada y aún no tiene todo el material.",
        )
    if any(carpeta.glob("audio.*")):
        return EstadoMaterialClase(
            "transcribiendo",
            "Audio guardado",
            "La transcripción todavía no está disponible.",
        )
    return EstadoMaterialClase(
        "pendiente",
        "Clase pendiente",
        "Todavía no hay material de estudio disponible.",
    )


def leer_material_clase(carpeta: str | Path, seccion: str) -> tuple[Path | None, str]:
    """Devuelve el material más elaborado disponible para una ficha de clase."""
    carpeta = Path(carpeta)
    for nombre in MATERIALES_CLASE.get(seccion, ()):
        archivo = carpeta / nombre
        if not archivo.exists():
            continue
        try:
            return archivo, archivo.read_text(encoding="utf-8")
        except OSError as exc:
            return archivo, f"No se pudo abrir {nombre}: {exc}"
    return None, (
        "Este material aún no está disponible. "
        "Pulsa «Actualizar material» para generarlo."
    )


def preparar_material_para_lectura(
    contenido: str, seccion: str
) -> list[tuple[str, str]]:
    """Convierte Markdown/TSV técnico en fragmentos legibles para la ficha."""
    if seccion == "Transcripción":
        return [(contenido, "cuerpo")]
    if seccion == "Tarjetas":
        return _preparar_tarjetas(contenido)

    fragmentos: list[tuple[str, str]] = []
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?", limpia):
            continue
        if limpia.startswith("### "):
            fragmentos.append((_limpiar_markdown(limpia[4:]) + "\n", "titulo3"))
        elif limpia.startswith("## "):
            fragmentos.append((_limpiar_markdown(limpia[3:]) + "\n", "titulo2"))
        elif limpia.startswith("# "):
            fragmentos.append((_limpiar_markdown(limpia[2:]) + "\n", "titulo1"))
        elif limpia.startswith("> "):
            fragmentos.append((_limpiar_markdown(limpia[2:]) + "\n", "nota"))
        elif limpia.startswith("|") and limpia.endswith("|"):
            celdas = [
                _limpiar_markdown(celda.strip())
                for celda in limpia.strip("|").split("|")
            ]
            fragmentos.append(("  ·  ".join(celdas) + "\n", "tabla"))
        elif re.match(r"^[-*]\s+", limpia):
            fragmentos.append(("• " + _limpiar_markdown(limpia[2:]) + "\n", "lista"))
        elif limpia:
            fragmentos.append((_limpiar_markdown(linea) + "\n", "cuerpo"))
        else:
            fragmentos.append(("\n", "cuerpo"))
    return fragmentos or [(contenido, "cuerpo")]


def _limpiar_markdown(texto: str) -> str:
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto)
    texto = re.sub(r"`(.+?)`", r"\1", texto)
    return texto.replace("\\|", "|").strip()


def _preparar_tarjetas(contenido: str) -> list[tuple[str, str]]:
    filas = list(csv.reader(io.StringIO(contenido), delimiter="\t"))
    if filas and [x.casefold() for x in filas[0][:2]] == ["frente", "dorso"]:
        filas = filas[1:]
    fragmentos: list[tuple[str, str]] = []
    for numero, fila in enumerate(filas, 1):
        if len(fila) < 2:
            continue
        minuto = fila[2].strip() if len(fila) > 2 else ""
        fragmentos.extend(
            [
                (f"Tarjeta {numero}\n", "titulo3"),
                (fila[0].strip() + "\n", "pregunta"),
                (fila[1].strip() + "\n", "cuerpo"),
                ((f"Referencia: {minuto}\n" if minuto else ""), "nota"),
                ("\n", "cuerpo"),
            ]
        )
    return fragmentos or [("No hay tarjetas disponibles.\n", "cuerpo")]


class NavegacionArgos(ctk.CTkFrame):
    """Navegación lateral con una API mínima compatible con ``CTkTabview``."""

    ORDEN = [
        "Inicio",
        "Grabar clase",
        "Importar archivo",
        "Mis clases",
        "Biblioteca",
        "Chat ARGOS",
        "Procesar clase",
        "Configuración",
    ]
    ETIQUETAS = {
        "Inicio": "Inicio",
        "Grabar clase": "Grabar clase",
        "Importar archivo": "Importar archivo",
        "Mis clases": "Mis clases",
        "Biblioteca": "Biblioteca",
        "Chat ARGOS": "Preguntar a ARGOS",
        "Procesar clase": "Estado y procesos",
        "Configuración": "Configuración",
        "Detalle de clase": "Clase",
    }
    ICONOS = {
        "Inicio": "⌂",
        "Grabar clase": "●",
        "Importar archivo": "＋",
        "Mis clases": "▤",
        "Biblioteca": "▦",
        "Chat ARGOS": "✦",
        "Procesar clase": "↻",
        "Configuración": "⚙",
    }

    def __init__(self, parent):
        super().__init__(parent, fg_color=COLOR_FONDO, corner_radius=0)
        self.pack(fill="both", expand=True)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.paginas: dict[str, ctk.CTkFrame] = {}
        self.botones: dict[str, ctk.CTkButton] = {}
        self.actual = ""

        self.barra = ctk.CTkFrame(
            self, width=222, corner_radius=0, fg_color=COLOR_BARRA
        )
        self.barra.grid(row=0, column=0, sticky="nsew")
        self.barra.grid_propagate(False)

        marca = ctk.CTkFrame(self.barra, fg_color="transparent")
        marca.pack(fill="x", padx=20, pady=(22, 20))
        ctk.CTkLabel(
            marca,
            text="ARGOS",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=24, weight="bold"),
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            marca,
            text="Memoria de estudio",
            text_color=COLOR_TEXTO_SUAVE,
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).pack(fill="x", pady=(1, 0))

        self.menu_principal = ctk.CTkFrame(self.barra, fg_color="transparent")
        self.menu_principal.pack(fill="x", padx=10)
        self.menu_pie = ctk.CTkFrame(self.barra, fg_color="transparent")
        self.menu_pie.pack(side="bottom", fill="x", padx=10, pady=14)

        self.area = ctk.CTkFrame(self, fg_color=COLOR_FONDO, corner_radius=0)
        self.area.grid(row=0, column=1, sticky="nsew")
        self.area.grid_rowconfigure(1, weight=1)
        self.area.grid_columnconfigure(0, weight=1)

        self.cabecera = ctk.CTkFrame(
            self.area,
            height=76,
            corner_radius=0,
            fg_color=COLOR_BARRA,
            border_width=0,
        )
        self.cabecera.grid(row=0, column=0, sticky="ew")
        self.cabecera.grid_propagate(False)

        self.titulo = ctk.CTkLabel(
            self.cabecera,
            text="Inicio",
            text_color=COLOR_TEXTO,
            font=ctk.CTkFont(size=19, weight="bold"),
            anchor="w",
        )
        self.titulo.pack(side="left", padx=24)

        self.contenido = ctk.CTkFrame(
            self.area, fg_color=COLOR_FONDO, corner_radius=0
        )
        self.contenido.grid(row=1, column=0, sticky="nsew")
        self.contenido.grid_rowconfigure(0, weight=1)
        self.contenido.grid_columnconfigure(0, weight=1)

    def add(self, nombre: str, visible: bool = True):
        if nombre in self.paginas:
            return self.paginas[nombre]
        pagina = ctk.CTkFrame(
            self.contenido, fg_color=COLOR_FONDO, corner_radius=0
        )
        pagina.grid(row=0, column=0, sticky="nsew")
        self.paginas[nombre] = pagina
        if visible:
            destino = self.menu_pie if nombre == "Configuración" else self.menu_principal
            boton = ctk.CTkButton(
                destino,
                text=f"{self.ICONOS.get(nombre, '·')}   {self.ETIQUETAS.get(nombre, nombre)}",
                command=lambda n=nombre: self.set(n),
                height=42,
                corner_radius=9,
                anchor="w",
                fg_color="transparent",
                hover_color=COLOR_PANEL_SUAVE,
                text_color=COLOR_TEXTO_SUAVE,
                font=ctk.CTkFont(size=13),
            )
            self.botones[nombre] = boton
            self._reordenar()
        if not self.actual:
            self.set(nombre)
        return pagina

    def _reordenar(self):
        for boton in self.botones.values():
            boton.pack_forget()
        for nombre in self.ORDEN:
            boton = self.botones.get(nombre)
            if boton is not None:
                boton.pack(fill="x", pady=3)

    def set(self, nombre: str):
        pagina = self.paginas.get(nombre)
        if pagina is None:
            raise ValueError(f"No existe la vista {nombre!r}")
        pagina.tkraise()
        self.actual = nombre
        self.titulo.configure(text=self.ETIQUETAS.get(nombre, nombre))
        for clave, boton in self.botones.items():
            seleccionado = clave == nombre
            boton.configure(
                fg_color=COLOR_PANEL_SUAVE if seleccionado else "transparent",
                text_color=COLOR_TEXTO if seleccionado else COLOR_TEXTO_SUAVE,
            )

    def get(self) -> str:
        return self.actual


def titulo_seccion(parent, titulo: str, descripcion: str = ""):
    bloque = ctk.CTkFrame(parent, fg_color="transparent")
    bloque.pack(fill="x", padx=24, pady=(22, 12))
    ctk.CTkLabel(
        bloque,
        text=titulo,
        text_color=COLOR_TEXTO,
        font=ctk.CTkFont(size=24, weight="bold"),
        anchor="w",
    ).pack(fill="x")
    if descripcion:
        ctk.CTkLabel(
            bloque,
            text=descripcion,
            text_color=COLOR_TEXTO_SUAVE,
            font=ctk.CTkFont(size=13),
            anchor="w",
            justify="left",
            wraplength=820,
        ).pack(fill="x", pady=(4, 0))
    return bloque


def tarjeta(parent, **kwargs):
    opciones = {
        "fg_color": COLOR_PANEL,
        "corner_radius": 14,
        "border_width": 1,
        "border_color": COLOR_BORDE,
    }
    opciones.update(kwargs)
    return ctk.CTkFrame(parent, **opciones)
