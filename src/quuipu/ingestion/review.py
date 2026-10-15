"""Confidenza e coda di revisione (specifica §4.5 e §4.6).

Un elemento va in revisione se la confidenza è sotto soglia, se contiene
prezzi, specifiche tecniche o claim (sempre da confermare), o se un valore
estratto non si ritrova nel testo di origine.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def confidence(value: object) -> float:
    """Confidenza tra 0 e 1; un valore mancante o non valido vale 0."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return min(max(number, 0.0), 1.0)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def found_in_source(value: str, source: str) -> bool:
    """Vero se il valore compare nel testo, o almeno tutti i suoi numeri."""
    value_norm = _norm(value)
    if not value_norm:
        return True
    source_norm = _norm(source)
    if value_norm in source_norm:
        return True
    numbers = NUMBER.findall(value_norm)
    if not numbers:
        return False
    source_numbers = {n.replace(",", ".") for n in NUMBER.findall(source_norm)}
    return all(n.replace(",", ".") in source_numbers for n in numbers)


def review_status(score: float, threshold: float, reasons: list[str]) -> dict:
    reasons = list(reasons)
    if score < threshold:
        reasons.insert(0, f"confidenza {score:.2f} sotto la soglia {threshold:.2f}")
    return {"necessaria": bool(reasons), "motivi": reasons}
