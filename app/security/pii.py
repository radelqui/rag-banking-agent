"""Enmascarado de PII antes de enviar contexto al modelo de frontera, a logs o al cliente.

Dos usos:
- mask_pii(texto)     → texto completo (contexto recuperado, logs, tool outputs).
- StreamMasker        → salida en streaming. Un IBAN o un DNI llegan partidos en varios
                        tokens; enmascarar token a token NO los detecta. El masker acumula
                        y solo emite texto cuando ninguna entidad puede quedar cortada.
"""
import re

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b")
DNI_RE = re.compile(r"\b\d{8}[A-Z]\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask_pii(text: str) -> str:
    text = IBAN_RE.sub("[IBAN]", text)
    text = DNI_RE.sub("[DNI]", text)
    text = CARD_RE.sub("[TARJETA]", text)
    text = EMAIL_RE.sub("[EMAIL]", text)
    return text


# Ninguna de las entidades anteriores puede contener un salto de línea ni ". " (punto+espacio):
# el IBAN/DNI/tarjeta no llevan puntos y el email termina en el primer espacio.
_SAFE_BOUNDARY = re.compile(r"(?:\.\s|\n)")
# Longitud máxima de una entidad (IBAN con espacios ≈ 42). Si el buffer supera este tamaño
# sin frontera segura, cortamos en un espacio dejando al menos esta cola sin emitir.
_MAX_ENTITY = 48


class StreamMasker:
    """Enmascara PII sobre un flujo de tokens sin que las entidades se escapen partidas."""

    def __init__(self, max_buffer: int = 400):
        self._buf = ""
        self._max_buffer = max_buffer

    def feed(self, token: str) -> str:
        """Añade un token y devuelve el texto ya seguro para emitir ("" si aún no hay)."""
        self._buf += token
        cut = self._safe_cut()
        if cut <= 0:
            return ""
        out, self._buf = self._buf[:cut], self._buf[cut:]
        return mask_pii(out)

    def flush(self) -> str:
        """Al terminar el stream: enmascara y vacía todo lo retenido."""
        out, self._buf = self._buf, ""
        return mask_pii(out)

    def _safe_cut(self) -> int:
        # 1) Última frontera segura (fin de frase o salto de línea): nada puede cruzarla.
        last = None
        for m in _SAFE_BOUNDARY.finditer(self._buf):
            last = m.end()
        if last:
            return last
        # 2) Sin frontera pero buffer largo: corta en un espacio dejando cola suficiente
        #    para que una entidad en curso no quede partida entre lo emitido y lo retenido.
        if len(self._buf) > self._max_buffer:
            limit = len(self._buf) - _MAX_ENTITY
            space = self._buf.rfind(" ", 0, limit)
            return space + 1 if space > 0 else 0
        return 0
