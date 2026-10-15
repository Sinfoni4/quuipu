"""Parsing di cataloghi e PDF in schede prodotto (specifica §4.2).

Il testo di ogni PDF viene estratto pagina per pagina, diviso in blocchi e
passato al modello, che restituisce le schede prodotto in JSON. Ogni scheda
viene poi controllata: i valori che non compaiono nel documento, i prezzi,
le specifiche e le certificazioni mandano la scheda in coda di revisione.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from quuipu.config import ClientConfig, data_dir, load_client
from quuipu.ingestion.llm import LLMClient, LLMError, text_client
from quuipu.ingestion.review import confidence, found_in_source, review_status

MAX_CHUNK_CHARS = 12_000

SYSTEM_PROMPT = (
    "Estrai dati strutturati dai documenti di un'azienda. "
    "Usa solo informazioni presenti nel testo fornito e non aggiungere nulla: "
    "se un dato manca, lascia il campo vuoto. "
    "Riporta valori, unità e nomi esattamente come sono scritti. "
    "Rispondi solo con un oggetto JSON."
)

USER_PROMPT = """Azienda: {company} (settore: {sector}).
Estrai le schede prodotto dal testo seguente, tratto dalle pagine {start}-{end} del documento "{filename}".

Formato della risposta:
{{"prodotti": [{{"nome": "...", "categoria": "...", "descrizione": "...",
"specifiche": {{"nome della specifica": "valore"}}, "certificazioni": ["..."],
"prezzo": "..." oppure null, "confidenza": numero tra 0 e 1}}]}}

La confidenza indica quanto sei sicuro che la scheda sia completa e corretta.
Se il testo non contiene prodotti, rispondi {{"prodotti": []}}.

TESTO:
{text}"""


def extract_pdf_pages(path: Path) -> list[str]:
    reader = PdfReader(path)
    return [(page.extract_text() or "").strip() for page in reader.pages]


def chunk_pages(pages: list[str], max_chars: int = MAX_CHUNK_CHARS) -> list[tuple[int, int, str]]:
    """Raggruppa le pagine in blocchi (prima pagina, ultima pagina, testo)."""
    chunks: list[tuple[int, int, str]] = []
    start, parts, size = 0, [], 0
    for number, text in enumerate(pages, start=1):
        if not text:
            continue
        if parts and size + len(text) > max_chars:
            chunks.append((start, number - 1, "\n\n".join(parts)))
            parts, size = [], 0
        if not parts:
            start = number
        parts.append(text[:max_chars])
        size += len(parts[-1])
    if parts:
        chunks.append((start, len(pages), "\n\n".join(parts)))
    return chunks


def product_id(filename: str, name: str) -> str:
    key = f"{filename}|{name.strip().lower()}"
    return "prod-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _as_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def build_product(
    raw: dict, filename: str, pages: tuple[int, int], source_text: str, threshold: float
) -> dict | None:
    """Normalizza una scheda restituita dal modello e decide se va rivista."""
    name = _as_text(raw.get("nome"))
    if not name:
        return None

    specs_raw = raw.get("specifiche") or {}
    specs = {
        _as_text(k): _as_text(v)
        for k, v in (specs_raw.items() if isinstance(specs_raw, dict) else [])
        if _as_text(k) and _as_text(v)
    }
    certs_raw = raw.get("certificazioni") or []
    certs = [_as_text(c) for c in certs_raw if _as_text(c)] if isinstance(certs_raw, list) else []
    price = _as_text(raw.get("prezzo")) or None
    score = confidence(raw.get("confidenza"))

    reasons: list[str] = []
    if not found_in_source(name, source_text):
        reasons.append(f"nome '{name}' non trovato nel documento")
    for key, value in specs.items():
        if not found_in_source(value, source_text):
            reasons.append(f"specifica '{key}: {value}' non trovata nel documento")
    if price and not found_in_source(price, source_text):
        reasons.append(f"prezzo '{price}' non trovato nel documento")
    for cert in certs:
        if not found_in_source(cert, source_text):
            reasons.append(f"certificazione '{cert}' non trovata nel documento")
    # Prezzi, specifiche e claim vanno sempre confermati dal cliente (§4.6).
    if price:
        reasons.append("prezzo da confermare")
    if specs:
        reasons.append("specifiche tecniche da confermare")
    if certs:
        reasons.append("certificazioni da confermare")

    return {
        "id": product_id(filename, name),
        "tipo": "prodotto",
        "nome": name,
        "categoria": _as_text(raw.get("categoria")),
        "descrizione": _as_text(raw.get("descrizione")),
        "specifiche": specs,
        "certificazioni": certs,
        "prezzo": price,
        "documenti": [filename],
        "fonte": {"file": filename, "pagine": list(pages)},
        "confidenza": score,
        "revisione": review_status(score, threshold, reasons),
    }


def parse_pdf(client: ClientConfig, path: Path, llm: LLMClient) -> tuple[list[dict], dict]:
    """Schede prodotto estratte da un PDF e riepilogo del file."""
    summary: dict = {"file": path.name, "pagine": 0, "prodotti": 0, "errori": []}
    try:
        pages = extract_pdf_pages(path)
    except (PdfReadError, OSError) as exc:
        summary["errori"].append(f"PDF non leggibile: {exc}")
        return [], summary
    summary["pagine"] = len(pages)

    chunks = chunk_pages(pages)
    if not chunks:
        summary["errori"].append("nessun testo estraibile (forse è una scansione)")
        return [], summary

    products: dict[str, dict] = {}
    for start, end, text in chunks:
        prompt = USER_PROMPT.format(
            company=client.name, sector=client.sector, start=start, end=end,
            filename=path.name, text=text,
        )
        try:
            response = llm.complete_json(SYSTEM_PROMPT, prompt)
        except LLMError as exc:
            summary["errori"].append(f"pagine {start}-{end}: {exc}")
            continue
        raw_products = response.get("prodotti")
        if not isinstance(raw_products, list):
            summary["errori"].append(f"pagine {start}-{end}: risposta senza elenco 'prodotti'")
            continue
        for raw in raw_products:
            if not isinstance(raw, dict):
                continue
            product = build_product(
                raw, path.name, (start, end), text, client.ingestion.confidence_threshold
            )
            # Lo stesso prodotto può comparire in più blocchi: si tiene la scheda più sicura.
            if product and (
                product["id"] not in products
                or product["confidenza"] > products[product["id"]]["confidenza"]
            ):
                products[product["id"]] = product

    summary["prodotti"] = len(products)
    return list(products.values()), summary


def parse_documents(
    client: ClientConfig, folder: Path, llm: LLMClient, out_dir: Path | None = None
) -> dict:
    """Analizza tutti i PDF della cartella e salva le schede in products.json."""
    products: list[dict] = []
    files: list[dict] = []
    for path in sorted(folder.rglob("*.pdf")):
        found, summary = parse_pdf(client, path, llm)
        products.extend(found)
        files.append(summary)

    result = {
        "client": client.id,
        "prodotti": products,
        "documenti": files,
        "da_rivedere": sum(1 for p in products if p["revisione"]["necessaria"]),
    }
    out_dir = out_dir or data_dir() / client.id / "knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "products.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Estrae schede prodotto dai PDF di un cliente.")
    parser.add_argument("client", help="ID del cliente (file in clients/)")
    parser.add_argument("folder", type=Path, help="cartella con i PDF")
    args = parser.parse_args(argv)

    result = parse_documents(load_client(args.client), args.folder, text_client())
    errors = sum(len(d["errori"]) for d in result["documenti"])
    print(
        f"{len(result['documenti'])} PDF, {len(result['prodotti'])} schede prodotto, "
        f"{result['da_rivedere']} da rivedere, {errors} errori."
    )


if __name__ == "__main__":
    main()
