import json
import tempfile
import unittest
from pathlib import Path

from correccion_medica import corregir_archivo_transcripcion, corregir_texto_medico


class TestRevisionMedica(unittest.TestCase):
    def test_correccion_conservadora(self):
        texto, cambios = corregir_texto_medico(
            "La interleucina seis activa linfocitos te y se de cuatro."
        )
        self.assertIn("interleucina 6", texto)
        self.assertIn("linfocitos T", texto)
        self.assertIn("CD4", texto)
        self.assertEqual(len(cambios), 3)
        self.assertTrue(all(c.confianza == 1.0 for c in cambios))

    def test_no_corrige_por_similitud(self):
        texto = "La endocarditis presenta vegetaciones."
        corregido, cambios = corregir_texto_medico(texto)
        self.assertEqual(texto, corregido)
        self.assertEqual(cambios, [])

    def test_genera_informe_auditable_desde_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "Materia" / "001 Clase"
            carpeta.mkdir(parents=True)
            (carpeta / "transcripcion.txt").write_text(
                "[00:10] Docente: La pese erre puede ser útil.\n",
                encoding="utf-8",
            )
            # Esta salida derivada contiene un texto distinto y nunca debe usarse.
            (carpeta / "transcripcion_limpia.txt").write_text(
                "[00:10] Docente: La endocarditis presenta vegetaciones.\n",
                encoding="utf-8",
            )

            informe = corregir_archivo_transcripcion(carpeta)

            self.assertEqual(informe["archivo_origen"], "transcripcion.txt")
            self.assertEqual(informe["total_cambios"], 1)
            revisada = (
                carpeta / "transcripcion_medica_revisada.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("PCR", revisada)
            self.assertNotIn("endocarditis", revisada)
            datos = json.loads(
                (carpeta / "correcciones_medicas.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(datos["cambios"][0]["linea"], 1)

    def test_reprocesar_es_idempotente(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "Materia" / "001 Clase"
            carpeta.mkdir(parents=True)
            (carpeta / "transcripcion.txt").write_text(
                "[00:10] Docente: La interleucina seis activa linfocitos te.\n",
                encoding="utf-8",
            )
            primero = corregir_archivo_transcripcion(carpeta)
            texto_primero = (
                carpeta / "transcripcion_medica_revisada.txt"
            ).read_text(encoding="utf-8")
            segundo = corregir_archivo_transcripcion(carpeta)
            texto_segundo = (
                carpeta / "transcripcion_medica_revisada.txt"
            ).read_text(encoding="utf-8")
            self.assertEqual(primero["total_cambios"], segundo["total_cambios"])
            self.assertEqual(texto_primero, texto_segundo)


if __name__ == "__main__":
    unittest.main()
