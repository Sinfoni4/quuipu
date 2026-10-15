# Quuipu

Agente AI che ricompone le pagine del sito di un'azienda in funzione del visitatore, usando solo contenuti aziendali già approvati.

La specifica funzionale completa è in [Sito generativo con Agente AI – Specifica funzionale.md](Sito%20generativo%20con%20Agente%20AI%20–%20Specifica%20funzionale.md).

## Stato

PoC in avvio:

- **Sito pilota:** cantina vitivinicola, ospitato su quuipu.me.
- **Stack:** backend Python (FastAPI) e front-end statico.
- **Modello linguistico:** Mistral.

## Struttura

- `clients/`: configurazione di ogni cliente (sito, lingue, esclusioni del crawler).
- `src/quuipu/ingestion/`: ingestione dei contenuti; per ora c'è solo il crawler del sito.
- `tests/`: test automatici.
- `data/`: pagine scaricate e dati generati. Non va su git.

## Uso

Installazione:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Test:

```bash
.venv\Scripts\python.exe -m pytest
```

Crawl del sito di un cliente. I risultati vanno in `data/<cliente>/crawl/`.

```bash
.venv\Scripts\quuipu-crawl.exe casapaladin --max-pages 20
```
