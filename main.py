from __future__ import annotations

import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from biblioteca_medica import BibliotecaMedica, CATEGORIAS
from config import Config
from grabador import GrabadorAudio
from media_utils import eliminar_temporal, preparar_para_transcripcion, tipo_archivo
from repositorio import RepositorioClases
from transcriptor import TranscriptorClases

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class AsistenteClasesApp(ctk.CTk):
    def __init__(self):
        super().__init__()
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

        self._crear_interfaz()
        self._cargar_modelos()

    def _crear_interfaz(self):
        cabecera = ctk.CTkFrame(self, height=54, corner_radius=0)
        cabecera.pack(fill="x")
        cabecera.pack_propagate(False)
        ctk.CTkLabel(
            cabecera, text="ARGOS · Asistente de Clases",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left", padx=18)
        self.estado_modelos = ctk.CTkLabel(cabecera, text="Preparando...", text_color="#ffb300")
        self.estado_modelos.pack(side="right", padx=18)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=12)
        self.tab_grabar = self.tabs.add("Grabar")
        self.tab_archivo = self.tabs.add("Audio o vídeo")
        self.tab_clases = self.tabs.add("Clases")
        self.tab_medica = self.tabs.add("Biblioteca médica")
        self.tab_config = self.tabs.add("Configuración")

        self._tab_grabacion()
        self._tab_archivo_multimedia()
        self._tab_biblioteca_clases()
        self._tab_biblioteca_medica()
        self._tab_configuracion()

        self.estado = ctk.CTkLabel(self, text="Inicializando...", anchor="w")
        self.estado.pack(fill="x", padx=16, pady=(0, 10))

    def _campos_clase(self, parent):
        marco = ctk.CTkFrame(parent)
        marco.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(marco, text="Materia").grid(row=0, column=0, padx=(12, 6), pady=10)
        materia = ctk.CTkComboBox(marco, values=self.repositorio.materias() or [""], width=260)
        materia.grid(row=0, column=1, padx=6, pady=10, sticky="ew")
        materia.set(self.config_obj.ultima_materia or "")
        ctk.CTkLabel(marco, text="Título").grid(row=0, column=2, padx=(18, 6), pady=10)
        titulo = ctk.CTkEntry(marco, placeholder_text="Ej.: Inflamación aguda")
        titulo.grid(row=0, column=3, padx=(6, 12), pady=10, sticky="ew")
        marco.grid_columnconfigure(3, weight=1)
        return materia, titulo

    def _tab_grabacion(self):
        self.materia_grabar, self.titulo_grabar = self._campos_clase(self.tab_grabar)
        panel = ctk.CTkFrame(self.tab_grabar)
        panel.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkLabel(panel, text="Micrófono:").pack(side="left", padx=(12, 6), pady=12)
        self.combo_micro = ctk.CTkComboBox(panel, width=430)
        self.combo_micro.pack(side="left", padx=6)
        valores = [f"{i}: {nombre}" for i, nombre in GrabadorAudio.listar_dispositivos()] or ["Sin dispositivos detectados"]
        self.combo_micro.configure(values=valores)
        self.combo_micro.set(valores[0])

        controles = ctk.CTkFrame(self.tab_grabar, fg_color="transparent")
        controles.pack(fill="x", padx=14)
        self.btn_grabar = ctk.CTkButton(
            controles, text="Iniciar grabación", command=self._iniciar_grabacion, fg_color="#c62828"
        )
        self.btn_grabar.pack(side="left", padx=(0, 8))
        self.btn_detener = ctk.CTkButton(
            controles, text="Detener, transcribir y guardar",
            command=self._detener_grabacion, state="disabled", fg_color="#2e7d32"
        )
        self.btn_detener.pack(side="left")
        self.reloj = ctk.CTkLabel(controles, text="00:00:00", font=ctk.CTkFont(size=20, weight="bold"))
        self.reloj.pack(side="right")
        self.nivel = ctk.CTkProgressBar(self.tab_grabar)
        self.nivel.pack(fill="x", padx=14, pady=12)
        self.nivel.set(0)
        self.progreso_grabar = ctk.CTkProgressBar(self.tab_grabar)
        self.progreso_grabar.pack(fill="x", padx=14, pady=(0, 10))
        self.progreso_grabar.set(0)
        self.texto_grabar = ctk.CTkTextbox(self.tab_grabar, font=ctk.CTkFont(size=13))
        self.texto_grabar.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def _tab_archivo_multimedia(self):
        self.materia_archivo, self.titulo_archivo = self._campos_clase(self.tab_archivo)
        panel = ctk.CTkFrame(self.tab_archivo)
        panel.pack(fill="x", padx=14, pady=(0, 10))
        self.etiqueta_archivo = ctk.CTkLabel(panel, text="Ningún audio o vídeo seleccionado", anchor="w")
        self.etiqueta_archivo.pack(side="left", fill="x", expand=True, padx=12, pady=12)
        ctk.CTkButton(panel, text="Seleccionar audio o vídeo", command=self._seleccionar_archivo).pack(side="left", padx=6)
        ctk.CTkButton(panel, text="Transcribir y guardar", command=self._transcribir_archivo).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            self.tab_archivo,
            text="Admite vídeos largos. Solo usa su audio y no copia el vídeo original.",
            text_color="#aaaaaa", anchor="w"
        ).pack(fill="x", padx=18, pady=(0, 8))
        self.progreso_archivo = ctk.CTkProgressBar(self.tab_archivo)
        self.progreso_archivo.pack(fill="x", padx=14, pady=(0, 10))
        self.progreso_archivo.set(0)
        self.texto_archivo = ctk.CTkTextbox(self.tab_archivo, font=ctk.CTkFont(size=13))
        self.texto_archivo.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def _tab_biblioteca_clases(self):
        superior = ctk.CTkFrame(self.tab_clases)
        superior.pack(fill="x", padx=14, pady=14)
        self.buscar_clases = ctk.CTkEntry(superior, placeholder_text="Buscar por materia, título o fecha...")
        self.buscar_clases.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=12)
        ctk.CTkButton(superior, text="Buscar", command=self._refrescar_clases, width=90).pack(side="left", padx=6)
        ctk.CTkButton(
            superior, text="Abrir carpeta general", command=self.repositorio.abrir_raiz, width=150
        ).pack(side="left", padx=(6, 12))
        self.lista_clases = ctk.CTkScrollableFrame(self.tab_clases)
        self.lista_clases.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._refrescar_clases()

    def _refrescar_clases(self):
        for widget in self.lista_clases.winfo_children():
            widget.destroy()
        filtro = self.buscar_clases.get() if hasattr(self, "buscar_clases") else ""
        clases = self.repositorio.listar_clases(filtro)
        if not clases:
            ctk.CTkLabel(self.lista_clases, text="Todavía no hay clases guardadas.").pack(pady=30)
            return
        for clase in clases:
            fila = ctk.CTkFrame(self.lista_clases)
            fila.pack(fill="x", pady=4)
            fecha = clase.get("fecha_iso", "").replace("T", " ")[:16]
            texto = f"{clase.get('numero', 0):03d} · {clase.get('materia', '')} · {clase.get('titulo', '')} · {fecha}"
            ctk.CTkLabel(fila, text=texto, anchor="w").pack(side="left", fill="x", expand=True, padx=12, pady=10)
            ctk.CTkButton(
                fila, text="Abrir", width=80,
                command=lambda r=clase["ruta"]: self.repositorio.abrir_carpeta(r)
            ).pack(side="right", padx=10)

    def _tab_biblioteca_medica(self):
        superior = ctk.CTkFrame(self.tab_medica)
        superior.pack(fill="x", padx=14, pady=14)

        self.buscar_documentos = ctk.CTkEntry(superior, placeholder_text="Buscar tratado, apunte, examen...")
        self.buscar_documentos.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=12)
        self.categoria_documentos = ctk.CTkComboBox(superior, values=["Todas", *CATEGORIAS], width=130)
        self.categoria_documentos.set("Todas")
        self.categoria_documentos.pack(side="left", padx=6)
        ctk.CTkButton(superior, text="Buscar", command=self._refrescar_documentos, width=80).pack(side="left", padx=6)
        ctk.CTkButton(superior, text="Importar", command=self._importar_documentos, width=90).pack(side="left", padx=6)
        ctk.CTkButton(
            superior, text="Abrir carpeta", command=self.biblioteca_medica.abrir_raiz, width=110
        ).pack(side="left", padx=(6, 12))

        acciones = ctk.CTkFrame(self.tab_medica, fg_color="transparent")
        acciones.pack(fill="x", padx=14, pady=(0, 8))
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
        ).pack(fill="x", padx=18, pady=(0, 8))

        self.lista_documentos = ctk.CTkScrollableFrame(self.tab_medica)
        self.lista_documentos.pack(fill="both", expand=True, padx=14, pady=(0, 14))
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
        nuevos, repetidos, errores = 0, 0, []
        for ruta in rutas:
            try:
                _, creado = self.biblioteca_medica.importar_archivo(ruta, categoria)
                nuevos += int(creado)
                repetidos += int(not creado)
            except Exception as exc:
                errores.append(f"{Path(ruta).name}: {exc}")
        self._refrescar_documentos()
        mensaje = f"Importados: {nuevos}. Ya existentes: {repetidos}."
        if errores:
            mensaje += "\n\nErrores:\n" + "\n".join(errores[:5])
        messagebox.showinfo("Biblioteca médica", mensaje)

    def _procesar_un_documento(self, item_id):
        def worker():
            try:
                self.biblioteca_medica.procesar_documento(
                    item_id,
                    lambda msg, p: self.after(0, self._actualizar_progreso_documentos, msg, p)
                )
                self.after(0, self._refrescar_documentos)
            except Exception as exc:
                self.after(0, messagebox.showerror, "Extracción documental", str(exc))
            finally:
                self.after(0, self._actualizar_progreso_documentos, "Finalizado", 0)
        threading.Thread(target=worker, daemon=True).start()

    def _procesar_documentos_pendientes(self):
        def worker():
            try:
                self.biblioteca_medica.procesar_pendientes(
                    lambda msg, p: self.after(0, self._actualizar_progreso_documentos, msg, p)
                )
                self.after(0, self._refrescar_documentos)
                self.after(0, messagebox.showinfo, "Biblioteca médica", "Extracción de texto completada.")
            except Exception as exc:
                self.after(0, messagebox.showerror, "Extracción documental", str(exc))
            finally:
                self.after(0, self._actualizar_progreso_documentos, "Finalizado", 0)
        threading.Thread(target=worker, daemon=True).start()

    def _actualizar_progreso_documentos(self, mensaje, valor):
        self.estado_documentos.configure(text=mensaje)
        self.progreso_documentos.set(valor)

    def _tab_configuracion(self):
        marco = ctk.CTkScrollableFrame(self.tab_config)
        marco.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(marco, text="Token de Hugging Face (opcional)", anchor="w").pack(fill="x", pady=(8, 4))
        self.token = ctk.CTkEntry(marco, show="*")
        self.token.pack(fill="x", pady=(0, 12))
        self.token.insert(0, self.config_obj.hf_token)
        ctk.CTkLabel(marco, text="Modelo Whisper", anchor="w").pack(fill="x")
        self.modelo = ctk.CTkComboBox(marco, values=["tiny", "base", "small", "medium", "large-v3"])
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

    def _indice_microfono(self):
        try:
            return int(self.combo_micro.get().split(":", 1)[0])
        except (ValueError, IndexError):
            return None

    def _iniciar_grabacion(self):
        if not self._datos_clase(self.materia_grabar, self.titulo_grabar):
            return
        if not self.transcriptor or not self.transcriptor.modelos_cargados:
            messagebox.showwarning("Modelos", "Los modelos todavía no están listos.")
            return
        self.grabador = GrabadorAudio(self.config_obj.sample_rate, self._indice_microfono())
        ok = self.grabador.iniciar(
            lambda n: self.after(0, self.nivel.set, n),
            self.config_obj.obtener_ruta_temp(),
        )
        if not ok:
            messagebox.showerror("Audio", self.grabador.ultimo_error or "No se pudo iniciar la grabación.")
            return
        self._grabando_desde = time.time()
        self.btn_grabar.configure(state="disabled")
        self.btn_detener.configure(state="normal")
        self.estado.configure(text="Grabando...")
        self._actualizar_reloj()

    def _actualizar_reloj(self):
        if not self.grabador or not self.grabador.esta_grabando():
            return
        segundos = int(time.time() - self._grabando_desde)
        h, resto = divmod(segundos, 3600)
        m, s = divmod(resto, 60)
        self.reloj.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.after(1000, self._actualizar_reloj)

    def _detener_grabacion(self):
        datos = self._datos_clase(self.materia_grabar, self.titulo_grabar)
        ruta = self.grabador.detener() if self.grabador else None
        self.btn_grabar.configure(state="normal")
        self.btn_detener.configure(state="disabled")
        self.nivel.set(0)
        if ruta and datos:
            self._procesar(ruta, "grabar", *datos)

    def _seleccionar_archivo(self):
        ruta = filedialog.askopenfilename(
            title="Seleccionar audio o vídeo",
            filetypes=[
                ("Audio y vídeo", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.aac *.opus *.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.mpeg *.mpg *.ts"),
                ("Vídeos", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.mpeg *.mpg *.ts"),
                ("Audios", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma *.aac *.opus"),
                ("Todos", "*.*"),
            ],
        )
        if ruta:
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
        caja.delete("1.0", "end")

        def callback_media(msg, progreso):
            self.after(0, self._progreso, barra, msg, progreso)

        def worker():
            temporal = False
            ruta_procesable = ruta
            tipo_original = "audio"
            try:
                ruta_procesable, temporal, tipo_original = preparar_para_transcripcion(ruta, callback_media)
                segmentos = self.transcriptor.transcribir_archivo(
                    ruta_procesable,
                    callback_progreso=lambda msg, p: self.after(0, self._progreso, barra, msg, max(0.08, p)),
                    min_hablantes=self.config_obj.min_hablantes,
                    max_hablantes=self.config_obj.max_hablantes,
                )
                fuente_archivable = ruta if tipo_original == "audio" else None
                carpeta = self.repositorio.guardar_clase(materia, titulo, segmentos, fuente_archivable)
                self.config_obj.ultima_materia = materia
                self.config_obj.guardar()
                self.after(0, self._mostrar_resultados, caja, segmentos, carpeta)
            except Exception as exc:
                self.after(0, messagebox.showerror, "Transcripción", str(exc))
                self.after(0, barra.set, 0)
            finally:
                if temporal:
                    eliminar_temporal(ruta_procesable)
        threading.Thread(target=worker, daemon=True).start()

    def _progreso(self, barra, mensaje, valor):
        barra.set(valor)
        self.estado.configure(text=mensaje)

    def _mostrar_resultados(self, caja, segmentos, carpeta):
        caja.delete("1.0", "end")
        caja.insert("end", "\n".join(s.a_linea_txt() for s in segmentos) if segmentos else "No se detectó voz.")
        self.progreso_grabar.set(0)
        self.progreso_archivo.set(0)
        self.estado.configure(text=f"Clase guardada: {carpeta}")
        self._refrescar_clases()
        messagebox.showinfo("Clase guardada", f"Se ha archivado correctamente en:\n{carpeta}")

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
        self._cargar_modelos()

    def _cargar_modelos(self):
        self.estado_modelos.configure(text="Cargando modelos...", text_color="#ffb300")
        def worker():
            try:
                motor = TranscriptorClases(
                    self.config_obj.hf_token, self.config_obj.whisper_model,
                    self.config_obj.usar_gpu, self.config_obj.idioma
                )
                motor.cargar_modelos(lambda msg, p: self.after(0, self.estado.configure, {"text": msg}))
                self.transcriptor = motor
                texto = f"Listo · {motor.dispositivo_real.upper()}" + (
                    " · diarización" if motor.diarizacion_disponible else ""
                )
                self.after(0, self.estado_modelos.configure, {"text": texto, "text_color": "#4caf50"})
                self.after(0, self.estado.configure, {"text": "Listo para grabar o transcribir."})
            except Exception as exc:
                self.after(0, self.estado_modelos.configure, {"text": "Error", "text_color": "#ef5350"})
                self.after(0, self.estado.configure, {"text": str(exc)})
        threading.Thread(target=worker, daemon=True).start()

    def _cerrar(self):
        if self.grabador and self.grabador.esta_grabando():
            self.grabador.detener()
        self.destroy()


if __name__ == "__main__":
    AsistenteClasesApp().mainloop()
