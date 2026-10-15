"""Analisi delle foto del cliente (specifica §4.3).

Per ogni immagine un modello vision produce descrizione, tag e categoria.
La categoria deve appartenere all'elenco chiuso del cliente; le immagini con
confidenza bassa o categoria non valida vanno in coda di revisione.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from quuipu.config import ClientConfig, data_dir, load_client
from quuipu.ingestion.llm import ImageInput, LLMClient, LLMError, vision_client
from quuipu.ingestion.review import confidence, review_status

MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TAGS = 10

SYSTEM_PROMPT = (
    "Descrivi le immagini di un'azienda per un archivio di contenuti. "
    "Descrivi solo ciò che si vede: non dedurre nomi di prodotti, luoghi o persone "
    "che non siano leggibili nell'immagine. Rispondi solo con un oggetto JSON."
)

USER_PROMPT = """Azienda: {company} (settore: {sector}).
Descrivi l'immagine in {language}.

Formato della risposta:
{{"descrizione": "una o due frasi", "tag": ["parole chiave"],
"categoria": una tra {categories}, "confidenza": numero tra 0 e 1}}"""

LANGUAGE_NAMES = {"it": "italiano", "en": "inglese", "de": "tedesco", "fr": "francese", "es": "spagnolo"}


def image_id(data: bytes) -> str:
    """Identificatore stabile, derivato dal contenuto: la stessa foto ha sempre lo stesso ID."""
    return "img-" + hashlib.sha1(data).hexdigest()[:12]


def describe_image(client: ClientConfig, path: Path, llm: LLMClient) -> dict:
    mime = MIME_TYPES.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"formato non supportato: {path.suffix}")
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"immagine troppo grande ({len(data) // 1024} KB)")

    settings = client.ingestion
    language = client.languages[0] if client.languages else "it"
    prompt = USER_PROMPT.format(
        company=client.name,
        sector=client.sector,
        language=LANGUAGE_NAMES.get(language, language),
        categories=", ".join(f'"{c}"' for c in settings.image_categories),
    )
    response = llm.complete_json(SYSTEM_PROMPT, prompt, [ImageInput(data, mime)])

    description = str(response.get("descrizione") or "").strip()
    raw_tags = response.get("tag") or []
    tags: list[str] = []
    for tag in raw_tags if isinstance(raw_tags, list) else []:
        tag = str(tag).strip().lower()
        if tag and tag not in tags:
            tags.append(tag)
    score = confidence(response.get("confidenza"))

    reasons: list[str] = []
    category = str(response.get("categoria") or "").strip().lower()
    if category not in settings.image_categories:
        reasons.append(f"categoria '{category}' non prevista")
        category = "altro" if "altro" in settings.image_categories else ""
    if not description:
        reasons.append("descrizione mancante")

    return {
        "id": image_id(data),
        "tipo": "immagine",
        "file": path.name,
        "lingua": language,
        "descrizione": description,
        "tag": tags[:MAX_TAGS],
        "categoria": category,
        "confidenza": score,
        "revisione": review_status(score, settings.confidence_threshold, reasons),
    }


def describe_images(
    client: ClientConfig, folder: Path, llm: LLMClient, out_dir: Path | None = None
) -> dict:
    """Analizza le immagini della cartella e salva il risultato in images.json."""
    images: dict[str, dict] = {}
    errors: list[dict[str, str]] = []
    for path in sorted(p for p in folder.rglob("*") if p.suffix.lower() in MIME_TYPES):
        try:
            data_id = image_id(path.read_bytes())
            if data_id in images:  # stessa foto salvata con un altro nome
                continue
            images[data_id] = describe_image(client, path, llm)
        except (ValueError, OSError, LLMError) as exc:
            errors.append({"file": path.name, "errore": str(exc)})

    result = {
        "client": client.id,
        "immagini": list(images.values()),
        "errori": errors,
        "da_rivedere": sum(1 for i in images.values() if i["revisione"]["necessaria"]),
    }
    out_dir = out_dir or data_dir() / client.id / "knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "images.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Descrive le immagini di un cliente.")
    parser.add_argument("client", help="ID del cliente (file in clients/)")
    parser.add_argument("folder", type=Path, help="cartella con le immagini")
    args = parser.parse_args(argv)

    result = describe_images(load_client(args.client), args.folder, vision_client())
    print(
        f"{len(result['immagini'])} immagini, {result['da_rivedere']} da rivedere, "
        f"{len(result['errori'])} errori."
    )


if __name__ == "__main__":
    main()
