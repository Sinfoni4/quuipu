"""Classificazione dei contenuti per tipo e profilo di visitatore (specifica §4.4).

Ogni contenuto (pagina del sito, scheda prodotto, immagine) riceve un tipo
da un elenco chiuso e uno o più profili di visitatore tra quelli del cliente.
Prodotti e immagini hanno già il tipo: al modello si chiedono solo i profili.
I contenuti vengono inviati al modello a gruppi, per ridurre le chiamate.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from quuipu.config import ClientConfig, data_dir, load_client
from quuipu.ingestion.llm import LLMClient, LLMError, text_client
from quuipu.ingestion.review import confidence, review_status

# Tipi ammessi per le pagine; "notizia" e "altro" si aggiungono a quelli della
# specifica perché i siti dei clienti hanno news e pagine di servizio (privacy, ecc.).
CONTENT_TYPES = {
    "prodotto": "scheda o presentazione di un prodotto o di una linea",
    "certificazione": "certificati, standard, premi e riconoscimenti",
    "case_study": "referenze e storie di clienti",
    "chi_siamo": "storia, valori, filosofia, territorio, persone dell'azienda",
    "faq": "domande e risposte ricorrenti",
    "contatto": "contatti, sedi, orari, moduli di richiesta, visite e degustazioni",
    "notizia": "news, eventi, comunicati",
    "altro": "pagine di servizio o non utili ai visitatori (privacy, note legali)",
}
FIXED_TYPES = {"prodotto": "prodotto", "immagine": "immagine"}
BATCH_SIZE = 10
MAX_TEXT_CHARS = 1500

SYSTEM_PROMPT = (
    "Classifichi i contenuti del sito di un'azienda per un assistente che adatta il sito "
    "al visitatore. Usa solo i tipi e i profili elencati, con i loro identificatori esatti. "
    "Rispondi solo con un oggetto JSON."
)

USER_PROMPT = """Azienda: {company} (settore: {sector}).

Tipi di contenuto ammessi:
{types}

Profili di visitatore:
{profiles}

Per ogni contenuto indica il tipo (se non è già indicato), i profili di visitatore
a cui è utile (uno o più; nessuno solo per il tipo "altro") e la confidenza.

Formato della risposta:
{{"classificazioni": [{{"id": "...", "tipo": "...", "profili": ["..."], "confidenza": numero tra 0 e 1}}]}}

CONTENUTI:
{items}"""


@dataclass(frozen=True)
class ContentItem:
    id: str
    source: str  # "pagina", "prodotto" o "immagine"
    summary: str

    @property
    def fixed_type(self) -> str | None:
        return FIXED_TYPES.get(self.source)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_items(client: ClientConfig, base_dir: Path | None = None) -> list[ContentItem]:
    """Raccoglie i contenuti prodotti da crawler, parsing dei PDF e analisi delle immagini."""
    base_dir = base_dir or data_dir() / client.id
    items: list[ContentItem] = []

    for path in sorted((base_dir / "crawl" / "pages").glob("*.json")):
        page = _read_json(path)
        summary = "\n".join([
            f"URL: {page['url']}",
            f"Titolo: {page.get('title', '')}",
            f"Intestazioni: {'; '.join(page.get('headings', [])[:10])}",
            f"Descrizione: {page.get('description', '')}",
            f"Testo: {page.get('text', '')[:MAX_TEXT_CHARS]}",
        ])
        items.append(ContentItem(page["id"], "pagina", summary))

    for product in _read_json(base_dir / "knowledge" / "products.json").get("prodotti", []):
        specs = "; ".join(f"{k}: {v}" for k, v in product.get("specifiche", {}).items())
        summary = "\n".join([
            f"Nome: {product['nome']}",
            f"Categoria: {product.get('categoria', '')}",
            f"Descrizione: {product.get('descrizione', '')}",
            f"Specifiche: {specs}",
        ])
        items.append(ContentItem(product["id"], "prodotto", summary))

    for image in _read_json(base_dir / "knowledge" / "images.json").get("immagini", []):
        summary = "\n".join([
            f"Descrizione: {image.get('descrizione', '')}",
            f"Tag: {', '.join(image.get('tag', []))}",
            f"Categoria: {image.get('categoria', '')}",
        ])
        items.append(ContentItem(image["id"], "immagine", summary))

    return items


def build_prompt(client: ClientConfig, batch: list[ContentItem]) -> str:
    types = "\n".join(f'- "{name}": {desc}' for name, desc in CONTENT_TYPES.items())
    profiles = "\n".join(
        f'- "{p.id}": {p.name}. Cerca: {p.looks_for}. Gli interessa: {p.highlight}.'
        for p in client.profiles
    )
    blocks = []
    for item in batch:
        header = f"### id: {item.id} (fonte: {item.source}"
        header += f", tipo già noto: {item.fixed_type})" if item.fixed_type else ")"
        blocks.append(f"{header}\n{item.summary}")
    return USER_PROMPT.format(
        company=client.name, sector=client.sector, types=types, profiles=profiles,
        items="\n\n".join(blocks),
    )


def build_classification(client: ClientConfig, item: ContentItem, raw: dict | None) -> dict:
    """Normalizza la risposta del modello per un contenuto e decide se va rivista."""
    reasons: list[str] = []
    raw = raw or {}
    if not raw:
        reasons.append("nessuna classificazione restituita dal modello")

    if item.fixed_type:
        content_type = item.fixed_type
    else:
        content_type = str(raw.get("tipo") or "").strip().lower()
        if content_type not in CONTENT_TYPES:
            if raw:
                reasons.append(f"tipo '{content_type}' non previsto")
            content_type = "altro"

    known = {p.id for p in client.profiles}
    raw_profiles = raw.get("profili") or []
    profiles: list[str] = []
    for profile in raw_profiles if isinstance(raw_profiles, list) else []:
        profile = str(profile).strip().lower()
        if profile not in known:
            reasons.append(f"profilo '{profile}' non previsto")
        elif profile not in profiles:
            profiles.append(profile)
    if not profiles and content_type != "altro" and raw:
        reasons.append("nessun profilo di visitatore assegnato")

    score = confidence(raw.get("confidenza"))
    return {
        "id": item.id,
        "fonte": item.source,
        "tipo": content_type,
        "profili": profiles,
        "confidenza": score,
        "revisione": review_status(score, client.ingestion.confidence_threshold, reasons),
    }


def classify_items(
    client: ClientConfig, items: list[ContentItem], llm: LLMClient
) -> tuple[list[dict], list[dict]]:
    """Classificazioni dei contenuti ed errori dei gruppi non elaborati."""
    results: list[dict] = []
    errors: list[dict] = []
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        try:
            response = llm.complete_json(SYSTEM_PROMPT, build_prompt(client, batch))
        except LLMError as exc:
            errors.append({"id": [i.id for i in batch], "errore": str(exc)})
            continue
        raw_list = response.get("classificazioni")
        by_id = {
            str(r.get("id")): r
            for r in (raw_list if isinstance(raw_list, list) else [])
            if isinstance(r, dict)
        }
        # I contenuti dimenticati dal modello restano nel risultato, in revisione.
        results.extend(build_classification(client, i, by_id.get(i.id)) for i in batch)
    return results, errors


def classify_contents(
    client: ClientConfig, llm: LLMClient, base_dir: Path | None = None
) -> dict:
    """Classifica tutti i contenuti del cliente e salva classification.json."""
    base_dir = base_dir or data_dir() / client.id
    results, errors = classify_items(client, load_items(client, base_dir), llm)

    by_profile = {p.id: sum(1 for r in results if p.id in r["profili"]) for p in client.profiles}
    result = {
        "client": client.id,
        "contenuti": results,
        "per_profilo": by_profile,
        "errori": errors,
        "da_rivedere": sum(1 for r in results if r["revisione"]["necessaria"]),
    }
    out_dir = base_dir / "knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "classification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Classifica i contenuti di un cliente per tipo e profilo di visitatore."
    )
    parser.add_argument("client", help="ID del cliente (file in clients/)")
    args = parser.parse_args(argv)

    result = classify_contents(load_client(args.client), text_client())
    per_profile = ", ".join(f"{k}: {v}" for k, v in result["per_profilo"].items())
    print(
        f"{len(result['contenuti'])} contenuti classificati, {result['da_rivedere']} da rivedere, "
        f"{len(result['errori'])} gruppi con errori. Per profilo: {per_profile}."
    )


if __name__ == "__main__":
    main()
