import json
import tempfile
import unittest
from pathlib import Path

from correccion_medica import corregir_texto_medico, corregir_archivo_transcripcion


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

    def test_genera_informe_auditable(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "Materia" / "001 Clase"
            carpeta.mkdir(parents=True)
            (carpeta / "transcripcion_limpia.txt").write_text(
                "[00:10] Docente: La pese erre puede ser útil.\n",
                encoding="utf-8",
            )
            informe = corregir_archivo_transcripcion(carpeta)
            self.assertEqual(informe["total_cambios"], 1)
            self.assertTrue((carpeta / "transcripcion_medica_revisada.txt").exists())
            datos = json.loads((carpeta / "correcciones_medicas.json").read_text(encoding="utf-8"))
            self.assertEqual(datos["cambios"][0]["linea"], 1)


if __name__ == "__main__":
    unittest.main()
