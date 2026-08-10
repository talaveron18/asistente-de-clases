from pathlib import Path

from grabador import FragmentoAudio
from repositorio import RepositorioClases
from texto_en_directo import actualizar_texto, copiar_texto
from transcripcion_incremental import TranscripcionIncremental
from transcriptor import (
    MAX_CARACTERES_CONTEXTO,
    SegmentoTranscrito,
    TranscriptorClases,
    construir_prompt_transcripcion,
)


class SegmentoWhisperFalso:
    def __init__(self, texto="La interleucina seis produce fiebre"):
        self.start = 0.0
        self.end = 2.0
        self.text = texto


class ModeloWhisperFalso:
    def __init__(self):
        self.llamadas = []

    def transcribe(self, _ruta, **opciones):
        self.llamadas.append(opciones)
        return iter([SegmentoWhisperFalso()]), object()


class CajaFalsa:
    def __init__(self, texto=""):
        self.texto = texto
        self.estado = "normal"
        self.seleccion = ()
        self.vista = (0.0, 1.0)
        self.see_llamadas = 0
        self.seleccion_restaurada = None

    def configure(self, **opciones):
        self.estado = opciones.get("state", self.estado)

    def insert(self, _indice, texto):
        self.texto += texto

    def delete(self, _inicio, _fin):
        self.texto = ""

    def get(self, inicio, _fin):
        if inicio == "sel.first" and self.seleccion:
            a, b = self.seleccion
            return self.texto[a:b]
        return self.texto

    def tag_ranges(self, _etiqueta):
        return self.seleccion

    def index(self, indice):
        if indice == "sel.first" and self.seleccion:
            return f"1.{self.seleccion[0]}"
        if indice == "sel.last" and self.seleccion:
            return f"1.{self.seleccion[1]}"
        raise RuntimeError("sin selección")

    def tag_add(self, _etiqueta, inicio, fin):
        self.seleccion_restaurada = (inicio, fin)

    def yview(self):
        return self.vista

    def see(self, _indice):
        self.see_llamadas += 1


class VentanaFalsa:
    def __init__(self):
        self.portapapeles = ""

    def clipboard_clear(self):
        self.portapapeles = ""

    def clipboard_append(self, texto):
        self.portapapeles += texto


def _transcriptor_falso(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF-audio-falso")
    motor = TranscriptorClases(model_size="small", idioma="es")
    modelo = ModeloWhisperFalso()
    motor.whisper_model = modelo
    motor.modelos_cargados = True
    return motor, modelo, audio


def test_prompt_fija_medicina_y_espanol_rioplatense_sin_crecer_sin_limite():
    prompt = construir_prompt_transcripcion(
        "Farmacología II", "contexto " * 100
    )

    assert "español rioplatense de Argentina" in prompt
    assert "fisiopatología" in prompt
    assert "Farmacología" not in prompt  # se conserva el final más reciente
    assert len(prompt) < 600
    assert MAX_CARACTERES_CONTEXTO == 260


def test_fragmentos_reutilizan_el_texto_anterior_como_contexto(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)

    primero = motor.transcribir_fragmento(
        str(audio), contexto_clase="Fisiopatología II · Inflamación"
    )
    motor.transcribir_fragmento(
        str(audio),
        contexto_clase="Fisiopatología II · Inflamación",
        contexto_previo=primero[0].texto,
    )

    assert primero[0].texto == "La interleucina seis produce fiebre"
    assert "Fisiopatología II" in modelo.llamadas[0]["initial_prompt"]
    assert "La interleucina seis produce fiebre" in modelo.llamadas[1][
        "initial_prompt"
    ]
    assert modelo.llamadas[0]["language"] == "es"
    assert modelo.llamadas[0]["condition_on_previous_text"] is False


def test_pasada_final_usa_busqueda_mas_precisa_y_contexto_medico(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)

    resultado = motor.transcribir_archivo(
        str(audio),
        min_hablantes=1,
        max_hablantes=1,
        contexto_clase="Fisiopatología II · Inflamación",
    )

    assert resultado[0].rol == "Docente"
    assert modelo.llamadas[0]["beam_size"] == 5
    assert modelo.llamadas[0]["condition_on_previous_text"] is True
    assert "español rioplatense de Argentina" in modelo.llamadas[0][
        "initial_prompt"
    ]


def test_cada_grabacion_conserva_su_propio_contexto_sin_contaminar_otras(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Microbiología", "Micobacterias")
    fragmento = carpeta / "fragmentos_audio" / "fragmento_000001.wav"
    fragmento.write_bytes(b"RIFF-audio-falso")

    class TranscriptorConContexto:
        def __init__(self):
            self.llamadas = []

        def transcribir_fragmento(
            self, _ruta, contexto_clase="", contexto_previo=""
        ):
            self.llamadas.append((contexto_clase, contexto_previo))
            return [
                SegmentoTranscrito(
                    0, 1, "Mycobacterium tuberculosis", "SPEAKER_00", "Docente"
                )
            ]

    motor = TranscriptorConContexto()
    incremental = TranscripcionIncremental(
        motor,
        repositorio,
        carpeta,
        materia="Microbiología",
        titulo="Micobacterias",
    )
    incremental.encolar(FragmentoAudio(1, str(fragmento), 0, 10))
    incremental.finalizar()

    assert motor.llamadas == [("Microbiología · Micobacterias", "")]


def test_actualizacion_incremental_no_reescribe_ni_mueve_una_seleccion():
    caja = CajaFalsa("Primera frase")
    caja.seleccion = (0, 7)

    renderizado = actualizar_texto(
        caja, "Primera frase\nSegunda frase", "Primera frase"
    )

    assert renderizado == "Primera frase\nSegunda frase"
    assert caja.texto == renderizado
    assert caja.estado == "disabled"
    assert caja.see_llamadas == 0


def test_copia_funciona_durante_la_transcripcion_sin_editar_el_cuadro():
    caja = CajaFalsa("Shock distributivo\nShock cardiogénico")
    ventana = VentanaFalsa()

    texto = copiar_texto(ventana, caja)

    assert texto == caja.texto
    assert ventana.portapapeles == caja.texto


def test_una_correccion_del_ultimo_fragmento_conserva_la_seleccion():
    caja = CajaFalsa("Interleucina seis")
    caja.seleccion = (0, 12)

    actualizar_texto(caja, "Interleucina 6", "Interleucina seis")

    assert caja.texto == "Interleucina 6"
    assert caja.seleccion_restaurada == ("1.0", "1.12")
    assert caja.see_llamadas == 0
