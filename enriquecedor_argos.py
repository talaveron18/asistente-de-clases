from __future__ import annotations

import json
from pathlib import Path

from correccion_medica import corregir_archivo_transcripcion
from indice_sqlite import IndiceConocimientoSQLite


def enriquecer_clase_con_fuentes(carpeta: str | Path, limite_por_bloque: int = 4) -> dict:
    """Añade referencias locales a los bloques de una clase.

    Recupera fragmentos del índice FTS5. No genera afirmaciones nuevas ni mezcla
    contenido sin citar. Las fuentes de la propia clase se excluyen cuando sea posible.
    """
    carpeta = Path(carpeta)
    pipeline_path = carpeta / "pipeline_clase.json"
    if not pipeline_path.exists():
        raise FileNotFoundError(pipeline_path)
    datos = json.loads(pipeline_path.read_text(encoding="utf-8"))

    indice = IndiceConocimientoSQLite()
    try:
        indice.reconstruir()
    except Exception:
        pass

    bloques_enriquecidos = []
    for bloque in datos.get("bloques", []):
        consulta = " ".join(bloque.get("palabras_clave", [])[:5]) or bloque.get("titulo", "")
        resultados = indice.buscar(consulta, alcance="Biblioteca médica", limite=max(8, limite_por_bloque * 3))
        referencias = []
        vistos = set()
        for r in resultados:
            clave = (r.ruta, r.pagina, r.contenido)
            if clave in vistos:
                continue
            vistos.add(clave)
            referencias.append({
                "categoria": r.categoria,
                "titulo": r.titulo,
                "ubicacion": r.ubicacion,
                "pagina": r.pagina,
                "fragmento": r.contenido,
                "ruta": r.ruta,
            })
            if len(referencias) >= limite_por_bloque:
                break
        copia = dict(bloque)
        copia["referencias_locales"] = referencias
        bloques_enriquecidos.append(copia)

    salida = dict(datos)
    salida["bloques"] = bloques_enriquecidos
    salida["politica_fuentes"] = (
        "Las referencias se recuperan de la biblioteca local. No validan por sí solas "
        "la exactitud clínica y deben revisarse en el documento original."
    )
    (carpeta / "argos_enriquecido.json").write_text(
        json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (carpeta / "apuntes_argos_enriquecidos.md").write_text(
        _markdown_enriquecido(salida), encoding="utf-8"
    )
    return salida


def procesar_bloque_medico_completo(carpeta: str | Path) -> dict:
    correcciones = corregir_archivo_transcripcion(carpeta)
    enriquecido = enriquecer_clase_con_fuentes(carpeta)
    return {
        "correcciones": correcciones.get("total_cambios", 0),
        "bloques": len(enriquecido.get("bloques", [])),
        "referencias": sum(len(b.get("referencias_locales", [])) for b in enriquecido.get("bloques", [])),
        "archivos": [
            "transcripcion_medica_revisada.txt",
            "correcciones_medicas.json",
            "argos_enriquecido.json",
            "apuntes_argos_enriquecidos.md",
        ],
    }


def _markdown_enriquecido(datos: dict) -> str:
    lineas = [
        f"# {datos.get('titulo', 'Clase')}", "",
        f"**Materia:** {datos.get('materia', '')}", "",
        "> Documento generado a partir de la clase. Las ampliaciones se muestran como referencias locales y conservan su fuente.", "",
    ]
    for bloque in datos.get("bloques", []):
        lineas += [
            f"## {bloque.get('numero')}. {bloque.get('titulo')}", "",
            f"**Intervalo:** {bloque.get('inicio')}–{bloque.get('fin')}", "",
            "### Resumen de la clase", "", bloque.get("resumen", ""), "",
            "### Desarrollo limpio", "", bloque.get("texto", ""), "",
        ]
        refs = bloque.get("referencias_locales", [])
        lineas += ["### Referencias de la biblioteca local", ""]
        if not refs:
            lineas += ["- No se encontraron referencias locales suficientemente próximas.", ""]
        else:
            for i, ref in enumerate(refs, 1):
                lineas += [
                    f"{i}. **{ref.get('titulo')} · {ref.get('ubicacion')}**",
                    f"   - Categoría: {ref.get('categoria')}",
                    f"   - Fragmento: {ref.get('fragmento')}", "",
                ]
    return "\n".join(lineas)
