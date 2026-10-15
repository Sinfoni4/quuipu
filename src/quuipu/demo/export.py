"""Esporta la demo come sito statico, pronto per Netlify Drop.

Esegue la demo vera (sito inventato, pipeline, modello simulato), registra le
risposte della piattaforma per ogni visitatore-tipo, con agente acceso e
spento, e scrive una cartella statica più il relativo zip:

    index.html            la pagina di demo in modalità registrata
    data/info.json        sintesi dell'ingestione e coda di revisione
    data/registrazioni.json  le risposte della piattaforma
    sito/                 il sito della cantina inventata
    _headers, robots.txt  la demo non va indicizzata dai motori di ricerca
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from quuipu.config import ROOT_DIR
from quuipu.demo.run import CLIENT_ID, SCENARIOS, STATIC_DIR, create_demo_app, prepare
from quuipu.demo.site import build_site

SITE_PREFIX = "/sito"
BROWSER = {"user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130"}


def _relocate(data: object, site_url: str) -> object:
    """Sostituisce l'indirizzo locale del sito con il percorso pubblico /sito."""
    text = json.dumps(data, ensure_ascii=False).replace(site_url, SITE_PREFIX)
    return json.loads(text)


def record(client: TestClient, site_url: str) -> dict[str, list[dict]]:
    recordings: dict[str, list[dict]] = {}
    for state in ("acceso", "spento"):
        client.post("/demo-api/agent", json={"attivo": state == "acceso"})
        responses = []
        for scenario in SCENARIOS:
            body = {k: scenario[k] for k in ("referrer", "lingua", "domanda") if k in scenario}
            body["pagina"] = site_url + scenario["pagina"]
            response = client.post(f"/v1/{CLIENT_ID}/plan", json=body, headers=BROWSER).json()
            response["session_id"] = None  # nessun codice di sessione nella versione pubblica
            responses.append(response)
        recordings[state] = responses
    client.post("/demo-api/agent", json={"attivo": True})
    return recordings


def export(out_dir: Path, log=print) -> Path:
    """Scrive la demo statica in out_dir e restituisce il percorso dello zip."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "data").mkdir(parents=True)

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "demo"
        log("Eseguo la demo: sito inventato, ingestione con modello simulato...")
        summary = prepare(base, site_port=0, log=lambda _: None)
        site_url = summary["sito"]
        client = TestClient(create_demo_app(base, summary))
        info = client.get("/demo-api/info").json()
        info["registro"] = []  # il registro locale non serve online
        log("Registro le risposte per ogni visitatore-tipo...")
        recordings = record(client, site_url)

    (out_dir / "data" / "info.json").write_text(
        json.dumps(_relocate(info, site_url), ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "data" / "registrazioni.json").write_text(
        json.dumps(_relocate(recordings, site_url), ensure_ascii=False, indent=1), encoding="utf-8")

    build_site(out_dir / "sito", SITE_PREFIX, prefix=SITE_PREFIX)
    (out_dir / "sito" / "robots.txt").unlink()
    (out_dir / "sito" / "sitemap.xml").unlink()

    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    page = page.replace("<head>", '<head>\n<meta name="robots" content="noindex, nofollow">', 1)
    page = page.replace("<script>", "<script>window.QUUIPU_STATIC = true;</script>\n<script>", 1)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    (out_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (out_dir / "_headers").write_text("/*\n  X-Robots-Tag: noindex, nofollow\n", encoding="utf-8")

    archive = shutil.make_archive(str(out_dir), "zip", root_dir=out_dir)
    return Path(archive)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Esporta la demo statica per Netlify.")
    parser.add_argument("--out", type=Path, default=ROOT_DIR / "dist" / "quuipu-demo",
                        help="cartella di destinazione (lo zip viene creato accanto)")
    args = parser.parse_args(argv)
    archive = export(args.out)
    print(f"Cartella: {args.out}")
    print(f"Zip per Netlify Drop: {archive}")


if __name__ == "__main__":
    main()
