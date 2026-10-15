import copy

import pytest
from fakes import FakeEmbedder, FakeLLM
from fastapi.testclient import TestClient

from quuipu.api.app import create_app, is_bot
from quuipu.api.sessions import SessionStore
from quuipu.control import set_agent_active
from quuipu.ingestion.llm import LLMError
from quuipu.knowledge.store import Content, KnowledgeStore

CLIENT_TOML = """id = "cantina"
name = "Cantina di prova"
sector = "agrifood"
base_url = "https://www.cantina.test/"
languages = ["it", "en"]
allowed_origins = ["https://www.cantina.test", "https://cantina.quuipu.me"]
"""

ALL = ["buyer_estero", "distributore", "privato", "ente", "curioso"]
CONTENTS = [
    Content(id="page-home", fonte="pagina", tipo="chi_siamo", hash="1", lingua="it",
            titolo="Cantina", testo="Famiglia di vignaioli dal 1962.", url="https://www.cantina.test/",
            profili=ALL, dati={"descrizione": "La cantina", "immagini": [{"url": "https://www.cantina.test/a.jpg", "alt": "Vigna"}]}),
    Content(id="cert-it", fonte="pagina", tipo="certificazione", hash="2", lingua="it",
            titolo="Certificazioni", testo="Certificazione biologica.", url="https://www.cantina.test/cert/",
            profili=["buyer_estero", "ente"]),
    Content(id="prod-a", fonte="prodotto", tipo="prodotto", hash="3", titolo="Prosecco",
            profili=ALL, dati={"categoria": "spumante", "specifiche": {"Vitigno": "Glera"},
                               "documenti_url": ["https://www.cantina.test/catalogo.pdf"]}),
    Content(id="prod-bozza", fonte="prodotto", tipo="prodotto", hash="4", titolo="Bozza",
            profili=ALL, motivi=["prezzo da confermare"]),
]
PLAN = {"profilo": "buyer_estero", "lingua": "it", "confidenza": 0.8, "blocchi": [
    {"componente": "hero", "contenuto_id": "page-home", "raccordo": "Vignaioli dal 1962."},
    {"componente": "certificazioni", "contenuto_id": ["cert-it"]},
    {"componente": "griglia_prodotti", "contenuto_id": ["prod-a"]},
    {"componente": "cta_contatto", "variante": "preventivo"},
]}
BROWSER = {"user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130"}


@pytest.fixture
def env(tmp_path):
    clients = tmp_path / "clients"
    clients.mkdir()
    (clients / "cantina.toml").write_text(CLIENT_TOML, encoding="utf-8")
    data = tmp_path / "data"
    with KnowledgeStore(data / "cantina" / "knowledge.db") as store:
        store.sync(copy.deepcopy(CONTENTS))

    llm = FakeLLM(*[copy.deepcopy(PLAN) for _ in range(5)])
    factories = {"llm": 0}

    def llm_factory():
        factories["llm"] += 1
        return llm

    app = create_app(clients_dir=clients, data_root=data, llm_factory=llm_factory,
                     embedder_factory=FakeEmbedder)
    return {"client": TestClient(app), "llm": llm, "data": data, "clients": clients,
            "factories": factories}


def post_plan(env, headers=BROWSER, **body):
    body.setdefault("pagina", "https://www.cantina.test/")
    return env["client"].post("/v1/cantina/plan", json=body, headers=headers)


def test_health_and_unknown_client(env):
    assert env["client"].get("/health").json() == {"stato": "ok"}
    assert env["client"].post("/v1/altro/plan", json={"pagina": "/"}).status_code == 404
    assert env["client"].get("/v1/Cantina.toml/status").status_code == 404


def test_weak_signals_give_standard_page_and_a_session(env):
    response = post_plan(env, lingua="it")
    data = response.json()
    assert response.status_code == 200
    assert data["standard"] is True and data["piano"] is None
    assert data["session_id"]
    assert data["motivi"] == ["profilo del visitatore non determinato"]
    assert env["llm"].calls == []


def test_declared_profile_gets_adaptive_page_with_content_data(env):
    data = post_plan(env, lingua="it", domanda="Siamo importatori dalla Germania, avete certificazioni?").json()
    assert data["standard"] is False
    assert data["profilo"]["id"] == "buyer_estero" and data["profilo"]["confidenza"] > 0.5

    blocks = data["piano"]["blocchi"]
    assert [b["componente"] for b in blocks] == ["hero", "certificazioni", "griglia_prodotti", "cta_contatto"]
    hero = blocks[0]["contenuti"][0]
    assert hero["titolo"] == "Cantina" and hero["immagine"]["alt"] == "Vigna"
    assert "testo" not in hero and "motivi" not in hero  # solo dati pubblici
    product = blocks[2]["contenuti"][0]
    assert product["specifiche"] == {"Vitigno": "Glera"}
    assert product["documenti"] == ["https://www.cantina.test/catalogo.pdf"]

    # La sessione ricorda la dichiarazione anche nelle pagine successive.
    later = post_plan(env, session_id=data["session_id"], pagina="https://www.cantina.test/cert/").json()
    assert later["session_id"] == data["session_id"]
    assert later["profilo"]["id"] == "buyer_estero"


def test_search_engines_always_get_the_standard_page(env):
    data = post_plan(env, headers={"user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
                     domanda="siamo importatori").json()
    assert data["standard"] is True and "motori di ricerca" in data["motivi"][0]
    assert env["llm"].calls == []
    assert is_bot("Mozilla/5.0 (compatible; bingbot/2.0)")
    assert not is_bot(BROWSER["user-agent"])


def test_emergency_switch(env):
    set_agent_active("cantina", False, "prova", base=env["data"])
    assert env["client"].get("/v1/cantina/status").json() == {"attivo": False}
    data = post_plan(env, domanda="siamo importatori").json()
    assert data["standard"] is True and data["motivi"] == ["agente disattivato"]
    assert env["factories"]["llm"] == 0

    set_agent_active("cantina", True, base=env["data"])
    assert post_plan(env, domanda="siamo importatori").json()["standard"] is False


def test_missing_model_gives_standard_page(tmp_path, env):
    def no_model():
        raise LLMError("manca MISTRAL_API_KEY")

    app = create_app(clients_dir=env["clients"], data_root=env["data"], llm_factory=no_model,
                     embedder_factory=FakeEmbedder)
    data = TestClient(app).post("/v1/cantina/plan", headers=BROWSER,
                                json={"pagina": "https://www.cantina.test/", "domanda": "siamo importatori"}).json()
    assert data["standard"] is True and data["motivi"] == ["modello linguistico non configurato"]


def test_content_endpoint_only_serves_approved_contents(env):
    response = env["client"].get("/v1/cantina/contents/prod-a")
    assert response.status_code == 200 and response.json()["titolo"] == "Prosecco"
    assert env["client"].get("/v1/cantina/contents/prod-bozza").status_code == 404
    assert env["client"].get("/v1/cantina/contents/inesistente").status_code == 404


def test_cors_only_for_declared_sites(env):
    allowed = env["client"].options("/v1/cantina/plan", headers={
        "Origin": "https://cantina.quuipu.me", "Access-Control-Request-Method": "POST"})
    assert allowed.headers["access-control-allow-origin"] == "https://cantina.quuipu.me"
    other = env["client"].options("/v1/cantina/plan", headers={
        "Origin": "https://malevolo.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in other.headers


def test_request_size_limits(env):
    assert post_plan(env, domanda="x" * 3000).status_code == 422


def test_sessions_expire_and_are_bound_to_one_client():
    now = [0.0]
    sessions = SessionStore(ttl=60, clock=lambda: now[0])
    first, created = sessions.get_or_create("cantina", None)
    assert created
    assert sessions.get_or_create("cantina", first.id) == (first, False)
    assert sessions.get_or_create("altro", first.id)[1] is True
    now[0] = 200
    assert sessions.get_or_create("cantina", first.id)[1] is True
    assert len(sessions) == 1  # le sessioni scadute sono state eliminate
