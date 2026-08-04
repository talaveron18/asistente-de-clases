import json
import tempfile
import unittest
from pathlib import Path

from material_estudio import generar_material_estudio


class MaterialEstudioTests(unittest.TestCase):
    def test_genera_flashcards_preguntas_repaso_y_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            datos = {
                "materia": "Fisiopatología II",
                "titulo": "Shock",
                "palabras_clave_globales": ["shock", "perfusión"],
                "avisos_examen": ["[13:20] Esto entra en el examen."],
                "bloques": [{
                    "numero": 1,
                    "inicio": "00:00",
                    "fin": "12:00",
                    "titulo": "Definición de shock",
                    "resumen": "El shock es una insuficiencia circulatoria aguda con hipoperfusión tisular.",
                    "palabras_clave": ["shock", "hipoperfusión"],
                    "texto": "El shock es una insuficiencia circulatoria aguda. Produce hipoperfusión tisular.",
                    "avisos_examen": ["[03:00] Esto entra en el examen."],
                    "preguntas": ["[04:00] ¿Qué es el shock?"],
                }],
            }
            (carpeta / "pipeline_clase.json").write_text(
                json.dumps(datos, ensure_ascii=False), encoding="utf-8"
            )

            resultado = generar_material_estudio(carpeta)

            self.assertGreater(resultado["flashcards"], 0)
            self.assertGreater(resultado["preguntas"], 0)
            self.assertTrue((carpeta / "flashcards_argos.tsv").exists())
            self.assertTrue((carpeta / "preguntas_repaso.md").exists())
            self.assertTrue((carpeta / "repaso_rapido.md").exists())
            try:
                import docx  # noqa: F401
                self.assertTrue((carpeta / "apuntes_argos.docx").exists())
            except ImportError:
                pass


if __name__ == "__main__":
    unittest.main()
