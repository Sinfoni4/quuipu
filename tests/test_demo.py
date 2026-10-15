"""La demo simulata esegue tutta la catena vera: è anche un test end-to-end."""

import pytest
from fastapi.testclient import TestClient

from quuipu.demo.files import png_color, solid_png
from quuipu.demo.run import create_demo_app, prepare

UA = {"user-agent": "Mozilla/5.0 Chrome/130"}


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    base = tmp_path_factory.mktemp("demo")
    summary = prepare(base, site_port=0, log=lambda _: None)
    return summary, TestClient(create_demo_app(base, summary))


def visit(demo, path, **body):
    summary, client = demo
    return client.post("/v1/valmora/plan", headers=UA, json={"pagina": summary["sito"] + path, **body}).json()


def test_png_color_roundtrip():
    assert png_color(solid_png((74, 124, 58), 8, 4)) == (74, 124, 58)
    assert png_color(b"non un png") is None


def test_ingestion_of_the_invented_winery(demo):
    summary, client = demo
    assert summary["pagine"] == 20
    assert summary["file_scaricati"] == {"documenti": 1, "immagini": 5}
    assert summary["prodotti"] == 4
    assert summary["stati"] == {"approvato": 26, "da_rivedere": 3}
    review = {r["titolo"]: r["motivi"] for r in client.get("/demo-api/info").json()["in_revisione"]}
    amarone = review["Valmora Amarone della Valpolicella DOCG"]
    assert "specifica 'Affinamento: 36 mesi in botte' non trovata nel documento" in amarone


def test_anonymous_visitor_gets_standard_page(demo):
    data = visit(demo, "/", lingua="it-IT")
    assert data["standard"] and data["motivi"] == ["profilo del visitatore non determinato"]


def test_private_visitor_from_instagram(demo):
    data = visit(demo, "/degustazioni/", referrer="https://www.instagram.com/", lingua="it-IT")
    assert not data["standard"] and data["profilo"]["id"] == "privato"
    blocks = data["piano"]["blocchi"]
    assert [b["componente"] for b in blocks] == ["hero", "griglia_prodotti", "faq", "cta_contatto"]
    assert blocks[-1]["variante"] == "degustazione"
    hero = blocks[0]["contenuti"][0]
    assert hero["titolo"].startswith("La nostra storia")
    assert not hero["estratto"].startswith("La nostra storia")  # il titolo non si ripete
    products = [p["titolo"] for p in blocks[1]["contenuti"]]
    assert "Valmora Amarone della Valpolicella DOCG" not in products  # in revisione


def test_german_importer_gets_english_page_without_invented_promises(demo):
    data = visit(demo, "/en/", lingua="de-DE",
                 domanda="We are a wine importer from Germany. Do you have organic certifications?")
    assert data["profilo"]["id"] == "buyer_estero"
    assert data["piano"]["lingua"] == "en"
    assert any("guarantee" in w for w in data["debug"]["avvisi"])
    grid = next(b for b in data["piano"]["blocchi"] if b["componente"] == "griglia_prodotti")
    assert "raccordo" not in grid


def test_restaurant_owner_invented_reference_is_discarded(demo):
    data = visit(demo, "/vini/", lingua="it-IT",
                 domanda="Ho un ristorante a Milano: avete un listino per la ristorazione?")
    assert data["profilo"]["id"] == "distributore"
    assert data["debug"]["scartati"][0]["motivi"] == ["contenuto 'case-ristorante-milano' inesistente"]
    assert data["piano"]["blocchi"][-1]["variante"] == "campione"


def test_weak_signals_and_emergency_switch(demo):
    weak = visit(demo, "/certificazioni/", lingua="it-IT",
                 referrer="https://www.bing.com/search?q=fornitura+vino+biologico+gara+d%27appalto+mensa")
    assert weak["standard"] and "poco sicuro" in weak["motivi"][0]

    _, client = demo
    client.post("/demo-api/agent", json={"attivo": False})
    off = visit(demo, "/", domanda="siamo importatori")
    client.post("/demo-api/agent", json={"attivo": True})
    assert off["standard"] and off["motivi"] == ["agente disattivato"]


def test_demo_page_is_served(demo):
    _, client = demo
    page = client.get("/demo/")
    assert page.status_code == 200 and "Quuipu · Demo simulata" in page.text
