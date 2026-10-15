"""Crawler del sito esistente del cliente (specifica §4.1 e §4.7).

Scarica le pagine pubbliche partendo dalle sitemap e dai link interni,
rispetta robots.txt e le esclusioni del cliente, ed estrae da ogni pagina
testo, titoli, immagini e documenti. Salva una pagina JSON per URL e un
manifest con le differenze rispetto al passaggio precedente.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from quuipu.config import ClientConfig, data_dir, load_client

USER_AGENT = "QuuipuBot/0.1 (+https://quuipu.me)"

DOCUMENT_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".avif"}
SKIP_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | {
    ".zip", ".mp3", ".mp4", ".mov", ".css", ".js", ".xml", ".json",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt",
}
# Elementi che non contengono contenuto della pagina (menu, piè di pagina, script).
NOISE_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "form",
              "nav", "header", "footer"]
MAX_SITEMAPS = 50


@dataclass
class Page:
    id: str
    url: str
    lang: str
    title: str
    description: str
    headings: list[str]
    text: str
    images: list[dict[str, str]]
    documents: list[dict[str, str]]
    links: list[str]
    alternates: dict[str, str]
    content_hash: str
    fetched_at: str = ""


@dataclass
class CrawlResult:
    pages: list[Page] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)


def _extension(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def normalize_url(url: str, base: str | None = None) -> str | None:
    """URL assoluto, senza frammento e query, con barra finale per le pagine."""
    absolute, _ = urldefrag(urljoin(base, url.strip()) if base else url.strip())
    parts = urlsplit(absolute)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    path = parts.path or "/"
    if not path.endswith("/") and not _extension(path):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


def page_id(url: str) -> str:
    """Identificatore stabile della pagina, derivato dall'URL."""
    return "page-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _lang_from_path(url: str, languages: tuple[str, ...]) -> str:
    first = urlsplit(url).path.strip("/").split("/")[0].lower()
    if first in languages:
        return first
    return languages[0] if languages else ""


def parse_page(url: str, html: str, languages: tuple[str, ...] = ()) -> Page:
    soup = BeautifulSoup(html, "html.parser")

    html_tag = soup.find("html")
    lang = ""
    if html_tag and html_tag.get("lang"):
        lang = html_tag["lang"].split("-")[0].lower()
    if not lang:
        lang = _lang_from_path(url, languages)

    title = _clean(soup.title.get_text()) if soup.title else ""
    description = ""
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and meta.get("content"):
            description = _clean(meta["content"])
            break

    alternates: dict[str, str] = {}
    for link in soup.find_all("link", rel="alternate", hreflang=True):
        code = link["hreflang"].split("-")[0].lower()
        href = normalize_url(link.get("href", ""), url)
        if href and code != "x" and code not in alternates:
            alternates[code] = href

    # Link e documenti si raccolgono da tutta la pagina, menu compresi,
    # perché servono a scoprire le altre pagine del sito.
    links: list[str] = []
    documents: list[dict[str, str]] = []
    seen_links: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"], url)
        if not href or href in seen_links:
            continue
        seen_links.add(href)
        if _extension(urlsplit(href).path) in DOCUMENT_EXTENSIONS:
            documents.append({"url": href, "title": _clean(a.get_text())})
        else:
            links.append(href)

    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup

    headings = [_clean(h.get_text()) for h in root.find_all(["h1", "h2", "h3"])]
    headings = [h for h in headings if h]

    images: list[dict[str, str]] = []
    seen_images: set[str] = set()
    for img in root.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        if src.startswith("data:"):
            continue
        absolute = urljoin(url, src.strip())
        if not src or absolute in seen_images:
            continue
        seen_images.add(absolute)
        images.append({"url": absolute, "alt": _clean(img.get("alt", ""))})

    lines: list[str] = []
    for line in root.get_text("\n").splitlines():
        line = _clean(line)
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    text = "\n".join(lines)

    return Page(
        id=page_id(url),
        url=url,
        lang=lang,
        title=title,
        description=description,
        headings=headings,
        text=text,
        images=images,
        documents=documents,
        links=links,
        alternates=alternates,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


class Crawler:
    def __init__(
        self,
        client: ClientConfig,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.settings = client.crawl
        self.base = normalize_url(client.base_url) or client.base_url
        self.host = urlsplit(self.base).netloc
        self.http = http or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=self.settings.timeout_seconds,
        )
        self.sleep = sleep
        self.robots = RobotFileParser()
        self._requests = 0

    def _get(self, url: str) -> httpx.Response:
        if self._requests and self.settings.delay_seconds:
            self.sleep(self.settings.delay_seconds)
        self._requests += 1
        return self.http.get(url)

    def is_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.netloc != self.host:
            return False
        if _extension(parts.path) in SKIP_EXTENSIONS:
            return False
        if any(pattern in parts.path for pattern in self.settings.exclude):
            return False
        return self.robots.can_fetch(USER_AGENT, url)

    def _load_robots(self) -> list[str]:
        robots_url = urljoin(self.base, "/robots.txt")
        try:
            response = self._get(robots_url)
            lines = response.text.splitlines() if response.status_code == 200 else []
        except httpx.HTTPError:
            lines = []
        self.robots.parse(lines)
        return self.robots.site_maps() or [urljoin(self.base, "/sitemap.xml")]

    def _sitemap_urls(self, sitemaps: list[str], result: CrawlResult) -> list[str]:
        """URL delle pagine elencate nelle sitemap, seguendo gli indici."""
        queue = deque(s for s in sitemaps if _extension(urlsplit(s).path) == ".xml")
        visited: set[str] = set()
        pages: list[str] = []
        while queue and len(visited) < MAX_SITEMAPS:
            sitemap = queue.popleft()
            if sitemap in visited:
                continue
            visited.add(sitemap)
            try:
                response = self._get(sitemap)
                response.raise_for_status()
                root = ET.fromstring(response.content)
            except (httpx.HTTPError, ET.ParseError) as exc:
                result.errors.append({"url": sitemap, "error": str(exc)})
                continue
            locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
            if root.tag.endswith("sitemapindex"):
                queue.extend(locs)
            else:
                pages.extend(locs)
        return pages

    def run(self) -> CrawlResult:
        result = CrawlResult()
        sitemaps = self._load_robots()

        queue: deque[str] = deque([self.base])
        seen: set[str] = {self.base}
        for loc in self._sitemap_urls(sitemaps, result):
            url = normalize_url(loc)
            if url and url not in seen:
                seen.add(url)
                queue.append(url)

        done: set[str] = set()
        while queue and len(result.pages) < self.settings.max_pages:
            url = queue.popleft()
            if not self.is_allowed(url):
                continue
            try:
                response = self._get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                result.errors.append({"url": url, "error": str(exc)})
                continue
            if "text/html" not in response.headers.get("content-type", ""):
                continue
            # Dopo un redirect conta l'URL finale, per non salvare due volte la stessa pagina.
            final_url = normalize_url(str(response.url)) or url
            if final_url in done or not self.is_allowed(final_url):
                continue
            done.add(final_url)

            page = parse_page(final_url, response.text, self.client.languages)
            page.fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result.pages.append(page)

            for link in page.links + list(page.alternates.values()):
                if link not in seen and self.is_allowed(link):
                    seen.add(link)
                    queue.append(link)
        return result


def save_result(client: ClientConfig, result: CrawlResult, out_dir: Path | None = None) -> dict:
    """Salva le pagine e il manifest; restituisce il manifest con le differenze."""
    out_dir = out_dir or data_dir() / client.id / "crawl"
    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"

    previous: dict[str, str] = {}
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous = {p["id"]: p["content_hash"] for p in old.get("pages", [])}

    current = {p.id: p.content_hash for p in result.pages}
    changes = {
        "new": sorted(i for i in current if i not in previous),
        "changed": sorted(i for i in current if i in previous and previous[i] != current[i]),
        "removed": sorted(i for i in previous if i not in current),
    }

    for page in result.pages:
        (pages_dir / f"{page.id}.json").write_text(
            json.dumps(asdict(page), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    documents = {d["url"]: d for p in result.pages for d in p.documents}
    images = {i["url"]: i for p in result.pages for i in p.images}
    manifest = {
        "client": client.id,
        "crawled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages": [
            {"id": p.id, "url": p.url, "lang": p.lang, "title": p.title,
             "content_hash": p.content_hash}
            for p in result.pages
        ],
        "documents": list(documents.values()),
        "images": list(images.values()),
        "changes": changes,
        "errors": result.errors,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scarica il sito di un cliente Quuipu.")
    parser.add_argument("client", help="ID del cliente (file in clients/)")
    parser.add_argument("--max-pages", type=int, help="limite di pagine per questo passaggio")
    args = parser.parse_args(argv)

    client = load_client(args.client)
    if args.max_pages:
        client = replace(client, crawl=replace(client.crawl, max_pages=args.max_pages))

    result = Crawler(client).run()
    manifest = save_result(client, result)
    changes = manifest["changes"]
    print(
        f"{len(result.pages)} pagine, {len(manifest['documents'])} documenti, "
        f"{len(manifest['images'])} immagini, {len(result.errors)} errori. "
        f"Nuove: {len(changes['new'])}, modificate: {len(changes['changed'])}, "
        f"rimosse: {len(changes['removed'])}."
    )


if __name__ == "__main__":
    main()
