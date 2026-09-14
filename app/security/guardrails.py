"""Guardrails de entrada: detección básica de prompt injection y sanitización.

Es una capa defensiva ADEMÁS del mínimo privilegio en BD, no un sustituto.
"""
import re
from dataclasses import dataclass

INJECTION_PATTERNS = [
    r"ignor(a|e)\s+(todas\s+)?(las\s+)?instrucciones",
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"\bsystem\s*prompt\b",
    r"\b(drop|delete|truncate|alter|update|insert)\s+(table|from|into)\b",
    r"\bact\s+as\s+(root|admin|dba)\b",
    r"revela(r)?\s+(la\s+)?contraseña",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

MAX_PROMPT_CHARS = 4000


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reason: str | None = None
    sanitized: str = ""


def check_prompt(text: str) -> GuardrailResult:
    if not text or not text.strip():
        return GuardrailResult(False, "empty_prompt")
    if len(text) > MAX_PROMPT_CHARS:
        return GuardrailResult(False, "prompt_too_long")
    for pattern in _COMPILED:
        if pattern.search(text):
            return GuardrailResult(False, f"injection_pattern:{pattern.pattern}")
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return GuardrailResult(True, None, sanitized)
