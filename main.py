import os
import threading
import time
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import Config
from grabador import GrabadorAudio
from transcriptor import TranscriptorClases

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class AsistenteClasesApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Asistente de Clases")
        self.geometry("920x720")
        self.minsize(820, 620)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self.config_obj = Config()
        self.transcriptor = None
        self.grabador = None
        self.segmentos = []
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
        self.tab_config = self.tabs.add("Configuración")
        self._tab_grabacion()
        self._tab_archivo_audio()
        self._tab_configuracion()
        self.estado = ctk.CTkLabel(self, text="Inicializando...", anchor="w")
        self.estado.pack(fill="x", padx=16, pady=(0, 10))

    def _tab_grabacion(self):
        panel = ctk.CTkFrame(self.tab_grabar)
        panel.pack(fill="x", padx=14, pady=14)
        ctk.CTkLabel(panel, text="Micrófono:").pack(side="left", padx=(12, 6), pady=12)
        self.combo_micro = ctk.CTkComboBox(panel, width=430)
        self.combo_micro.pack(side="left", padx=6)
        dispositivos = GrabadorAudio.listar_dispositivos()
        valores = [f"{i}: {nombre}" for i, nombre in dispositivos] or ["Sin dispositivos detectados"]
        self.combo_micro.configure(values=valores)
        self.combo_micro.set(valores[0])
        controles = ctk.CTkFrame(self.tab_grabar, fg_color="transparent")
        controles.pack(fill="x", padx=14)
        self.btn_grabar = ctk.CTkButton(controles, text="Iniciar grabación", command=self._iniciar_grabacion, fg_color="#c62828")
        self.btn_grabar.pack(side="left", padx=(0, 8))
        self.btn_detener = ctk.CTkButton(controles, text="Detener y transcribir", command=self._detener_grabacion, state="disabled", fg_color="#2e7d32")
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
        self.texto_grabar.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self._botones_exportacion(self.tab_grabar)

    def _tab_archivo_audio(self):
        panel = ctk.CTkFrame(self.tab_archivo)
        panel.pack(fill="x", padx=14, pady=14)
        self.etiqueta_archivo = ctk.CTkLabel(panel, text="Ningún archivo seleccionado", anchor="w")
        self.etiqueta_archivo.pack(side="left", fill="x", expand=True, padx=12, pady=12)
        ctk.CTkButton(panel, text="Seleccionar audio", command=self._seleccionar_archivo).pack(side="left", padx=6)
        ctk.CTkButton(panel, text="Transcribir", command=self._transcribir_archivo).pack(side="left", padx=(0, 12))
        self.progreso_archivo = ctk.CTkProgressBar(self.tab_archivo)
        self.progreso_archivo.pack(fill="x", padx=14, pady=(0, 10))
        self.progreso_archivo.set(0)
        self.texto_archivo = ctk.CTkTextbox(self.tab_archivo, font=ctk.CTkFont(size=13))
        self.texto_archivo.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self._botones_exportacion(self.tab_archivo)

    def _botones_exportacion(self, parent):
        fila = ctk.CTkFrame(parent, fg_color="transparent")
        fila.pack(fill="x", padx=14, pady=(0, 12))
        for formato in ("txt", "md", "srt"):
            ctk.CTkButton(fila, text=f"Guardar {formato.upper()}", width=130, command=lambda f=formato: self._exportar(f)).pack(side="left", padx=(0, 6))

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
        fila = ctk.CTkFrame(marco, fg_color="transparent")
        fila.pack(fill="x", pady=10)
        ctk.CTkLabel(fila, text="Mín. hablantes").pack(side="left")
        self.min_h = ctk.CTkEntry(fila, width=60)
        self.min_h.pack(side="left", padx=(6, 18))
        self.min_h.insert(0, str(self.config_obj.min_hablantes))
        ctk.CTkLabel(fila, text="Máx. hablantes").pack(side="left")
        self.max_h = ctk.CTkEntry(fila, width=60)
        self.max_h.pack(side="left", padx=6)
        self.max_h.insert(0, str(self.config_obj.max_hablantes))
        ctk.CTkButton(marco, text="Guardar y recargar modelos", command=self._guardar_config).pack(pady=18)

    def _indice_microfono(self):
        try:
            return int(self.combo_micro.get().split(":", 1)[0])
        except (ValueError, IndexError):
            return None

    def _iniciar_grabacion(self):
        if not self.transcriptor or not self.transcriptor.modelos_cargados:
            messagebox.showwarning("Modelos", "Los modelos todavía no están listos.")
            return
        self.grabador = GrabadorAudio(self.config_obj.sample_rate, self._indice_microfono())
        ruta = self.config_obj.obtener_ruta_temp()
        ok = self.grabador.iniciar(lambda n: self.after(0, self.nivel.set, n), ruta)
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
        ruta = self.grabador.detener() if self.grabador else None
        self.btn_grabar.configure(state="normal")
        self.btn_detener.configure(state="disabled")
        self.nivel.set(0)
        if ruta:
            self._procesar(ruta, "grabar")

    def _seleccionar_archivo(self):
        ruta = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg *.wma"), ("Todos", "*.*")])
        if ruta:
            self.ruta_audio = ruta
            self.etiqueta_archivo.configure(text=ruta)

    def _transcribir_archivo(self):
        if not self.ruta_audio:
            messagebox.showinfo("Archivo", "Selecciona primero un audio.")
            return
        self._procesar(self.ruta_audio, "archivo")

    def _procesar(self, ruta, tab):
        if not self.transcriptor or not self.transcriptor.modelos_cargados:
            messagebox.showwarning("Modelos", "Los modelos todavía no están listos.")
            return
        barra = self.progreso_grabar if tab == "grabar" else self.progreso_archivo
        texto = self.texto_grabar if tab == "grabar" else self.texto_archivo
        texto.delete("1.0", "end")
        def worker():
            try:
                segmentos = self.transcriptor.transcribir_archivo(ruta, callback_progreso=lambda msg, p: self.after(0, self._progreso, barra, msg, p), min_hablantes=self.config_obj.min_hablantes, max_hablantes=self.config_obj.max_hablantes)
                self.after(0, self._mostrar_resultados, texto, segmentos)
            except Exception as exc:
                self.after(0, messagebox.showerror, "Transcripción", str(exc))
                self.after(0, barra.set, 0)
        threading.Thread(target=worker, daemon=True).start()

    def _progreso(self, barra, mensaje, valor):
        barra.set(valor)
        self.estado.configure(text=mensaje)

    def _mostrar_resultados(self, caja, segmentos):
        self.segmentos = segmentos
        caja.delete("1.0", "end")
        caja.insert("end", "\n".join(s.a_linea_txt() for s in segmentos) if segmentos else "No se detectó voz.")
        self.estado.configure(text=f"Transcripción completada: {len(segmentos)} segmentos")
        self.progreso_grabar.set(0)
        self.progreso_archivo.set(0)

    def _exportar(self, formato):
        if not self.segmentos:
            messagebox.showinfo("Exportar", "No hay una transcripción para guardar.")
            return
        extension = {"txt": ".txt", "md": ".md", "srt": ".srt"}[formato]
        ruta = filedialog.asksaveasfilename(defaultextension=extension, filetypes=[(formato.upper(), f"*{extension}")])
        if not ruta:
            return
        getattr(self.transcriptor, {"txt": "exportar_txt", "md": "exportar_markdown", "srt": "exportar_srt"}[formato])(self.segmentos, ruta)
        self.estado.configure(text=f"Guardado: {os.path.basename(ruta)}")

    def _guardar_config(self):
        self.config_obj.hf_token = self.token.get().strip()
        self.config_obj.whisper_model = self.modelo.get()
        self.config_obj.idioma = self.idioma.get()
        self.config_obj.usar_gpu = bool(self.gpu.get())
        try:
            self.config_obj.min_hablantes = max(1, min(20, int(self.min_h.get())))
            self.config_obj.max_hablantes = max(self.config_obj.min_hablantes, min(20, int(self.max_h.get())))
        except ValueError:
            messagebox.showerror("Configuración", "Los valores de hablantes deben ser números.")
            return
        valido, mensaje = self.config_obj.validar()
        if not valido:
            messagebox.showerror("Configuración", mensaje)
            return
        self.config_obj.guardar()
        self._cargar_modelos()

    def _cargar_modelos(self):
        self.estado_modelos.configure(text="Cargando modelos...", text_color="#ffb300")
        self.estado.configure(text="La primera carga puede descargar varios GB.")
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
