import json

import httpx

from quuipu.config import ClientConfig, CrawlSettings
from quuipu.ingestion.crawler import Crawler, normalize_url, page_id, parse_page, save_result

BASE = "https://www.cantina.test/"

ROBOTS = """User-agent: *
Disallow: /wp-admin/
Disallow: /privato/

Sitemap: https://www.cantina.test/sitemap.xml
"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.cantina.test/page-sitemap.xml</loc></sitemap>
</sitemapindex>"""

PAGE_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.cantina.test/la-filosofia/</loc></url>
  <url><loc>https://www.cantina.test/portal/login-page/</loc></url>
  <url><loc>https://www.cantina.test/privato/</loc></url>
</urlset>"""


def html(lang, title, body, head=""):
    return f"""<!doctype html><html lang="{lang}"><head><title>{title}</title>{head}</head>
<body><header><nav><a href="/">Home</a> <a href="/contatti">Contatti</a>
<a href="/en/">English</a></nav></header>
<main>{body}</main><footer>Footer © Cantina</footer></body></html>"""


PAGES = {
    "/": html(
        "it-IT", "Cantina",
        "<h1>Benvenuti</h1><p>Vini dal 1962.</p>"
        '<img src="/img/vigna.jpg" alt="Vigna"><a href="/docs/catalogo.pdf">Catalogo</a>',
        '<meta name="description" content="La cantina di famiglia">'
        '<link rel="alternate" hreflang="en-US" href="https://www.cantina.test/en/">',
    ),
    "/la-filosofia/": html("it-IT", "Filosofia", "<h2>La filosofia</h2><p>Rispetto per la terra.</p>"),
    "/contatti/": html("it-IT", "Contatti", "<p>Scrivici.</p>"),
    "/en/": html("en-US", "Winery", "<h1>Welcome</h1><p>Wines since 1962.</p>"),
    "/portal/login-page/": html("it-IT", "Login", "<p>Area riservata</p>"),
    "/privato/": html("it-IT", "Privato", "<p>Non pubblico</p>"),
}


def make_handler(requested):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requested.append(path)
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        if path == "/sitemap.xml":
            return httpx.Response(200, text=SITEMAP_INDEX, headers={"content-type": "application/xml"})
        if path == "/page-sitemap.xml":
            return httpx.Response(200, text=PAGE_SITEMAP, headers={"content-type": "application/xml"})
        if path == "/contatti":
            return httpx.Response(301, headers={"location": "https://www.cantina.test/contatti/"})
        if path in PAGES:
            return httpx.Response(200, text=PAGES[path], headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="not found")
    return handler


def make_client(**crawl):
    return ClientConfig(
        id="cantina",
        name="Cantina di prova",
        sector="agrifood",
        base_url=BASE,
        languages=("it", "en"),
        crawl=CrawlSettings(delay_seconds=0, exclude=("/portal/",), **crawl),
    )


def run_crawl(**crawl):
    requested = []
    http = httpx.Client(transport=httpx.MockTransport(make_handler(requested)), follow_redirects=True)
    result = Crawler(make_client(**crawl), http=http, sleep=lambda _: None).run()
    return result, requested


def test_normalize_url():
    assert normalize_url("/en/poggio#top", BASE) == "https://www.cantina.test/en/poggio/"
    assert normalize_url("https://WWW.cantina.test/a/?x=1") == "https://www.cantina.test/a/"
    assert normalize_url("/docs/catalogo.pdf", BASE) == "https://www.cantina.test/docs/catalogo.pdf"
    assert normalize_url("mailto:info@cantina.test", BASE) is None


def test_parse_page_extracts_content_without_menus():
    page = parse_page(BASE, PAGES["/"], ("it", "en"))
    assert page.id == page_id(BASE)
    assert page.lang == "it"
    assert page.title == "Cantina"
    assert page.description == "La cantina di famiglia"
    assert page.headings == ["Benvenuti"]
    assert "Vini dal 1962." in page.text
    assert "Footer" not in page.text and "Contatti" not in page.text
    assert page.images == [{"url": "https://www.cantina.test/img/vigna.jpg", "alt": "Vigna"}]
    assert page.documents == [{"url": "https://www.cantina.test/docs/catalogo.pdf", "title": "Catalogo"}]
    assert "https://www.cantina.test/contatti/" in page.links
    assert page.alternates == {"en": "https://www.cantina.test/en/"}


def test_crawl_follows_sitemaps_and_links_and_respects_exclusions():
    result, requested = run_crawl()
    urls = {p.url for p in result.pages}
    assert urls == {
        "https://www.cantina.test/",
        "https://www.cantina.test/la-filosofia/",
        "https://www.cantina.test/contatti/",
        "https://www.cantina.test/en/",
    }
    assert "/portal/login-page/" not in requested  # esclusione del cliente
    assert "/privato/" not in requested  # robots.txt
    assert "/docs/catalogo.pdf" not in requested  # i documenti non sono pagine
    assert {p.lang for p in result.pages} == {"it", "en"}


def test_crawl_stops_at_max_pages():
    result, _ = run_crawl(max_pages=2)
    assert len(result.pages) == 2


def test_save_result_reports_changes(tmp_path):
    client = make_client()
    result, _ = run_crawl()
    first = save_result(client, result, tmp_path)
    assert len(first["changes"]["new"]) == 4
    assert first["documents"] == [{"url": "https://www.cantina.test/docs/catalogo.pdf", "title": "Catalogo"}]

    changed = result.pages[0]
    changed.content_hash = "diverso"
    removed = result.pages.pop()
    second = save_result(client, result, tmp_path)
    assert second["changes"] == {"new": [], "changed": [changed.id], "removed": [removed.id]}

    saved = json.loads((tmp_path / "pages" / f"{changed.id}.json").read_text(encoding="utf-8"))
    assert saved["url"] == changed.url
