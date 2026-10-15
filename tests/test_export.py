import json
import zipfile

from quuipu.demo.export import export


def test_static_export_is_self_contained(tmp_path):
    archive = export(tmp_path / "quuipu-demo", log=lambda _: None)
    out = tmp_path / "quuipu-demo"

    page = (out / "index.html").read_text(encoding="utf-8")
    assert "window.QUUIPU_STATIC = true" in page
    assert '<meta name="robots" content="noindex, nofollow">' in page
    assert "noindex" in (out / "_headers").read_text(encoding="utf-8")

    recordings = json.loads((out / "data" / "registrazioni.json").read_text(encoding="utf-8"))
    assert len(recordings["acceso"]) == len(recordings["spento"]) == 6
    assert [r["standard"] for r in recordings["acceso"]] == [True, False, False, False, False, True]
    assert all(r["motivi"] == ["agente disattivato"] for r in recordings["spento"])
    assert all(r["session_id"] is None for r in recordings["acceso"])

    # Nessun riferimento al server locale: tutto punta a /sito.
    for name in ("info.json", "registrazioni.json"):
        assert "127.0.0.1" not in (out / "data" / name).read_text(encoding="utf-8")
    assert (out / "sito" / "media" / "catalogo-valmora-2026.pdf").exists()
    assert 'href="/sito/storia/"' in (out / "sito" / "index.html").read_text(encoding="utf-8")

    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
    assert "index.html" in names and "data/registrazioni.json" in names
