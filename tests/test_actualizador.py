import hashlib
import io
import json
import unittest

from actualizador import (
    Actualizacion,
    ErrorActualizacion,
    buscar_actualizacion,
    descargar_instalador,
    es_mas_reciente,
)


class RespuestaFalsa(io.BytesIO):
    def __init__(self, datos: bytes):
        super().__init__(datos)
        self.headers = {"Content-Length": str(len(datos))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _abrir_con(datos: bytes):
    return lambda _peticion, timeout: RespuestaFalsa(datos)


class ActualizadorTests(unittest.TestCase):
    def test_compara_versiones_numericas(self):
        self.assertTrue(es_mas_reciente("0.8.10", "0.8.9"))
        self.assertFalse(es_mas_reciente("0.8.9", "0.8.10"))
        self.assertFalse(es_mas_reciente("1.2.0", "1.2"))

    def test_busca_actualizacion_y_descarta_la_misma_version(self):
        manifiesto = {
            "version": "0.8.12",
            "sha256": "a" * 64,
            "tamano": 1234,
        }
        datos = json.dumps(manifiesto).encode()
        self.assertEqual(
            buscar_actualizacion("0.8.11", abrir=_abrir_con(datos)),
            Actualizacion(version="0.8.12", sha256="a" * 64, tamano=1234),
        )
        self.assertIsNone(buscar_actualizacion("0.8.12", abrir=_abrir_con(datos)))

    def test_rechaza_manifiesto_sin_huella_valida(self):
        datos = json.dumps(
            {"version": "0.8.12", "sha256": "mal", "tamano": 1234}
        ).encode()
        with self.assertRaises(ErrorActualizacion):
            buscar_actualizacion("0.8.11", abrir=_abrir_con(datos))

    def test_descarga_y_verifica_instalador(self):
        import tempfile

        contenido = b"instalador-argos"
        actualizacion = Actualizacion(
            version="0.8.12",
            sha256=hashlib.sha256(contenido).hexdigest(),
            tamano=len(contenido),
        )
        with tempfile.TemporaryDirectory() as temporal:
            destino = descargar_instalador(
                actualizacion,
                directorio=temporal,
                abrir=_abrir_con(contenido),
            )
            self.assertEqual(destino.read_bytes(), contenido)

    def test_elimina_descarga_si_la_huella_no_coincide(self):
        import tempfile
        from pathlib import Path

        actualizacion = Actualizacion(
            version="0.8.12",
            sha256="0" * 64,
            tamano=4,
        )
        with tempfile.TemporaryDirectory() as temporal:
            with self.assertRaises(ErrorActualizacion):
                descargar_instalador(
                    actualizacion,
                    directorio=temporal,
                    abrir=_abrir_con(b"dato"),
                )
            self.assertFalse(list(Path(temporal).iterdir()))
