"""Interruttore dell'agente per cliente (specifica §10 e §14).

Il pulsante di emergenza: con l'agente spento il sito torna subito alla
versione standard, senza riavviare nulla, perché l'API rilegge lo stato a
ogni richiesta. Lo stesso interruttore copre l'abbonamento non attivo.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from quuipu.config import data_dir, load_client


def _path(client_id: str, base: Path | None = None) -> Path:
    return (base or data_dir()) / client_id / "agent.json"


def agent_status(client_id: str, base: Path | None = None) -> dict:
    path = _path(client_id, base)
    if not path.exists():
        return {"attivo": True, "motivo": "", "aggiornato": None}
    return json.loads(path.read_text(encoding="utf-8"))


def agent_active(client_id: str, base: Path | None = None) -> bool:
    return bool(agent_status(client_id, base)["attivo"])


def set_agent_active(client_id: str, active: bool, reason: str = "", base: Path | None = None) -> dict:
    status = {
        "attivo": active,
        "motivo": reason,
        "aggiornato": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = _path(client_id, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Accende o spegne l'agente di un cliente.")
    parser.add_argument("client", help="ID del cliente")
    parser.add_argument("azione", choices=["stato", "accendi", "spegni"])
    parser.add_argument("--motivo", default="", help="es. 'abbonamento scaduto'")
    args = parser.parse_args(argv)

    load_client(args.client)  # verifica che il cliente esista
    if args.azione == "stato":
        status = agent_status(args.client)
    else:
        status = set_agent_active(args.client, args.azione == "accendi", args.motivo)
    state = "ACCESO" if status["attivo"] else "SPENTO"
    print(f"Agente di {args.client}: {state}" + (f" ({status['motivo']})" if status["motivo"] else ""))


if __name__ == "__main__":
    main()
