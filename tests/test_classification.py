import json

from fakes import FakeLLM, LLMError, wine_client

from quuipu.config import DEFAULT_PROFILES, load_client
from quuipu.ingestion import classification
from quuipu.ingestion.classification import (
    ContentItem,
    build_classification,
    build_prompt,
    classify_contents,
    load_items,
)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def sample_data(base):
    write_json(base / "crawl" / "pages" / "page-aaa.json", {
        "id": "page-aaa", "url": "https://www.cantina.test/la-filosofia/",
        "title": "La filosofia", "headings": ["Rispetto per la terra"],
        "description": "", "text": "Coltiviamo le nostre vigne dal 1962.",
    })
    write_json(base / "crawl" / "pages" / "page-bbb.json", {
        "id": "page-bbb", "url": "https://www.cantina.test/privacy-policy/",
        "title": "Privacy", "headings": [], "description": "", "text": "Informativa privacy.",
    })
    write_json(base / "knowledge" / "products.json", {"prodotti": [{
        "id": "prod-ccc", "nome": "Prosecco DOC Treviso Brut", "categoria": "spumante",
        "descrizione": "", "specifiche": {"Vitigno": "Glera"},
    }]})
    write_json(base / "knowledge" / "images.json", {"immagini": [{
        "id": "img-ddd", "descrizione": "Filari di vite in collina.",
        "tag": ["vigneto", "collina"], "categoria": "vigneto",
    }]})


def test_load_items_collects_pages_products_and_images(tmp_path):
    sample_data(tmp_path)
    items = load_items(wine_client(), tmp_path)
    assert [(i.id, i.source) for i in items] == [
        ("page-aaa", "pagina"), ("page-bbb", "pagina"),
        ("prod-ccc", "prodotto"), ("img-ddd", "immagine"),
    ]
    assert "Coltiviamo le nostre vigne" in items[0].summary
    assert "Vitigno: Glera" in items[2].summary


def test_load_items_without_data_returns_nothing(tmp_path):
    assert load_items(wine_client(), tmp_path) == []


def test_prompt_lists_types_profiles_and_fixed_types():
    items = [ContentItem("page-aaa", "pagina", "Titolo: X"), ContentItem("prod-ccc", "prodotto", "Nome: Y")]
    prompt = build_prompt(wine_client(), items)
    assert '"chi_siamo"' in prompt and '"buyer_estero"' in prompt
    assert "### id: page-aaa (fonte: pagina)" in prompt
    assert "### id: prod-ccc (fonte: prodotto, tipo già noto: prodotto)" in prompt


def test_valid_classification_needs_no_review():
    item = ContentItem("page-aaa", "pagina", "")
    result = build_classification(
        wine_client(), item, {"tipo": "chi_siamo", "profili": ["privato", "curioso"], "confidenza": 0.9}
    )
    assert result == {
        "id": "page-aaa", "fonte": "pagina", "tipo": "chi_siamo",
        "profili": ["privato", "curioso"], "confidenza": 0.9,
        "revisione": {"necessaria": False, "motivi": []},
    }


def test_invalid_type_and_profiles_go_to_review():
    item = ContentItem("page-aaa", "pagina", "")
    result = build_classification(
        wine_client(), item, {"tipo": "blog", "profili": ["sommelier", "privato", "privato"], "confidenza": 0.8}
    )
    assert result["tipo"] == "altro"
    assert result["profili"] == ["privato"]
    assert result["revisione"]["motivi"] == ["tipo 'blog' non previsto", "profilo 'sommelier' non previsto"]


def test_fixed_type_is_kept_even_if_model_disagrees():
    item = ContentItem("prod-ccc", "prodotto", "")
    result = build_classification(
        wine_client(), item, {"tipo": "notizia", "profili": ["distributore"], "confidenza": 0.9}
    )
    assert result["tipo"] == "prodotto"
    assert not result["revisione"]["necessaria"]


def test_missing_profiles_are_flagged_except_for_service_pages():
    item = ContentItem("page-aaa", "pagina", "")
    client = wine_client()
    no_profiles = build_classification(client, item, {"tipo": "contatto", "profili": [], "confidenza": 0.9})
    assert no_profiles["revisione"]["motivi"] == ["nessun profilo di visitatore assegnato"]
    service = build_classification(client, item, {"tipo": "altro", "profili": [], "confidenza": 0.9})
    assert not service["revisione"]["necessaria"]


def test_classify_contents_end_to_end(tmp_path):
    sample_data(tmp_path)
    llm = FakeLLM({"classificazioni": [
        {"id": "page-aaa", "tipo": "chi_siamo", "profili": ["privato", "curioso"], "confidenza": 0.9},
        {"id": "page-bbb", "tipo": "altro", "profili": [], "confidenza": 0.95},
        {"id": "prod-ccc", "profili": ["privato", "distributore", "buyer_estero"], "confidenza": 0.85},
        # img-ddd manca: il modello l'ha dimenticata
        {"id": "inventato", "tipo": "faq", "profili": ["privato"], "confidenza": 1},
    ]})
    result = classify_contents(wine_client(), llm, tmp_path)

    by_id = {r["id"]: r for r in result["contenuti"]}
    assert list(by_id) == ["page-aaa", "page-bbb", "prod-ccc", "img-ddd"]
    assert by_id["prod-ccc"]["tipo"] == "prodotto"
    assert by_id["img-ddd"]["tipo"] == "immagine"
    assert by_id["img-ddd"]["revisione"]["motivi"][-1] == "nessuna classificazione restituita dal modello"
    assert result["da_rivedere"] == 1
    assert result["per_profilo"] == {
        "buyer_estero": 1, "distributore": 1, "privato": 2, "ente": 0, "curioso": 1,
    }
    saved = json.loads((tmp_path / "knowledge" / "classification.json").read_text(encoding="utf-8"))
    assert saved == result


def test_contents_are_sent_in_batches_and_errors_do_not_stop_the_run(tmp_path, monkeypatch):
    sample_data(tmp_path)
    monkeypatch.setattr(classification, "BATCH_SIZE", 2)
    llm = FakeLLM(
        LLMError("timeout"),
        {"classificazioni": [
            {"id": "prod-ccc", "profili": ["privato"], "confidenza": 0.9},
            {"id": "img-ddd", "profili": ["privato"], "confidenza": 0.9},
        ]},
    )
    result = classify_contents(wine_client(), llm, tmp_path)
    assert len(llm.calls) == 2
    assert result["errori"] == [{"id": ["page-aaa", "page-bbb"], "errore": "timeout"}]
    assert [r["id"] for r in result["contenuti"]] == ["prod-ccc", "img-ddd"]


def test_profiles_from_client_file(tmp_path):
    (tmp_path / "prova.toml").write_text(
        """id = "prova"
name = "Prova"
sector = "agrifood"
base_url = "https://www.prova.test/"
languages = ["it"]

[[profiles]]
id = "importatore"
name = "Importatore estero"
looks_for = "Volumi e disponibilità"
highlight = "Schede tecniche, premi, contatti export"
""",
        encoding="utf-8",
    )
    client = load_client("prova", tmp_path)
    assert [p.id for p in client.profiles] == ["importatore"]
    assert load_client("casapaladin").profiles == DEFAULT_PROFILES
