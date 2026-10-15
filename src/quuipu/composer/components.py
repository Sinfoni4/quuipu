"""Libreria dei componenti del PoC (specifica §8).

Ogni componente ha uno schema rigido: quali contenuti accetta (per tipo),
quanti, e quali varianti. L'agente può solo sceglierli e ordinarli.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    name: str
    purpose: str
    content_types: tuple[str, ...] = ()  # tipi ammessi per contenuto_id; vuoto = nessun contenuto
    min_items: int = 0
    max_items: int = 0
    multiple: bool = False  # contenuto_id è una lista
    variants: tuple[str, ...] = ()
    image: bool = False  # accetta immagine_id


# Le pagine del sito di tipo "altro" (privacy, note legali) non entrano mai in un componente.
PAGE_TYPES = ("chi_siamo", "prodotto", "certificazione", "case_study", "faq", "contatto", "notizia")

COMPONENTS: dict[str, Component] = {
    c.name: c
    for c in (
        Component(
            "hero", "messaggio di apertura adattato al profilo",
            content_types=PAGE_TYPES, min_items=1, max_items=1, image=True,
        ),
        Component(
            "griglia_prodotti", "selezione di prodotti pertinenti",
            content_types=("prodotto",), min_items=1, max_items=9, multiple=True,
        ),
        Component(
            "certificazioni", "certificati, standard e riconoscimenti",
            content_types=("certificazione",), min_items=1, max_items=6, multiple=True,
        ),
        Component(
            "case_study", "referenze e storie di clienti",
            content_types=("case_study",), min_items=1, max_items=3, multiple=True,
        ),
        Component(
            "faq", "risposte alle domande ricorrenti",
            content_types=("faq",), min_items=1, max_items=8, multiple=True,
        ),
        Component(
            "cta_contatto", "invito all'azione: contatto, preventivo, campione o degustazione",
            variants=("contatto", "preventivo", "campione", "degustazione"),
        ),
    )
}

CTA = "cta_contatto"
MAX_BLOCKS = 8


def describe_library() -> str:
    """Descrizione della libreria per il prompt dell'agente."""
    lines = []
    for c in COMPONENTS.values():
        parts = [f'- "{c.name}": {c.purpose}.']
        if c.content_types:
            how_many = "uno solo" if not c.multiple else f"da {c.min_items} a {c.max_items}"
            kind = "una stringa" if not c.multiple else "una lista"
            parts.append(
                f"contenuto_id: {kind}, {how_many}, di tipo {', '.join(c.content_types)}."
            )
        if c.image:
            parts.append("immagine_id facoltativo: un contenuto di tipo immagine.")
        if c.variants:
            parts.append(f"variante obbligatoria: {', '.join(c.variants)}.")
        lines.append(" ".join(parts))
    return "\n".join(lines)
