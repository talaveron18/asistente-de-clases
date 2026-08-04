from __future__ import annotations

from dataclasses import dataclass
from indice_sqlite import IndiceConocimientoSQLite, CoincidenciaFTS


@dataclass
class RespuestaArgos:
    pregunta: str
    respuesta: str
    fuentes: list[CoincidenciaFTS]
    modo: str = "extractivo"


class ChatArgos:
    """Primera versión segura del chat: recuperación + síntesis extractiva.

    No llama todavía a un modelo externo. Resume únicamente fragmentos hallados
    en las fuentes locales y deja claro cuándo no hay evidencia suficiente.
    """

    def __init__(self, indice: IndiceConocimientoSQLite | None = None):
        self.indice = indice or IndiceConocimientoSQLite()

    def preguntar(self, pregunta: str, alcance: str = "Todo", limite_fuentes: int = 8) -> RespuestaArgos:
        fuentes = self.indice.buscar(pregunta, alcance, limite=limite_fuentes)
        if not fuentes:
            return RespuestaArgos(
                pregunta=pregunta,
                respuesta=(
                    "No he encontrado evidencia suficiente en las clases o documentos indexados. "
                    "Prueba con términos más concretos o reconstruye el índice."
                ),
                fuentes=[],
            )

        bloques = []
        for i, f in enumerate(fuentes, 1):
            etiqueta = f"{f.categoria} · {f.titulo} · {f.ubicacion}"
            texto = f.contenido.replace("⟦", "").replace("⟧", "").strip()
            bloques.append(f"[{i}] {etiqueta}\n{texto}")

        respuesta = (
            "He encontrado los siguientes pasajes relevantes en tu base de conocimiento. "
            "Esta primera versión no añade conocimiento externo ni rellena huecos:\n\n"
            + "\n\n".join(bloques)
            + "\n\nConclusión provisional: revisa los pasajes anteriores como base documental. "
              "Cuando conectemos el motor de IA, podrá sintetizarlos manteniendo estas mismas referencias."
        )
        return RespuestaArgos(pregunta=pregunta, respuesta=respuesta, fuentes=fuentes)
