"""Dal page plan ai dati che servono al widget per mostrare i blocchi.

Il piano cita solo ID; qui ogni ID viene sostituito dai dati pubblici del
contenuto, così come sono nella base di conoscenza. I testi aziendali non
vengono riscritti: al massimo si mostra l'inizio di un testo lungo.
"""

from __future__ import annotations

from quuipu.knowledge.store import APPROVED, KnowledgeStore

MAX_EXCERPT_CHARS = 400


def _excerpt(text: str) -> str:
    if len(text) <= MAX_EXCERPT_CHARS:
        return text
    cut = text.rfind(" ", 0, MAX_EXCERPT_CHARS)
    return text[:cut if cut > 0 else MAX_EXCERPT_CHARS].rstrip() + "…"


def public_content(content: dict) -> dict:
    """Solo i campi che il visitatore può vedere."""
    view = {
        "id": content["id"],
        "fonte": content["fonte"],
        "tipo": content["tipo"],
        "lingua": content["lingua"],
        "titolo": content["titolo"],
        "url": content["url"],
    }
    dati = content["dati"]
    if content["fonte"] == "pagina":
        images = dati.get("immagini") or []
        # Il titolo della pagina (h1) è già mostrato come titolo: non lo si ripete nel testo.
        lines = content["testo"].split("\n")
        headings = dati.get("intestazioni") or []
        if lines and headings and lines[0] == headings[0]:
            lines = lines[1:]
        view.update(
            descrizione=dati.get("descrizione", ""),
            estratto=_excerpt("\n".join(lines)),
            immagine=images[0] if images else None,
        )
    elif content["fonte"] == "prodotto":
        view.update(
            categoria=dati.get("categoria", ""),
            descrizione=dati.get("descrizione", ""),
            specifiche=dati.get("specifiche", {}),
            certificazioni=dati.get("certificazioni", []),
            prezzo=dati.get("prezzo"),
            documenti=dati.get("documenti_url", []),
        )
    elif content["fonte"] == "immagine":
        view.update(descrizione=dati.get("descrizione", ""), tag=dati.get("tag", []))
    return view


def approved_content(store: KnowledgeStore, content_id: str) -> dict | None:
    content = store.get(content_id)
    return public_content(content) if content and content["stato"] == APPROVED else None


def resolve_plan(plan: dict, store: KnowledgeStore) -> dict:
    blocks = []
    for block in plan["blocchi"]:
        resolved = dict(block)
        ids = block.get("contenuto_id")
        if ids:
            ids = ids if isinstance(ids, list) else [ids]
            resolved["contenuti"] = [c for c in (approved_content(store, i) for i in ids) if c]
        if block.get("immagine_id"):
            resolved["immagine"] = approved_content(store, block["immagine_id"])
        blocks.append(resolved)
    return dict(plan, blocchi=blocks)
