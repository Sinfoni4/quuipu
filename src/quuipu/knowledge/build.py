"""Costruzione dei contenuti della base di conoscenza dai risultati dell'ingestione.

Unisce pagine del sito, schede prodotto e immagini con la loro classificazione.
I motivi di revisione dell'estrazione e della classificazione si sommano.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quuipu.knowledge.store import Content


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def content_hash(*parts: object) -> str:
    """Impronta del contenuto: cambia solo se cambia ciò che il visitatore vedrebbe."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _without(record: dict, *keys: str) -> dict:
    return {k: v for k, v in record.items() if k not in keys}


def build_contents(base_dir: Path, default_language: str = "") -> list[Content]:
    classification = {
        c["id"]: c for c in _read(base_dir / "knowledge" / "classification.json").get("contenuti", [])
    }
    assets = _read(base_dir / "assets" / "index.json")
    document_urls: dict[str, str] = assets.get("documents", {})
    image_urls: dict[str, str] = assets.get("images", {})

    def classified(content_id: str, fixed_type: str | None) -> tuple[str, list[str], list[str]]:
        c = classification.get(content_id)
        if c is None:
            return fixed_type or "altro", [], ["contenuto non ancora classificato"]
        return c["tipo"], c["profili"], list(c["revisione"]["motivi"])

    contents: list[Content] = []

    for path in sorted((base_dir / "crawl" / "pages").glob("*.json")):
        page = _read(path)
        tipo, profili, motivi = classified(page["id"], None)
        contents.append(Content(
            id=page["id"], fonte="pagina", tipo=tipo, profili=profili, motivi=motivi,
            lingua=page.get("lang", default_language), titolo=page.get("title", ""),
            testo=page.get("text", ""), url=page["url"],
            dati={
                "descrizione": page.get("description", ""),
                "intestazioni": page.get("headings", []),
                "immagini": page.get("images", []),
                "documenti": page.get("documents", []),
                "traduzioni": page.get("alternates", {}),
            },
            hash=page.get("content_hash") or content_hash(page.get("title"), page.get("text")),
        ))

    for product in _read(base_dir / "knowledge" / "products.json").get("prodotti", []):
        tipo, profili, motivi = classified(product["id"], "prodotto")
        specs = "\n".join(f"{k}: {v}" for k, v in product.get("specifiche", {}).items())
        dati = _without(product, "id", "tipo", "confidenza", "revisione")
        dati["documenti_url"] = [document_urls[d] for d in product.get("documenti", []) if d in document_urls]
        contents.append(Content(
            id=product["id"], fonte="prodotto", tipo=tipo, profili=profili,
            motivi=list(product["revisione"]["motivi"]) + motivi,
            lingua=default_language, titolo=product["nome"],
            testo="\n".join(t for t in (product.get("descrizione", ""), specs) if t),
            url=dati["documenti_url"][0] if dati["documenti_url"] else "",
            dati=dati, hash=content_hash(dati),
        ))

    for image in _read(base_dir / "knowledge" / "images.json").get("immagini", []):
        tipo, profili, motivi = classified(image["id"], "immagine")
        dati = _without(image, "id", "tipo", "confidenza", "revisione")
        contents.append(Content(
            id=image["id"], fonte="immagine", tipo=tipo, profili=profili,
            motivi=list(image["revisione"]["motivi"]) + motivi,
            lingua=image.get("lingua", default_language), titolo="",
            testo="\n".join([image.get("descrizione", ""), ", ".join(image.get("tag", []))]).strip(),
            url=image_urls.get(image["file"], ""),
            dati=dati, hash=content_hash(dati),
        ))

    return contents
