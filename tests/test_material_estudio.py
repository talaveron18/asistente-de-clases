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
                    "segmentos": [
                        {
                            "tiempo": "00:30",
                            "rol": "Docente",
                            "texto": "El shock es una insuficiencia circulatoria aguda.",
                        },
                        {
                            "tiempo": "01:20",
                            "rol": "Docente",
                            "texto": "Produce hipoperfusión tisular.",
                        },
                    ],
                    "avisos_examen": ["[03:00] Esto entra en el examen."],
                    "preguntas": [
                        "[04:00] ¿Qué es el shock?",
                        "[05:00] ¿Qué receptor inicia esta respuesta?",
                    ],
                    "referencias_locales": [{
                        "titulo": "Diapositivas de shock.pdf",
                        "ubicacion": "Página 7",
                        "pagina": 7,
                        "ruta": "Diapositivas de shock.pdf",
                        "fragmento": "El shock cursa con hipoperfusión tisular.",
                        "vinculada_a_clase": True,
                    }],
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
            self.assertTrue((carpeta / "apuntes_estudio_argos.md").exists())
            self.assertTrue((carpeta / "trazabilidad_argos.json").exists())
            self.assertTrue((carpeta / "trazabilidad_argos.md").exists())
            preguntas = (carpeta / "preguntas_repaso.md").read_text(
                encoding="utf-8"
            )
            apuntes = (carpeta / "apuntes_estudio_argos.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("Respuesta basada en la clase", preguntas)
            self.assertIn("Historia fisiopatológica", apuntes)
            self.assertIn("Produce hipoperfusión tisular", apuntes)
            self.assertIn("Preguntas de parcial con respuesta", apuntes)
            trazabilidad = json.loads(
                (carpeta / "trazabilidad_argos.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                trazabilidad["metricas"]["cobertura_documental_porcentaje"],
                100.0,
            )
            self.assertEqual(
                trazabilidad["metricas"]["preguntas_con_respuesta_explicitada"],
                1,
            )
            self.assertEqual(
                trazabilidad["metricas"]["preguntas_sin_respuesta"], 1
            )
            self.assertEqual(trazabilidad["preguntas"][0]["minuto"], "04:00")
            self.assertEqual(
                trazabilidad["preguntas"][0]["minuto_respuesta"], "00:30"
            )
            self.assertEqual(trazabilidad["bloques"][0]["inicio"], "00:00")
            self.assertEqual(
                trazabilidad["bloques"][0]["referencias_documentales"][0]["pagina"],
                7,
            )
            self.assertIn("No consta una respuesta explícita", preguntas)
            try:
                import docx  # noqa: F401
                self.assertTrue((carpeta / "apuntes_argos.docx").exists())
            except ImportError:
                pass


if __name__ == "__main__":
    unittest.main()
