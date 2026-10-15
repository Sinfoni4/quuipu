# Quuipu

Agente AI che ricompone le pagine del sito di un'azienda in funzione del visitatore, usando solo contenuti aziendali già approvati.

La specifica funzionale completa è in [Sito generativo con Agente AI – Specifica funzionale.md](Sito%20generativo%20con%20Agente%20AI%20–%20Specifica%20funzionale.md).

## Stato

PoC in costruzione:

- **Sito pilota:** cantina vitivinicola, ospitato su quuipu.me.
- **Stack:** backend Python (FastAPI) e front-end statico.
- **Modelli:** Mistral per il testo e mistral-embed per la ricerca semantica; il modello per le immagini non è ancora stato scelto.
- **Fatto:** ingestione completa e base di conoscenza con ricerca semantica.
- **Da fare:** page plan e validatore, API, sito pilota, assistente in chat.

## Struttura

- `clients/`: configurazione di ogni cliente (sito, lingue, profili, esclusioni).
- `src/quuipu/pipeline.py`: ingestione completa in un solo comando.
- `src/quuipu/ingestion/`: singoli passaggi dell'ingestione.
  - `crawler.py`: scarica il sito.
  - `assets.py`: scarica PDF e immagini.
  - `documents.py`: estrae schede prodotto dai PDF.
  - `images.py`: descrive le foto.
  - `classification.py`: assegna tipo e profili di visitatore.
  - `review.py`: decide cosa va in coda di revisione.
  - `llm.py`: accesso ai modelli.
- `src/quuipu/knowledge/`: base di conoscenza.
  - `store.py`: archivio per cliente con stato di approvazione (SQLite nel PoC).
  - `build.py`: costruisce i contenuti dai risultati dell'ingestione.
  - `search.py`: indicizzazione e ricerca per significato.
  - `embeddings.py`: calcolo dei vettori.
  - `cli.py`: comandi per revisione e ricerca.
- `tests/`: test automatici, con sito, modelli ed embedding simulati.
- `data/`: dati scaricati e generati, una cartella per cliente. Non va su git.

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

Per i comandi che usano i modelli copia `.env.example` in `.env` e inserisci la chiave Mistral.

### Ingestione completa

Un solo comando esegue in ordine: crawl, download, parsing dei PDF, immagini, classificazione, base di conoscenza e indice. Con `--folder` si aggiunge la cartella dedicata del cliente; con `--skip-crawl` si riusa l'ultimo crawl. Se manca il modello per le immagini, quel passaggio viene saltato con un avviso.

```bash
.venv\Scripts\quuipu-ingest.exe casapaladin --max-pages 20
```

### Coda di revisione

Comandi disponibili:

- `lista`: elenca i contenuti, con filtri `--stato`, `--tipo`, `--profilo`.
- `mostra`: mostra un contenuto con i motivi della revisione.
- `approva` / `escludi`: registra la decisione del cliente.
- `annulla`: cancella la decisione.

```bash
.venv\Scripts\quuipu-review.exe casapaladin lista --stato da_rivedere
```

```bash
.venv\Scripts\quuipu-review.exe casapaladin approva prod-1234abcd5678
```

### Ricerca nella base di conoscenza

Restituisce solo contenuti approvati.

```bash
.venv\Scripts\quuipu-search.exe casapaladin "vini per l'export" --profilo buyer_estero
```

### Singoli passaggi

```bash
.venv\Scripts\quuipu-crawl.exe casapaladin --max-pages 20
```

```bash
.venv\Scripts\quuipu-parse-docs.exe casapaladin percorso\cartella-pdf
```

```bash
.venv\Scripts\quuipu-describe-images.exe casapaladin percorso\cartella-foto
```

```bash
.venv\Scripts\quuipu-classify.exe casapaladin
```
