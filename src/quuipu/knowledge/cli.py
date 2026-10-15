"""Comandi per consultare la base di conoscenza e gestire la coda di revisione.

Nel PoC sostituiscono il pannello di controllo del cliente (specifica §14).
"""

from __future__ import annotations

import argparse
import json

from quuipu.config import load_client
from quuipu.knowledge.embeddings import default_embedder
from quuipu.knowledge.search import search
from quuipu.knowledge.store import APPROVED, EXCLUDED, TO_REVIEW, KnowledgeStore


def _line(content: dict) -> str:
    title = content["titolo"] or content["testo"].split("\n")[0]
    profiles = ",".join(content["profili"]) or "-"
    return f"{content['id']}  [{content['stato']}]  {content['tipo']}  ({profiles})  {title[:70]}"


def review_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Coda di revisione dei contenuti di un cliente.")
    parser.add_argument("client", help="ID del cliente")
    sub = parser.add_subparsers(dest="azione", required=True)
    lista = sub.add_parser("lista", help="elenca i contenuti")
    lista.add_argument("--stato", choices=[APPROVED, TO_REVIEW, EXCLUDED])
    lista.add_argument("--tipo")
    lista.add_argument("--profilo")
    for name, help_text in (
        ("mostra", "mostra un contenuto con i motivi di revisione"),
        ("approva", "approva un contenuto"),
        ("escludi", "esclude un contenuto: l'agente non lo userà"),
        ("annulla", "annulla la decisione presa su un contenuto"),
    ):
        sub.add_parser(name, help=help_text).add_argument("id", nargs="+")
    args = parser.parse_args(argv)

    with KnowledgeStore.for_client(load_client(args.client)) as store:
        if args.azione == "lista":
            contents = store.list(stato=args.stato, tipo=args.tipo, profilo=args.profilo)
            for content in contents:
                print(_line(content))
            print(f"\n{len(contents)} contenuti. Totali per stato: {store.counts()}")
            return
        decisions = {"approva": APPROVED, "escludi": EXCLUDED, "annulla": None}
        for content_id in args.id:
            if args.azione == "mostra":
                content = store.get(content_id)
                print(json.dumps(content, ensure_ascii=False, indent=2) if content
                      else f"{content_id}: non trovato")
            elif store.decide(content_id, decisions[args.azione]):
                print(_line(store.get(content_id)))
            else:
                print(f"{content_id}: non trovato")


def search_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ricerca per significato nella base di conoscenza.")
    parser.add_argument("client", help="ID del cliente")
    parser.add_argument("domanda", help="testo da cercare")
    parser.add_argument("-k", type=int, default=5, help="numero di risultati")
    parser.add_argument("--profilo")
    parser.add_argument("--tipo")
    parser.add_argument("--lingua")
    args = parser.parse_args(argv)

    with KnowledgeStore.for_client(load_client(args.client)) as store:
        results = search(
            store, default_embedder(), args.domanda, k=args.k,
            profilo=args.profilo, tipo=args.tipo, lingua=args.lingua,
        )
    for r in results:
        print(f"{r['punteggio']:.3f}  {_line(r['contenuto'])}")
        print("        " + r["estratto"].replace("\n", " ")[:160])
    if not results:
        print("Nessun contenuto approvato pertinente.")
