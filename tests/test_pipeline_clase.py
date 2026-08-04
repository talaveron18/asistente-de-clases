import json
import tempfile
import unittest
from pathlib import Path

from pipeline_clase import analizar_clase_completa


class PipelineClaseTests(unittest.TestCase):
    def test_genera_salidas_y_detecta_examen(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "Fisiopatología II" / "001 · 2026-08-04 · Shock"
            carpeta.mkdir(parents=True)
            (carpeta / "ficha.json").write_text(
                json.dumps({"materia": "Fisiopatología II", "titulo": "Shock"}),
                encoding="utf-8",
            )
            (carpeta / "transcripcion.txt").write_text(
                "\n".join([
                    "[00:00] Docente: Bueno, hoy vamos a ver shock.",
                    "[02:10] Docente: El shock es una insuficiencia circulatoria aguda.",
                    "[12:30] Docente: Ahora vamos a ver shock distributivo.",
                    "[13:20] Docente: Esto entra en el examen y es muy importante.",
                    "[14:00] Docente: ¿Cuál es la diferencia con el shock hipovolémico?",
                ]),
                encoding="utf-8",
            )

            resultado = analizar_clase_completa(carpeta, minutos_bloque=10)

            self.assertGreaterEqual(len(resultado["bloques"]), 2)
            self.assertEqual(len(resultado["avisos_examen"]), 1)
            self.assertEqual(len(resultado["preguntas_profesor"]), 1)
            self.assertTrue((carpeta / "transcripcion_limpia.txt").exists())
            self.assertTrue((carpeta / "pipeline_clase.json").exists())
            self.assertTrue((carpeta / "apuntes_argos.md").exists())
            markdown = (carpeta / "apuntes_argos.md").read_text(encoding="utf-8")
            self.assertIn("Avisos de examen", markdown)
            self.assertIn("Shock", markdown)


if __name__ == "__main__":
    unittest.main()
