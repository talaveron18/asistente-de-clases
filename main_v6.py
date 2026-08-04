from __future__ import annotations

import threading

from main_v5 import ArgosV5App
from material_estudio import generar_material_estudio


class ArgosV6App(ArgosV5App):
    """ARGOS completo para clases: transcripción, apuntes, índice y repaso."""

    def _mostrar_resultados(self, caja, segmentos, carpeta):
        # Ejecuta el flujo completo heredado.
        super()._mostrar_resultados(caja, segmentos, carpeta)

        # El pipeline heredado se ejecuta en segundo plano. Esperamos a que cree
        # pipeline_clase.json antes de generar el material de estudio.
        def worker():
            import time
            from pathlib import Path
            objetivo = Path(carpeta) / "pipeline_clase.json"
            for _ in range(240):
                if objetivo.exists():
                    try:
                        generar_material_estudio(carpeta)
                        self.after(0, self.estado.configure, {
                            "text": "Clase completa: apuntes, flashcards, preguntas e índice listos."
                        })
                    except Exception as exc:
                        self.after(0, self.estado.configure, {
                            "text": f"Clase procesada; material de repaso pendiente: {exc}"
                        })
                    return
                time.sleep(0.5)
        threading.Thread(target=worker, daemon=True).start()

    def _procesar_clase_seleccionada(self):
        # Reprocesa usando la versión anterior y regenera además el material.
        ruta = self._ruta_clase_pipeline()
        super()._procesar_clase_seleccionada()
        if not ruta:
            return

        def worker():
            import time
            from pathlib import Path
            objetivo = Path(ruta) / "pipeline_clase.json"
            for _ in range(240):
                if objetivo.exists():
                    try:
                        generar_material_estudio(ruta)
                    except Exception:
                        pass
                    return
                time.sleep(0.5)
        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    ArgosV6App().mainloop()
