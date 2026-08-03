import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import Config
from grabador import GrabadorAudio
from repositorio import RepositorioClases
from transcriptor import TranscriptorClases

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class AsistenteClasesApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Asistente de Clases")
        self.geometry("1040x760")
        self.minsize(900, 650)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.config_obj = Config()
        self.repositorio = RepositorioClases()
        self.transcriptor = None
        self.grabador = None
        self.ruta_audio = ""
        self._grabando_desde = 0.0
        self._crear_interfaz()
        self._cargar_modelos()

    def _crear_interfaz(self):
        cabecera = ctk.CTkFrame(self, height=54, corner_radius=0)
        cabecera.pack(fill="x")
        cabecera.pack_propagate(False)
        ctk.CTkLabel(cabecera, text="Asistente de Clases", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left", padx=18)
        self.estado_modelos = ctk.CTkLabel(cabecera, text="Preparando...", text_color="#ffb300")
        self.estado_modelos.pack(side="right", padx=18)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=12)
        self.tab_grabar = self.tabs.add("Grabar")
        self.tab_archivo = self.tabs.add("Archivo")
        self.tab_biblioteca = self.tabs.add("Biblioteca")
        self.tab_config = self.tabs.add("Configuración")
        self._tab_grabacion()
        self._tab_archivo_audio()
        self._tab_biblioteca_clases()
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
        self.btn_grabar = ctk.CTkButton(controles, text="Iniciar grabación", command=self._iniciar_grabacion, fg_color="#c62828")
        self.btn_grabar.pack(side="left", padx=(0, 8))
        self.btn_detener = ctk.CTkButton(controles, text="Detener, transcribir y guardar", command=self._detener_grabacion, state="disabled", fg_color="#2e7d32")
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

    def _tab_archivo_audio(self):
        self.materia_archivo, self.titulo_archivo = self._campos_clase(self.tab_archivo)
        panel = ctk.CTkFrame(self.tab_archivo)
        panel.pack(fill="x", padx=14, pady=(0, 10))
        self.etiqueta_archivo = ctk.CTkLabel(panel, text="Ningún archivo seleccionado", anchor="w")
        self.etiqueta_archivo.pack(side="left", fill="x", expand=True, padx=12, pady=12)
        ctk.CTkButton(panel, text="Seleccionar audio", command=self._seleccionar_archivo).pack(side="left", padx=6)
        ctk.CTkButton(panel, text="Transcribir y guardar", command=self._transcribir_archivo).pack(side="left", padx=(0, 12))
        self.progreso_archivo = ctk.CTkProgressBar(self.tab_archivo)
        self.progreso_archivo.pack(fill="x", padx=14, pady=(0, 10))
        self.progreso_archivo.set(0)
        self.texto_archivo = ctk.CTkTextbox(self.tab_archivo, font=ctk.CTkFont(size=13))
        self.texto_archivo.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def _tab_biblioteca_clases(self):
        superior = ctk.CTkFrame(self.tab_biblioteca)
        superior.pack(fill="x", padx=14, pady=14)
        self.buscar = ctk.CTkEntry(superior, placeholder_text="Buscar por materia, título o fecha...")
        self.buscar.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=12)
        ctk.CTkButton(superior, text="Buscar", command=self._refrescar_biblioteca, width=90).pack(side="left", padx=6)
        ctk.CTkButton(superior, text="Abrir carpeta general", command=self.repositorio.abrir_raiz, width=150).pack(side="left", padx=(6, 12))
        self.lista_clases = ctk.CTkScrollableFrame(self.tab_biblioteca)
        self.lista_clases.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._refrescar_biblioteca()

    def _refrescar_biblioteca(self):
        for widget in self.lista_clases.winfo_children():
            widget.destroy()
        filtro = self.buscar.get() if hasattr(self, "buscar") else ""
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
            ctk.CTkButton(fila, text="Abrir", width=80, command=lambda r=clase["ruta"]: self.repositorio.abrir_carpeta(r)).pack(side="right", padx=10)

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
        ok = self.grabador.iniciar(lambda n: self.after(0, self.nivel.set, n), self.config_obj.obtener_ruta_temp())
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
        ruta = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma"), ("Todos", "*.*")])
        if ruta:
            self.ruta_audio = ruta
            self.etiqueta_archivo.configure(text=ruta)
            if not self.titulo_archivo.get():
                self.titulo_archivo.insert(0, Path(ruta).stem)

    def _transcribir_archivo(self):
        datos = self._datos_clase(self.materia_archivo, self.titulo_archivo)
        if not datos:
            return
        if not self.ruta_audio:
            messagebox.showinfo("Archivo", "Selecciona primero un audio.")
            return
        self._procesar(self.ruta_audio, "archivo", *datos)

    def _procesar(self, ruta, tab, materia, titulo):
        if not self.transcriptor or not self.transcriptor.modelos_cargados:
            messagebox.showwarning("Modelos", "Los modelos todavía no están listos.")
            return
        barra = self.progreso_grabar if tab == "grabar" else self.progreso_archivo
        caja = self.texto_grabar if tab == "grabar" else self.texto_archivo
        caja.delete("1.0", "end")

        def worker():
            try:
                segmentos = self.transcriptor.transcribir_archivo(
                    ruta,
                    callback_progreso=lambda msg, p: self.after(0, self._progreso, barra, msg, p),
                    min_hablantes=self.config_obj.min_hablantes,
                    max_hablantes=self.config_obj.max_hablantes,
                )
                carpeta = self.repositorio.guardar_clase(materia, titulo, segmentos, ruta)
                self.config_obj.ultima_materia = materia
                self.config_obj.guardar()
                self.after(0, self._mostrar_resultados, caja, segmentos, carpeta)
            except Exception as exc:
                self.after(0, messagebox.showerror, "Transcripción", str(exc))
                self.after(0, barra.set, 0)

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
        self._refrescar_biblioteca()
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
        self.estado.configure(text="La primera carga descargará el modelo automáticamente.")

        def worker():
            try:
                motor = TranscriptorClases(self.config_obj.hf_token, self.config_obj.whisper_model, self.config_obj.usar_gpu, self.config_obj.idioma)
                motor.cargar_modelos(lambda msg, p: self.after(0, self.estado.configure, {"text": msg}))
                self.transcriptor = motor
                texto = f"Listo · {motor.dispositivo_real.upper()}" + (" · diarización" if motor.diarizacion_disponible else "")
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
