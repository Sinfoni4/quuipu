import re

import httpx
import pytest
from fakes import FakeEmbedder, make_pdf, wine_client

from quuipu.ingestion.assets import asset_filename, is_client_asset
from quuipu.ingestion.llm import LLMError
from quuipu.knowledge.search import search
from quuipu.knowledge.store import KnowledgeStore
from quuipu.pipeline import run_ingestion

PDF = make_pdf([["Prosecco DOC Treviso Brut", "Vitigno: Glera", "Gradazione: 11,5% vol"]])
PNG = b"\x89PNG finta bottiglia"


def html(lang, title, body):
    return (
        f'<html lang="{lang}"><head><title>{title}</title></head><body>'
        f'<nav><a href="/">Home</a> <a href="/la-filosofia/">Filosofia</a></nav>'
        f"<main>{body}</main></body></html>"
    )


SITE = {
    "/": html("it", "Cantina", '<h1>Benvenuti</h1><p>Vini dal 1962.</p>'
              '<img src="/wp-content/uploads/bottiglia.png" alt="Bottiglia">'
              '<img src="https://altrosito.test/logo.png" alt="Logo esterno">'
              '<a href="/wp-content/uploads/catalogo.pdf">Catalogo</a>'),
    "/la-filosofia/": html("it", "La filosofia", "<p>Coltiviamo le vigne in collina con rispetto.</p>"),
}


class Site:
    def __init__(self):
        self.requested = []

    def __call__(self, request):
        path = request.url.path
        self.requested.append(str(request.url))
        if request.url.host != "www.cantina.test":
            return httpx.Response(200, content=b"esterno")
        if path == "/robots.txt":
            return httpx.Response(404)
        if path in SITE:
            return httpx.Response(200, text=SITE[path], headers={"content-type": "text/html"})
        if path == "/wp-content/uploads/catalogo.pdf":
            return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
        if path == "/wp-content/uploads/bottiglia.png":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        return httpx.Response(404)


class RoutingLLM:
    """Risponde in base al tipo di richiesta, come farebbe il modello vero."""

    def __init__(self):
        self.calls = []

    def complete_json(self, system, user, images=()):
        self.calls.append(user)
        if images:
            return {"descrizione": "Bottiglia di spumante.", "tag": ["bottiglia"],
                    "categoria": "bottiglia", "confidenza": 0.9}
        if "CONTENUTI:" in user:
            ids = re.findall(r"### id: (\S+)", user)
            return {"classificazioni": [
                {"id": i, "tipo": "chi_siamo", "profili": ["privato"], "confidenza": 0.9} for i in ids
            ]}
        return {"prodotti": [{"nome": "Prosecco DOC Treviso Brut", "categoria": "spumante",
                              "specifiche": {"Vitigno": "Glera"}, "confidenza": 0.9}]}


def run(tmp_path, site, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(site), follow_redirects=True)
    defaults = dict(
        base_dir=tmp_path, http=http, sleep=lambda _: None, text_llm=RoutingLLM(),
        vision_llm=RoutingLLM(), embedder=FakeEmbedder(), log=lambda _: None,
    )
    defaults.update(kwargs)
    return run_ingestion(wine_client(), **defaults)


def test_asset_helpers():
    client = wine_client()
    assert is_client_asset("https://www.cantina.test/a.pdf", client)
    assert is_client_asset("https://cdn.cantina.test/a.pdf", client)
    assert not is_client_asset("https://altrosito.test/a.pdf", client)
    taken = {"catalogo.pdf": "https://www.cantina.test/2025/catalogo.pdf"}
    name = asset_filename("https://www.cantina.test/2026/catalogo.pdf", taken)
    assert name.startswith("catalogo-") and name.endswith(".pdf")
    assert asset_filename("https://www.cantina.test/x/Scheda%20Vino.pdf", {}) == "Scheda_Vino.pdf"


def test_full_ingestion_builds_searchable_knowledge_base(tmp_path):
    site = Site()
    summary = run(tmp_path, site)

    assert summary["pagine"] == 2
    assert summary["file_scaricati"] == {"documenti": 1, "immagini": 1}
    assert summary["prodotti"] == 1 and summary["immagini"] == 1
    assert summary["base_di_conoscenza"]["nuovi"] == 4
    assert summary["stati"] == {"approvato": 3, "da_rivedere": 1}
    assert summary["avvisi"] == []
    assert not any("altrosito" in url for url in site.requested)  # niente file di altri siti

    with KnowledgeStore.for_client(wine_client(), tmp_path) as store:
        product = store.list(tipo="prodotto")[0]
        assert product["stato"] == "da_rivedere"
        assert "specifiche tecniche da confermare" in product["motivi"]
        assert product["url"] == "https://www.cantina.test/wp-content/uploads/catalogo.pdf"
        image = store.list(tipo="immagine")[0]
        assert image["url"] == "https://www.cantina.test/wp-content/uploads/bottiglia.png"

        results = search(store, FakeEmbedder(), "vigne in collina")
        assert results[0]["contenuto"]["titolo"] == "La filosofia"
        assert all(r["contenuto"]["tipo"] != "prodotto" for r in results)  # in revisione

        store.decide(product["id"], "approvato")

    # Secondo passaggio senza crawl: niente nuovi download, l'approvazione resta.
    site.requested.clear()
    embedder = FakeEmbedder()
    summary = run(tmp_path, site, skip_crawl=True, embedder=embedder)
    assert site.requested == []
    assert summary["base_di_conoscenza"]["invariati"] == 4
    assert summary["indicizzati"] == 0 and embedder.calls == []
    assert summary["stati"] == {"approvato": 4}


def test_dedicated_folder_is_included(tmp_path):
    folder = tmp_path / "cartella"
    folder.mkdir()
    (folder / "listino.pdf").write_bytes(make_pdf([["Listino 2026"]]))
    summary = run(tmp_path / "dati", Site(), folder=folder)
    assert summary["prodotti"] == 2  # il prodotto finto compare in entrambi i PDF


def test_missing_vision_model_and_embedder_only_skip_their_steps(tmp_path, monkeypatch):
    monkeypatch.delenv("QUUIPU_VISION_MODEL", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setattr("quuipu.pipeline.default_embedder", _raise)
    summary = run(tmp_path, Site(), vision_llm=None, embedder=None)
    assert len(summary["avvisi"]) == 2
    assert "immagini" not in summary and "indicizzati" not in summary
    assert summary["base_di_conoscenza"]["nuovi"] == 3


def test_skip_crawl_without_previous_crawl_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        run(tmp_path, Site(), skip_crawl=True)


def _raise():
    raise LLMError("manca MISTRAL_API_KEY")
