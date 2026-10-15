import copy

import pytest
from fakes import FakeEmbedder, FakeLLM, LLMError, wine_client

from quuipu.composer.components import COMPONENTS, describe_library
from quuipu.composer.history import PlanHistory
from quuipu.composer.planner import Planner, PlanRequest, page_language
from quuipu.composer.validator import check_bridge, validate_plan
from quuipu.knowledge.search import index_contents
from quuipu.knowledge.store import Content, KnowledgeStore

ALL = ["buyer_estero", "distributore", "privato", "ente", "curioso"]


def content(id_, fonte, tipo, lingua="it", testo="", profili=ALL, motivi=(), dati=None, url=""):
    return Content(
        id=id_, fonte=fonte, tipo=tipo, hash=id_, lingua=lingua, titolo=id_.upper(), testo=testo,
        url=url, profili=list(profili), motivi=list(motivi), dati=dati or {},
    )


CONTENTS = [
    content("page-home", "pagina", "chi_siamo", testo="Famiglia di vignaioli dal 1962.",
            url="https://www.cantina.test/"),
    content("page-home-en", "pagina", "chi_siamo", lingua="en", testo="Winemakers since 1962.",
            url="https://www.cantina.test/en/"),
    content("prod-a", "prodotto", "prodotto", testo="Prosecco brut",
            dati={"specifiche": {"Gradazione": "11,5% vol"}}),
    content("prod-b", "prodotto", "prodotto", testo="Chianti Classico"),
    content("prod-bozza", "prodotto", "prodotto", motivi=["prezzo da confermare"]),
    content("cert-it", "pagina", "certificazione", testo="Certificazione biologica",
            profili=["buyer_estero", "ente"]),
    content("cert-en", "pagina", "certificazione", lingua="en", testo="Organic certification",
            profili=["buyer_estero", "ente"]),
    content("faq-it", "pagina", "faq", testo="Spedite all'estero?"),
    content("img-a", "immagine", "immagine", lingua="it", testo="Bottiglia di spumante"),
    content("page-privacy", "pagina", "altro", testo="Informativa privacy", profili=[]),
]


@pytest.fixture
def store(tmp_path):
    with KnowledgeStore(tmp_path / "knowledge.db") as s:
        s.sync(copy.deepcopy(CONTENTS))
        yield s


def plan(*blocks, profilo="privato", lingua="it", confidenza=0.8):
    return {"profilo": profilo, "lingua": lingua, "confidenza": confidenza, "blocchi": list(blocks)}


HERO = {"componente": "hero", "contenuto_id": "page-home", "immagine_id": "img-a",
        "raccordo": "Una famiglia di vignaioli dal 1962."}
GRID = {"componente": "griglia_prodotti", "contenuto_id": ["prod-a", "prod-b"]}
CTA = {"componente": "cta_contatto", "variante": "degustazione", "raccordo": "Vieni a trovarci."}


# --- libreria -------------------------------------------------------------

def test_library_has_the_six_poc_components():
    assert set(COMPONENTS) == {
        "hero", "griglia_prodotti", "certificazioni", "case_study", "faq", "cta_contatto",
    }
    assert '"griglia_prodotti"' in describe_library()


# --- validatore -----------------------------------------------------------

def test_valid_plan_is_accepted_and_cleaned(store):
    raw = plan(dict(HERO, extra="ignorato"), GRID, CTA)
    raw["campo_sconosciuto"] = True
    result = validate_plan(raw, wine_client(), store)
    assert result.valid and result.errors == [] and result.discarded == []
    assert result.plan == plan(HERO, GRID, CTA)


@pytest.mark.parametrize("bad_block, reason", [
    ({"componente": "carosello", "contenuto_id": "page-home"}, "non presente nella libreria"),
    ({"componente": "griglia_prodotti", "contenuto_id": ["prod-a", "prod-x"]}, "'prod-x' inesistente"),
    ({"componente": "griglia_prodotti", "contenuto_id": ["prod-bozza"]}, "non approvato"),
    ({"componente": "griglia_prodotti", "contenuto_id": ["cert-it"]}, "non ammesso"),
    ({"componente": "griglia_prodotti", "contenuto_id": "prod-a"}, "deve essere una lista"),
    ({"componente": "griglia_prodotti", "contenuto_id": ["prod-a", "prod-a"]}, "ripetuti"),
    ({"componente": "griglia_prodotti", "contenuto_id": []}, "servono da 1 a 9"),
    ({"componente": "certificazioni", "contenuto_id": ["cert-en"]}, "in lingua 'en'"),
    ({"componente": "hero", "contenuto_id": "page-privacy"}, "non ammesso"),
    ({"componente": "hero", "contenuto_id": "img-a"}, "non ammesso"),
    ({"componente": "hero", "contenuto_id": "page-home", "immagine_id": "prod-a"}, "non disponibile"),
    ({"componente": "faq", "contenuto_id": ["faq-it"], "variante": "x"}, None),
    ({"componente": "cta_contatto", "variante": "sconto"}, "variante 'sconto'"),
    ({"componente": "cta_contatto", "variante": "contatto", "contenuto_id": "prod-a"}, "non accetta"),
    ("testo", "non è un oggetto"),
])
def test_invalid_blocks_are_discarded_but_the_page_survives(store, bad_block, reason):
    result = validate_plan(plan(HERO, bad_block, CTA), wine_client(), store)
    assert result.valid
    if reason is None:  # campi in più vengono semplicemente ignorati
        assert result.discarded == []
        return
    assert [b["componente"] for b in result.plan["blocchi"]] == ["hero", "cta_contatto"]
    assert any(reason in m for m in result.discarded[0]["motivi"]), result.discarded


def test_same_content_cannot_appear_twice(store):
    other = {"componente": "griglia_prodotti", "contenuto_id": ["prod-b"]}
    result = validate_plan(plan(GRID, other, CTA), wine_client(), store)
    assert result.discarded[0]["motivi"] == ["contenuti già usati: prod-b"]


@pytest.mark.parametrize("raw, error", [
    ("non è un piano", "non è un oggetto JSON"),
    (plan(HERO, CTA, profilo="sommelier"), "profilo 'sommelier' non previsto"),
    (plan(HERO, CTA, lingua="fr"), "lingua 'fr' non prevista"),
    (plan(HERO, CTA, confidenza=0.3), "sotto la soglia"),
    (plan(HERO, CTA, confidenza="alta"), "confidenza mancante"),
    (plan(), "nessun blocco"),
    (plan(HERO, GRID), "manca l'invito all'azione"),
    (plan(CTA), "nessun blocco di contenuto valido"),
    (plan({"componente": "hero", "contenuto_id": "inventato"}, CTA), "nessun blocco di contenuto valido"),
])
def test_invalid_plans_fall_back_to_standard_page(store, raw, error):
    result = validate_plan(raw, wine_client(), store)
    assert not result.valid and result.plan is None
    assert any(error in e for e in result.errors), result.errors


def test_too_many_blocks_are_cut(store):
    faqs = [{"componente": "faq", "contenuto_id": ["faq-it"]}] + [
        {"componente": "hero", "contenuto_id": "page-home"}
    ]
    blocks = [GRID, CTA] + [{"componente": "cta_contatto", "variante": "contatto"}] * 7 + faqs
    result = validate_plan(plan(*blocks), wine_client(), store)
    assert len(result.plan["blocchi"]) == 8
    assert "oltre il massimo" in result.discarded[-1]["motivi"][0]


def test_bridge_rules():
    sources = [{"titolo": "Prosecco", "testo": "Dal 1962", "dati": {"Gradazione": "11,5% vol"}}]
    assert check_bridge("Un brut da 11,5 gradi, come nel 1962.", sources) == []
    assert check_bridge("Il migliore Prosecco.", sources) == ["raccordo con espressione non ammessa: 'il migliore'"]
    assert check_bridge("Garantiamo consegne rapide.", sources) == ["raccordo con espressione non ammessa: 'garanti'"]
    assert check_bridge("Spedizione in 48 ore.", sources) == ["raccordo con numeri non presenti nei contenuti: 48"]
    assert "troppo lungo" in check_bridge("x" * 300, sources)[0]


def test_bad_bridge_is_removed_and_block_kept(store):
    grid = dict(GRID, raccordo="Sconto del 20% solo oggi!")
    result = validate_plan(plan(grid, CTA), wine_client(), store)
    assert result.valid
    assert "raccordo" not in result.plan["blocchi"][0]
    assert len(result.warnings) == 2


# --- agente ---------------------------------------------------------------

def make_planner(store, *responses, **kwargs):
    llm = FakeLLM(*responses)
    return Planner(wine_client(), store, llm, **kwargs), llm


def test_page_language():
    client = wine_client()
    assert page_language(client, "en-GB") == "en"
    assert page_language(client, "de") == "en"
    assert page_language(client, "IT") == "it"


def test_inactive_agent_and_weak_profile_give_standard_page_without_calling_the_model(store):
    planner, llm = make_planner(store, active=False)
    assert planner.plan(PlanRequest("privato", 0.9, "it")).motivi == ["agente disattivato"]

    planner, llm = make_planner(store)
    assert planner.plan(PlanRequest(None, 0.0, "it")).standard
    assert planner.plan(PlanRequest("sommelier", 0.9, "it")).standard
    weak = planner.plan(PlanRequest("privato", 0.3, "it"))
    assert weak.standard and "poco sicuro" in weak.motivi[0]
    assert llm.calls == []
    assert len(PlanHistory(store).recent()) == 4  # anche le pagine standard vengono registrate


def test_plan_is_composed_validated_logged_and_cached(store):
    proposal = plan(HERO, GRID, CTA, profilo="distributore", lingua="de")
    planner, llm = make_planner(store, proposal, copy.deepcopy(proposal))

    first = planner.plan(PlanRequest("privato", 0.8, "it", "https://www.cantina.test/"))
    assert not first.standard and not first.da_cache
    assert first.piano["profilo"] == "privato" and first.piano["lingua"] == "it"
    prompt = llm.calls[0]["user"]
    assert "page-home |" in prompt and "prod-a |" in prompt and "img-a | immagine" in prompt
    assert "prod-bozza" not in prompt and "page-home-en" not in prompt
    assert "page-privacy" not in prompt

    second = planner.plan(PlanRequest("privato", 0.8, "it", "https://www.cantina.test/"))
    assert second.da_cache and second.piano == first.piano
    assert len(llm.calls) == 1

    # Cambia la base di conoscenza approvata: la cache non vale più, e il
    # prodotto escluso fa scartare la griglia proposta dal modello.
    store.decide("prod-b", "escluso")
    third = planner.plan(PlanRequest("privato", 0.8, "it", "https://www.cantina.test/"))
    assert len(llm.calls) == 2
    assert [b["componente"] for b in third.piano["blocchi"]] == ["hero", "cta_contatto"]

    log = PlanHistory(store).recent()
    assert [r["esito"] for r in log] == ["adattiva"] * 3
    assert log[0]["scartati"][0]["motivi"] == ["contenuto 'prod-b' non approvato (escluso)"]
    assert [r["da_cache"] for r in log] == [False, True, False]


def test_question_uses_semantic_search_and_is_not_cached(store):
    index_contents(store, FakeEmbedder())
    proposal = plan({"componente": "faq", "contenuto_id": ["faq-it"]}, CTA)
    planner, llm = make_planner(store, proposal, copy.deepcopy(proposal), embedder=FakeEmbedder())
    request = PlanRequest("buyer_estero", 0.9, "it", domanda="spedite all'estero?")
    assert not planner.plan(request).standard
    assert not planner.plan(request).da_cache
    assert "Domanda del visitatore: spedite all'estero?" in llm.calls[0]["user"]
    assert llm.calls[0]["user"].index("faq-it |") < llm.calls[0]["user"].index("prod-a |")


def test_model_failures_give_standard_page(store):
    planner, _ = make_planner(store, LLMError("timeout"), plan({"componente": "hero", "contenuto_id": "x"}))
    down = planner.plan(PlanRequest("privato", 0.9, "it"))
    assert down.standard and down.motivi == ["agente non disponibile: timeout"]
    invalid = planner.plan(PlanRequest("privato", 0.9, "it"))
    assert invalid.standard and invalid.scartati[0]["motivi"] == ["contenuto 'x' inesistente"]


def test_no_approved_contents_gives_standard_page(tmp_path):
    with KnowledgeStore(tmp_path / "vuoto.db") as empty:
        planner, llm = make_planner(empty)
        response = planner.plan(PlanRequest("privato", 0.9, "it"))
    assert response.standard and llm.calls == []
