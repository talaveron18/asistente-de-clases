from __future__ import annotations

import json
from pathlib import Path

from indice_sqlite import IndiceConocimientoSQLite


def enriquecer_clase_con_fuentes(
    carpeta: str | Path,
    limite_por_bloque: int = 4,
    indice: IndiceConocimientoSQLite | None = None,
) -> dict:
    """Añade referencias documentales usando exclusivamente el índice FTS5.

    No reconstruye índices ni ejecuta correcciones por su cuenta. Es una etapa
    pura del orquestador y, por tanto, no puede iniciar una segunda cadena de
    procesamiento en paralelo.
    """
    carpeta = Path(carpeta)
    pipeline_path = carpeta / "pipeline_clase.json"
    if not pipeline_path.exists():
        raise FileNotFoundError(pipeline_path)
    datos = json.loads(pipeline_path.read_text(encoding="utf-8"))
    indice = indice or IndiceConocimientoSQLite(str(carpeta.parent.parent))

    bloques_enriquecidos = []
    for bloque in datos.get("bloques", []):
        consulta = (
            " ".join(bloque.get("palabras_clave", [])[:5])
            or bloque.get("titulo", "")
        )
        resultados = indice.buscar(
            consulta,
            alcance="Biblioteca médica",
            limite=max(8, limite_por_bloque * 3),
        )
        referencias = []
        vistos = set()
        for resultado in resultados:
            clave = (resultado.ruta, resultado.pagina, resultado.contenido)
            if clave in vistos:
                continue
            vistos.add(clave)
            referencias.append(
                {
                    "categoria": resultado.categoria,
                    "titulo": resultado.titulo,
                    "ubicacion": resultado.ubicacion,
                    "pagina": resultado.pagina,
                    "fragmento": resultado.contenido,
                    "ruta": resultado.ruta,
                }
            )
            if len(referencias) >= limite_por_bloque:
                break
        copia = dict(bloque)
        copia["referencias_locales"] = referencias
        bloques_enriquecidos.append(copia)

    salida = dict(datos)
    salida["bloques"] = bloques_enriquecidos
    salida["politica_fuentes"] = (
        "Las referencias se recuperan del único índice FTS5 local. No validan "
        "por sí solas la exactitud clínica y deben revisarse en el original."
    )
    _escribir_atomico(
        carpeta / "argos_enriquecido.json",
        json.dumps(salida, ensure_ascii=False, indent=2),
    )
    _escribir_atomico(
        carpeta / "apuntes_argos_enriquecidos.md",
        _markdown_enriquecido(salida),
    )
    return salida


def _escribir_atomico(ruta: Path, contenido: str) -> None:
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(contenido, encoding="utf-8")
    temporal.replace(ruta)


def _markdown_enriquecido(datos: dict) -> str:
    lineas = [
        f"# {datos.get('titulo', 'Clase')}",
        "",
        f"**Materia:** {datos.get('materia', '')}",
        f"**Fuente de clase:** {datos.get('archivo_fuente', '')}",
        "",
        "> Documento generado desde la clase. Las ampliaciones se muestran "
        "como referencias locales y conservan su fuente.",
        "",
    ]
    for bloque in datos.get("bloques", []):
        lineas += [
            f"## {bloque.get('numero')}. {bloque.get('titulo')}",
            "",
            f"**Intervalo:** {bloque.get('inicio')}–{bloque.get('fin')}",
            "",
            "### Resumen de la clase",
            "",
            bloque.get("resumen", ""),
            "",
            "### Desarrollo limpio",
            "",
            bloque.get("texto", ""),
            "",
            "### Referencias de la biblioteca local",
            "",
        ]
        referencias = bloque.get("referencias_locales", [])
        if not referencias:
            lineas += [
                "- No se encontraron referencias locales suficientemente próximas.",
                "",
            ]
            continue
        for numero, referencia in enumerate(referencias, 1):
            lineas += [
                f"{numero}. **{referencia.get('titulo')} · "
                f"{referencia.get('ubicacion')}**",
                f"   - Categoría: {referencia.get('categoria')}",
                f"   - Fragmento: {referencia.get('fragmento')}",
                "",
            ]
    return "\n".join(lineas)
