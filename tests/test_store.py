import pytest
from fakes import FakeEmbedder

from quuipu.knowledge.search import chunk_text, content_chunks, index_contents, search
from quuipu.knowledge.store import Content, KnowledgeStore


def page(content_id, text, hash_="h1", motivi=(), profili=("privato",), tipo="chi_siamo"):
    return Content(
        id=content_id, fonte="pagina", tipo=tipo, hash=hash_, lingua="it",
        titolo=content_id, testo=text, profili=list(profili), motivi=list(motivi),
    )


@pytest.fixture
def store(tmp_path):
    with KnowledgeStore(tmp_path / "knowledge.db") as s:
        yield s


def test_state_follows_review_reasons(store):
    store.sync([page("a", "testo"), page("b", "testo", motivi=["prezzo da confermare"])])
    assert store.get("a")["stato"] == "approvato"
    assert store.get("b")["stato"] == "da_rivedere"
    assert store.get("b")["motivi"] == ["prezzo da confermare"]
    assert store.counts() == {"approvato": 1, "da_rivedere": 1}


def test_sync_reports_new_changed_unchanged_removed(store):
    store.sync([page("a", "x"), page("b", "x"), page("c", "x")])
    report = store.sync([page("a", "x"), page("b", "y", hash_="h2"), page("d", "x")])
    assert report == {"nuovi": ["d"], "modificati": ["b"], "invariati": ["a"], "rimossi": ["c"]}
    assert store.get("c") is None


def test_client_decisions_survive_until_content_changes(store):
    store.sync([page("a", "x", motivi=["dubbio"]), page("b", "x")])
    store.decide("a", "approvato")
    store.decide("b", "escluso")

    store.sync([page("a", "x", motivi=["dubbio"]), page("b", "x")])
    assert store.get("a")["stato"] == "approvato"
    assert store.get("b")["stato"] == "escluso"

    # Cambia il contenuto: l'approvazione va ridata, l'esclusione resta.
    store.sync([page("a", "y", hash_="h2", motivi=["dubbio"]), page("b", "y", hash_="h2")])
    assert store.get("a")["stato"] == "da_rivedere"
    assert store.get("b")["stato"] == "escluso"

    store.decide("b", None)
    assert store.get("b")["stato"] == "approvato"


def test_decide_rejects_unknown_ids_and_decisions(store):
    store.sync([page("a", "x")])
    assert store.decide("inesistente", "approvato") is False
    with pytest.raises(ValueError):
        store.decide("a", "forse")


def test_list_filters(store):
    store.sync([
        page("a", "x", profili=["privato"]),
        page("b", "x", profili=["distributore"], tipo="prodotto", motivi=["dubbio"]),
    ])
    assert [c["id"] for c in store.list(profilo="distributore")] == ["b"]
    assert [c["id"] for c in store.list(stato="approvato")] == ["a"]
    assert [c["id"] for c in store.list(tipo="prodotto")] == ["b"]


def test_chunk_text_splits_long_text_and_keeps_lines():
    assert chunk_text("uno\n\ndue", max_chars=20) == ["uno\ndue"]
    long_line = " ".join(["parola"] * 50)
    chunks = chunk_text(long_line, max_chars=60)
    assert all(len(c) <= 60 for c in chunks)
    assert " ".join(chunks) == long_line


def test_content_chunks_prefix_title():
    content = {"titolo": "Chi siamo", "testo": "Famiglia di vignaioli."}
    assert content_chunks(content) == ["Chi siamo\nFamiglia di vignaioli."]
    assert content_chunks({"titolo": "Solo titolo", "testo": ""}) == ["Solo titolo"]


def test_index_only_new_or_changed_contents(store):
    embedder = FakeEmbedder()
    store.sync([page("a", "vigne in collina"), page("b", "cantina sotterranea")])
    assert index_contents(store, embedder) == 2
    assert index_contents(store, embedder) == 0
    store.sync([page("a", "vigne in collina"), page("b", "cantina nuova", hash_="h2")])
    assert index_contents(store, embedder) == 1
    assert len(embedder.calls) == 2  # la seconda indicizzazione non ha chiamato il modello


def test_search_returns_only_approved_contents_matching_filters(store):
    embedder = FakeEmbedder()
    store.sync([
        page("vigne", "le nostre vigne in collina", profili=["privato"]),
        page("export", "spedizioni export in tutto il mondo", profili=["buyer_estero"]),
        page("bozza", "vigne in collina ancora da rivedere", motivi=["dubbio"]),
    ])
    index_contents(store, embedder)

    results = search(store, embedder, "vigne collina", k=5)
    assert [r["contenuto"]["id"] for r in results][0] == "vigne"
    assert "bozza" not in [r["contenuto"]["id"] for r in results]

    filtered = search(store, embedder, "vigne collina", profilo="buyer_estero")
    assert [r["contenuto"]["id"] for r in filtered] == ["export"]

    store.decide("vigne", "escluso")
    assert "vigne" not in [r["contenuto"]["id"] for r in search(store, embedder, "vigne")]
    assert search(store, embedder, "   ") == []
