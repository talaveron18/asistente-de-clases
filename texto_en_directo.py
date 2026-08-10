"""Actualización y copia segura de la transcripción mientras sigue creciendo."""
from __future__ import annotations


def _widget_texto(caja):
    """Devuelve el Text interno de CustomTkinter cuando sea necesario."""
    return getattr(caja, "_textbox", caja)


def hay_seleccion(caja) -> bool:
    widget = _widget_texto(caja)
    try:
        return bool(widget.tag_ranges("sel"))
    except Exception:
        return False


def _rango_seleccion(caja) -> tuple[str, str] | None:
    widget = _widget_texto(caja)
    try:
        return widget.index("sel.first"), widget.index("sel.last")
    except Exception:
        return None


def obtener_seleccion(caja) -> str:
    widget = _widget_texto(caja)
    try:
        return widget.get("sel.first", "sel.last").strip()
    except Exception:
        return ""


def _esta_al_final(caja) -> bool:
    widget = _widget_texto(caja)
    try:
        _inicio, fin = widget.yview()
        return float(fin) >= 0.98
    except Exception:
        return True


def actualizar_texto(
    caja,
    texto_nuevo: str,
    texto_anterior: str = "",
    *,
    seguir_final: bool = True,
) -> str:
    """Añade solo el sufijo nuevo y respeta selección y posición de lectura."""
    rango_seleccion = _rango_seleccion(caja)
    seleccion_activa = rango_seleccion is not None
    estaba_al_final = _esta_al_final(caja)
    caja.configure(state="normal")
    if texto_anterior and texto_nuevo.startswith(texto_anterior):
        sufijo = texto_nuevo[len(texto_anterior) :]
        if sufijo:
            caja.insert("end", sufijo)
    else:
        caja.delete("1.0", "end")
        caja.insert("end", texto_nuevo)
        if rango_seleccion is not None:
            widget = _widget_texto(caja)
            try:
                widget.tag_add("sel", *rango_seleccion)
            except Exception:
                pass
    caja.configure(state="disabled")
    if seguir_final and estaba_al_final and not seleccion_activa:
        caja.see("end")
    return texto_nuevo


def copiar_texto(ventana, caja, *, solo_seleccion: bool = False) -> str:
    """Copia la selección o, si se solicita, la transcripción completa."""
    texto = obtener_seleccion(caja) if solo_seleccion else ""
    if not texto and not solo_seleccion:
        try:
            texto = caja.get("1.0", "end-1c").strip()
        except Exception:
            texto = ""
    if texto:
        ventana.clipboard_clear()
        ventana.clipboard_append(texto)
    return texto
