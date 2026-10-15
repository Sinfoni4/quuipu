import pytest
from fakes import wine_client

from quuipu.knowledge.store import Content, KnowledgeStore
from quuipu.visitor.profile import Signals, estimate_profile, matches, search_query


@pytest.fixture
def store(tmp_path):
    with KnowledgeStore(tmp_path / "k.db") as s:
        s.sync([
            Content(id="p-export", fonte="pagina", tipo="chi_siamo", hash="1", lingua="it",
                    url="https://www.cantina.test/export/", profili=["buyer_estero"]),
            Content(id="p-home", fonte="pagina", tipo="chi_siamo", hash="2", lingua="it",
                    url="https://www.cantina.test/",
                    profili=["buyer_estero", "distributore", "privato", "ente", "curioso"]),
            Content(id="p-spedizioni", fonte="pagina", tipo="faq", hash="4", lingua="it",
                    url="https://www.cantina.test/spedizioni-estero/", profili=["buyer_estero"]),
            Content(id="p-bozza", fonte="pagina", tipo="chi_siamo", hash="3", lingua="it",
                    url="https://www.cantina.test/bozza/", profili=["ente"], motivi=["dubbio"]),
        ])
        yield s


def estimate(store=None, **signals):
    return estimate_profile(wine_client(), Signals(**signals), store)


def test_keywords_match_word_starts_without_accents():
    keywords = ("import", "conformit", "gara d")
    assert matches("Siamo IMPORTATORI", keywords) == ["import"]
    assert matches("Conformità alle norme", keywords) == ["conformit"]
    assert matches("vino garantito", keywords) == []
    assert matches("una gara d'appalto", keywords) == ["gara d"]
    assert matches("reimport", keywords) == []


def test_search_query_from_referrer():
    assert search_query("https://www.bing.com/search?q=wine+importer+italy") == "wine importer italy"
    assert search_query("https://search.yahoo.com/search?p=prosecco") == "prosecco"
    assert search_query("https://www.google.com/") == ""


def test_no_signals_means_no_profile():
    result = estimate()
    assert result.profilo is None and result.confidenza == 0
    assert set(result.probabilita.values()) == {0.2}


def test_chat_declaration_is_the_strongest_signal(store):
    result = estimate(store, messaggi=["Buongiorno, siamo un distributore tedesco"],
                      pagina_ingresso="https://www.cantina.test/export/")
    assert result.profilo == "distributore"
    assert result.confidenza > 0.5
    assert result.segnali[0] == "dichiarazione in chat: distributore"


def test_search_query_and_foreign_language_point_to_foreign_buyer():
    result = estimate(referrer="https://www.bing.com/search?q=italian+wine+importers", lingua="en-US")
    assert result.profilo == "buyer_estero"
    assert result.confidenza == pytest.approx(5 / 9, abs=1e-3)
    assert result.segnali == ["query di ricerca: buyer_estero", "browser in lingua 'en': buyer_estero"]


def test_foreign_language_alone_is_not_enough():
    result = estimate(lingua="de")
    assert result.profilo == "buyer_estero" and result.confidenza < 0.5


def test_social_referrer():
    result = estimate(referrer="https://www.instagram.com/")
    assert result.profilo == "privato"
    assert result.segnali == ["provenienza da www.instagram.com: privato"]


def test_internal_referrer_is_ignored():
    assert estimate(referrer="https://www.cantina.test/?q=import").segnali == []


def test_pages_count_through_their_profiles(store):
    entry = estimate(store, pagina_ingresso="https://www.cantina.test/export")
    assert entry.profilo == "buyer_estero"
    assert entry.confidenza == pytest.approx(3 / 7, abs=1e-3)

    # La home è utile a tutti: non distingue nessuno.
    home = estimate(store, pagina_ingresso="https://www.cantina.test/")
    assert len(set(home.probabilita.values())) == 1
    assert home.profilo is None

    # Parità tra due profili: nessuno dei due viene scelto.
    assert estimate(referrer="https://www.linkedin.com/").profilo is None

    # Le pagine non approvate non contano.
    assert estimate(store, pagine_viste=["https://www.cantina.test/bozza/"]).segnali == []

    # La navigazione rafforza il profilo; la pagina d'ingresso non conta due volte.
    browsing = estimate(store, pagina_ingresso="https://www.cantina.test/export/",
                        pagine_viste=["https://www.cantina.test/export/",
                                      "https://www.cantina.test/spedizioni-estero/"], lingua="en")
    assert browsing.confidenza == pytest.approx(5 / 9, abs=1e-3)
    assert [s for s in browsing.segnali if s.startswith("pagina")] == [
        "pagina d'ingresso: buyer_estero", "pagina vista: buyer_estero",
    ]
