"""Download dei PDF e delle immagini trovati dal crawler.

I file vengono salvati in assets/documents e assets/images; index.json
collega ogni nome di file al suo URL di origine, così le schede prodotto e le
immagini possono rimandare al documento pubblicato. I file già scaricati non
vengono riscaricati.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import unquote, urlsplit

import httpx

from quuipu.config import ClientConfig
from quuipu.ingestion.crawler import USER_AGENT
from quuipu.ingestion.images import MAX_IMAGE_BYTES, MIME_TYPES

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
KINDS = {
    "documents": ({".pdf"}, MAX_DOCUMENT_BYTES),
    "images": (set(MIME_TYPES), MAX_IMAGE_BYTES),
}


def _registered_host(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def is_client_asset(url: str, client: ClientConfig) -> bool:
    """Solo file del dominio del cliente (anche sottodomini, es. cdn.cliente.it)."""
    host = urlsplit(url).netloc.lower()
    domain = _registered_host(urlsplit(client.base_url).netloc.lower())
    return host == domain or host.endswith("." + domain)


def asset_filename(url: str, taken: dict[str, str]) -> str:
    """Nome del file dall'URL; in caso di omonimi aggiunge un pezzo di hash."""
    name = unquote(PurePosixPath(urlsplit(url).path).name) or "file"
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    if taken.get(name, url) != url:
        path = PurePosixPath(name)
        name = f"{path.stem}-{hashlib.sha1(url.encode()).hexdigest()[:6]}{path.suffix}"
    return name


def download_assets(
    client: ClientConfig,
    manifest: dict,
    out_dir: Path,
    http: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    http = http or httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True,
        timeout=client.crawl.timeout_seconds,
    )
    index_path = out_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    index.setdefault("documents", {})
    index.setdefault("images", {})
    index["errori"] = []
    downloaded = 0

    sources = {"documents": manifest.get("documents", []), "images": manifest.get("images", [])}
    for kind, entries in sources.items():
        extensions, max_bytes = KINDS[kind]
        folder = out_dir / kind
        folder.mkdir(parents=True, exist_ok=True)
        files: dict[str, str] = index[kind]
        known_urls = {url: name for name, url in files.items()}
        for entry in entries:
            url = entry["url"]
            if PurePosixPath(urlsplit(url).path).suffix.lower() not in extensions:
                continue
            if not is_client_asset(url, client):
                continue
            name = known_urls.get(url) or asset_filename(url, files)
            if (folder / name).exists():
                files[name] = url
                continue
            if downloaded and client.crawl.delay_seconds:
                sleep(client.crawl.delay_seconds)
            downloaded += 1
            try:
                response = http.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                index["errori"].append({"url": url, "errore": str(exc)})
                continue
            if len(response.content) > max_bytes:
                index["errori"].append({"url": url, "errore": "file troppo grande"})
                continue
            (folder / name).write_bytes(response.content)
            files[name] = url
            known_urls[url] = name

    out_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index
