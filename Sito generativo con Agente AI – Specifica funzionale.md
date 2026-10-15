# Sito generativo con Agente AI – Specifica funzionale

Oct 15, 2026 · @Flavio

## 1. Visione e obiettivo

Il prodotto è un agente AI inserito nel sito di un'azienda cliente che ricompone la pagina in funzione del visitatore, usando solo contenuti aziendali già approvati.

- **Problema**: buyer esteri, privati e distributori si perdono tra molte pagine e lasciano il sito senza contattare l'azienda.
- **Promessa commerciale**: chi arriva sul sito trova subito ciò che gli serve, anche quando l'azienda non può rispondere.
- **Principio guida**: l'agente non inventa contenuti, li seleziona, li ordina e li adatta nel tono.
- **Primo prodotto vendibile**: un assistente che risponde ai visitatori con i contenuti già pubblicati.
- **Upgrade successivo**: la ricomposizione adattiva dell'intera pagina, proposta quando la fiducia del cliente c'è già.

Il prodotto si chiama **Quuipu**.

Il sito generato deve avere un taglio commerciale, orientato al contatto e alla vendita, e allo stesso tempo rispettare lo storytelling del sito di partenza: stessa voce, stessi valori, stesso stile.

## 2. Utenti, profili di visitatore e scenari

Il sistema ha tre tipi di utenti: l'azienda cliente, il visitatore del sito e tu come gestore della piattaforma.

| Profilo di visitatore | Cosa cerca | Cosa l'agente mette in primo piano |
| --- | --- | --- |
| Buyer estero (B2B) | Affidabilità, volumi, export | Certificazioni, capacità produttiva, contatti commerciali, lingua |
| Distributore o rivenditore | Margini, condizioni, cataloghi | Listino su richiesta, cataloghi PDF, condizioni di fornitura |
| Cliente privato | Prodotto e fiducia | Storia dell'azienda, schede prodotto, dove acquistare |
| Ente o stazione appaltante | Conformità e requisiti | Certificazioni, documentazione, referenze |
| Candidato o curioso | Chi siete | Chi siamo, lavora con noi, notizie |

Scenari d'uso principali:

1. Il visitatore arriva da una ricerca specifica e atterra su una pagina; l'agente adatta i blocchi sotto quella pagina.
2. Il visitatore scrive una domanda nella chat; l'agente risponde e ricompone la pagina intorno alla risposta.
3. Il visitatore chiede un preventivo o un contatto; l'agente raccoglie i dati essenziali e li inoltra all'azienda.
4. Il visitatore non interagisce; l'agente usa solo i segnali di contesto (provenienza, lingua, pagina d'ingresso). Se questi non danno informazioni sulle preferenze del visitatore, resta la pagina standard.

Settori dei primi clienti: agrifood (una cantina vitivinicola) e packaging (un'azienda che realizza profili in polistirolo EPS). I profili di visitatore della tabella vanno specializzati per ciascuno dei due settori.

## 3. Architettura generale e flusso dati

La logica sta sulla piattaforma in UE; il sito del cliente ospita solo il widget e resta funzionante anche senza.

&#91;embedded content: architettura · 3 zone, 1 punto di controllo\]

Il widget invia il contesto alla piattaforma e riceve il piano validato; il validatore è l'unico punto da cui passa tutto ciò che arriva al visitatore.

Flusso di una visita:

1. Il widget legge il contesto della sessione e lo invia alla piattaforma.
2. L'agente cerca nella base di conoscenza i contenuti pertinenti.
3. L'agente propone un page plan in JSON.
4. Il validatore controlla componenti, ID, schema e coerenza dei dati con quelli strutturati.
5. Il widget riceve il piano e mostra i blocchi; se qualcosa non torna, resta la pagina standard.
6. Conversazione e piano vengono registrati per metriche e revisione.

## 4. Ingestione automatica dei contenuti

L'ingestione trasforma il materiale del cliente in dati strutturati senza pulizia manuale, lasciando al cliente solo l'approvazione delle eccezioni.

1. **Crawler del sito esistente**: scarica pagine, testi, immagini e PDF già pubblicati, che sono per definizione contenuti approvati.
2. **Parsing di cataloghi e PDF**: un LLM estrae schede prodotto in JSON (nome, categoria, specifiche, certificazioni, documenti collegati).
3. **Analisi delle foto**: un modello vision genera descrizione, tag e categoria per ogni immagine.
4. **Classificazione**: ogni contenuto viene assegnato a un tipo (prodotto, certificazione, case study, chi siamo, FAQ, contatto) e a uno o più profili di visitatore.
5. **Livello di confidenza**: ogni elemento riceve un punteggio; sotto soglia va in coda di revisione.
6. **Revisione per eccezioni**: il cliente vede solo gli elementi dubbi, più prezzi, specifiche tecniche e claim legali, che vanno sempre confermati.
7. **Aggiornamento periodico**: il crawler ripassa il sito a intervalli e segnala le differenze da approvare.

Fonti ammesse: l'agente usa solo due fonti, il sito del cliente e una cartella dedicata.

- **Sito del cliente**: testi, immagini e documenti già pubblicati.
- **Cartella dedicata**: una cartella condivisa in cui l'azienda mette immagini, testi, PDF, brochure e listini che non sono sul sito.
- **Nessun'altra fonte**: tutto ciò che l'agente mostra proviene da una di queste due.
- **Aggiornamento automatico**: l'agente ricontrolla sito e cartella a intervalli e recepisce le modifiche; approvazione solo per prezzi, specifiche e claim legali.
- **Costo di aggiornamento**: l'aggiornamento di testi e media è coperto da un canone, annuale o mensile a scelta del cliente, di cui il cliente non deve occuparsi; l'azienda continua ad aggiornare sito o cartella come già fa.

## 5. Base di conoscenza chiusa e RAG

L'agente può usare solo ciò che sta nella base di conoscenza del singolo cliente; non attinge a conoscenza generale per fatti aziendali.

- **Archivio per cliente**: ogni cliente ha uno spazio separato (multi-tenant), senza condivisione di dati tra clienti.
- **Indice semantico**: testi e descrizioni delle immagini sono indicizzati in un database vettoriale per la ricerca per significato.
- **Dati strutturati separati**: prezzi, specifiche tecniche, codici, certificazioni e claim legali stanno in tabelle strutturate e vengono mostrati così come sono, mai riscritti dal modello.
- **Identificatori stabili**: ogni contenuto ha un ID; l'agente costruisce la pagina citando ID, non testo.
- **Se manca l'informazione**: l'agente dichiara di non avere la risposta e propone il contatto con l'azienda, senza inventare.
- **Lingue**: tutte le lingue europee; i contenuti sono tradotti automaticamente, con un glossario dei termini tecnici per ciascun cliente e traduzioni approvabili dal cliente.

## 6. Lettura del contesto del visitatore

L'agente deduce il profilo dal contesto della sessione, senza tracciamento persistente né identificazione della persona.

| Segnale | Esempio | Uso |
| --- | --- | --- |
| Pagina d'ingresso | Atterra su una scheda prodotto | Stabilisce l'interesse iniziale |
| Provenienza | Ricerca, social, link di un'associazione | Orienta il tono e i blocchi |
| Query di ricerca | Termini trasmessi dal referrer, se disponibili | Seleziona prodotti e FAQ |
| Lingua e dispositivo | Browser in inglese, smartphone | Lingua, layout e lunghezza |
| Navigazione nella sessione | Pagine viste, tempo, click | Affina il profilo durante la visita |
| Dichiarazione in chat | "Siamo un distributore tedesco" | Segnale più forte, prevale sugli altri |

Regole:

- Il profilo vive solo nella sessione e si azzera alla chiusura, salvo consenso esplicito.
- Il profilo è una probabilità su un elenco chiuso di profili, non un giudizio sulla persona.
- Se i segnali sono deboli, l'agente mostra la versione standard del sito.

## 7. Page plan e composizione della pagina

L'LLM non genera HTML: produce un page plan in JSON che il sito valida e trasforma in pagina. Così grafica e brand restano coerenti.

```json
{
  "profilo": "buyer_estero",
  "lingua": "en",
  "confidenza": 0.82,
  "blocchi": [
    { "componente": "hero", "contenuto_id": "home-hero-export" },
    { "componente": "certificazioni", "contenuto_id": "cert-all" },
    { "componente": "griglia_prodotti", "contenuto_id": ["p-101", "p-102", "p-107"] },
    { "componente": "cta_contatto", "variante": "export" }
  ]
}
```

Regole di composizione:

- L'agente sceglie solo componenti presenti nella libreria e solo ID presenti nella base di conoscenza.
- Il sito scarta ogni blocco non valido e ricade sulla pagina standard.
- L'agente decide ordine, priorità, variante e tono dei testi di raccordo; i testi aziendali restano invariati.
- Il piano si può rigenerare durante la sessione quando il profilo cambia, non a ogni click.
- I piani dei profili ricorrenti vengono messi in cache per costo e velocità.
- Ogni piano viene registrato (profilo, blocchi, esito) per verifica e miglioramento.

Storytelling e taglio commerciale:

- **Profilo di marca**: all'ingestione l'agente ricava dal sito tono, lessico e valori, e li salva in un profilo modificabile dal cliente.
- **Testi di raccordo**: seguono il profilo di marca; i testi aziendali non vengono riscritti.
- **Obiettivo di pagina**: ogni pagina composta punta a un'azione (contatto, preventivo, richiesta di campione) con una CTA coerente con il profilo del visitatore.

## 8. Libreria di componenti

Ogni componente è un blocco grafico con uno schema rigido; l'agente li assembla ma non li modifica.

| Componente | Funzione | Dati richiesti |
| --- | --- | --- |
| Hero | Messaggio di apertura adattato al profilo | Titolo, sottotitolo, immagine, CTA |
| Griglia prodotti | Selezione di prodotti pertinenti | ID prodotto, immagine, scheda |
| Scheda prodotto | Dettaglio con specifiche | Dati strutturati del catalogo |
| Certificazioni | Certificati e standard | Nome, ente, documento |
| Case study | Referenze di clienti | Testo approvato, settore, immagine |
| Chi siamo | Storia e valori | Testi approvati |
| FAQ | Risposte alle domande ricorrenti | Domanda, risposta, categoria |
| Cataloghi e documenti | Download di PDF | File, titolo, lingua |
| CTA e contatto | Richiesta di preventivo o chiamata | Campi del modulo, destinatario |

Per il PoC bastano hero, griglia prodotti, certificazioni, case study, FAQ e CTA.

## 9. Assistente conversazionale

L'assistente è il canale esplicito con cui il visitatore dichiara ciò che cerca; è anche il primo prodotto vendibile.

- **Posizione**: pulsante o barra sul sito, aperta su richiesta e non invasiva.
- **Risposte**: sempre basate sulla base di conoscenza, con rimando alla pagina o al documento di origine.
- **Azione sulla pagina**: la risposta può riordinare i blocchi o evidenziare la sezione pertinente.
- **Domande senza risposta**: l'assistente lo dichiara e offre un contatto umano.
- **Raccolta contatti**: chiede nome, azienda ed esigenza solo quando il visitatore vuole essere ricontattato, con informativa visibile.
- **Inoltro all'azienda**: email o notifica con riepilogo della conversazione e profilo stimato.
- **Tono e lingua**: definiti dal cliente (formale, cordiale) e adattati alla lingua del visitatore.
- **Argomenti esclusi**: consulenze legali, mediche o finanziarie, prezzi non pubblicati, impegni contrattuali.
- **Trasparenza**: il visitatore sa di parlare con un assistente AI.

## 10. Guardrail, validazione e revisione umana

Le regole che impediscono all'agente di danneggiare il cliente, con tre livelli di controllo.

1. **Prima della generazione**: l'agente riceve solo contenuti approvati del cliente corrente e una lista chiusa di componenti.
2. **Dopo la generazione**: il sito valida il page plan con uno schema; ID inesistenti, componenti non ammessi o formato errato fanno scattare la pagina standard.
3. **Controlli sul testo**: verifica che numeri, prezzi, specifiche e claim mostrati coincidano con i dati strutturati.

Regole fisse:

- Prezzi, specifiche tecniche, certificazioni e claim legali provengono solo da dati strutturati approvati.
- Testi di raccordo generati dall'agente: brevi, senza promesse, confronti con concorrenti o dati non presenti nella base.
- Il sito mostra la versione standard quando la confidenza è bassa, quando mancano informazioni sulle preferenze del visitatore e quando l'abbonamento del cliente non è attivo.
- Il cliente può bloccare argomenti, prodotti o pagine che l'agente non deve toccare.
- Ogni risposta dell'assistente e ogni piano restano registrati e consultabili dal cliente.
- Pulsante di emergenza: il cliente può disattivare l'agente in qualsiasi momento e il sito torna al funzionamento normale.

## 11. Modalità di integrazione sul sito del cliente

La logica dell'agente sta sulla tua infrastruttura in UE; il sito del cliente (anche su hosting condiviso, come Aruba) la richiama. Tre modalità, dalla più leggera.

| Modalità | Come funziona | Pro | Limiti |
| --- | --- | --- | --- |
| Widget embed | Il cliente incolla una riga di JavaScript | Nessuna migrazione, funziona su qualsiasi sito, rimovibile | Adattamento lato browser, poco peso SEO |
| Sottodominio | Un record DNS (es. new.cliente.it) punta alla tua app | Versione completa, SEO propria | Intervento sul DNS; su Aruba il terzo livello può avere un costo annuo a parte (da verificare) |
| Plugin WordPress | Un plugin PHP chiama le tue API e sostituisce i blocchi | Integrazione nativa per i siti WP | Solo per siti WordPress |

In produzione si parte dal widget. Il sottodominio è l'upgrade. In ogni caso serve un accordo di trattamento dati (DPA) con il cliente.

Percorso di adozione:

1. **Pilota**: versione adattiva ospitata da Quuipu su un sottodominio di quuipu.me (es. cantina.quuipu.me), senza interventi del cliente.
2. **Produzione**: widget da incollare nel sito del cliente.
3. **Upgrade opzionale**: sottodominio sul dominio del cliente.

Regole per il pilota ospitato:

- **Perimetro**: solo le pagine chiave (home, prodotti, chi siamo, certificazioni, contatti), ricostruite con i componenti di Quuipu; gli altri link rimandano al sito originale.
- **Consenso**: uso dei contenuti del cliente autorizzato per iscritto nell'accordo di pilota.
- **Visibilità**: versione in noindex, raggiungibile solo con il link, per evitare contenuti duplicati e confusione con il sito ufficiale.
- **Fedeltà al marchio**: grafica e storytelling riconoscibili rispetto al sito di partenza.

## 12. Privacy e GDPR

La privacy è parte del prodotto e un argomento di vendita: dati in UE, nessuna profilazione persistente.

- **Ruoli**: il cliente è titolare del trattamento, tu sei responsabile; serve un DPA firmato.
- **Hosting**: server e database in UE; modello linguistico con garanzie contrattuali sul non riutilizzo dei dati per addestramento.
- **Dati raccolti**: contesto di sessione e conversazione; nessun cookie di profilazione di default.
- **Analytics**: strumenti privacy-first, senza identificazione del singolo visitatore.
- **Informativa e consenso**: banner o link visibile per l'assistente; consenso esplicito prima di raccogliere contatti o conservare dati oltre la sessione.
- **Conservazione**: conversazioni conservate per un periodo definito col cliente, poi cancellate.
- **Diritti dell'interessato**: procedura per accesso e cancellazione dei dati.
- **Trasparenza**: indicazione chiara che si parla con un'IA.

Informativa e DPA vengono rivisti da Flavio prima dell'uso con clienti reali, pilota gratuito compreso.

## 13. SEO e prestazioni

La personalizzazione sta sopra pagine statiche indicizzabili, così il posizionamento del cliente non peggiora.

- **Pagine di base**: restano le pagine originali del cliente, indicizzate dai motori di ricerca.
- **Versione per i crawler**: i motori di ricerca vedono sempre la versione standard.
- **Contenuti adattivi**: caricati dopo la pagina, senza bloccarla né spostare gli elementi.
- **Velocità**: se l'agente non risponde entro una soglia (es. 1-2 secondi), la pagina standard resta visibile.
- **Cache**: piani dei profili ricorrenti in cache; richieste LLM ridotte al minimo.
- **Costi per visita**: monitorati per cliente, con un tetto mensile configurabile.
- **Accessibilità**: i componenti rispettano le regole di base di accessibilità.

## 14. Pannello di controllo del cliente

Un'area riservata in cui il cliente governa l'agente senza competenze tecniche.

- **Contenuti**: elenco di ciò che l'agente conosce, con stato (approvato, da rivedere, escluso).
- **Coda di revisione**: elementi a bassa confidenza, prezzi, specifiche e claim da confermare con un clic.
- **Regole**: tono, lingue, argomenti vietati, pagine o prodotti da non toccare.
- **Profili**: elenco dei profili di visitatore attivi e dei blocchi associati, modificabili.
- **Conversazioni**: storico delle richieste e dei contatti raccolti, con esportazione.
- **Interruttore**: attivazione e disattivazione immediata dell'agente.
- **Installazione**: istruzioni e codice del widget da copiare.
- **Accessi**: utenti del cliente con ruoli (amministratore, revisore).

Nel PoC il pannello può essere minimo o sostituito da file di configurazione.

## 15. Metriche e analytics

Le metriche servono a dimostrare al cliente il risultato durante il pilota, con indicatori concordati in anticipo.

| Metrica | Cosa misura |
| --- | --- |
| Contatti qualificati | Richieste di preventivo o chiamata generate dall'agente |
| Conversazioni avviate | Quanti visitatori usano l'assistente |
| Domande senza risposta | Contenuti mancanti da aggiungere alla base |
| Tempo e pagine per sessione | Coinvolgimento rispetto alla versione standard |
| Risultati per profilo | Quali profili convertono di più |
| Confronto con il sito standard | Test A/B tra pagina adattiva e pagina di base |
| Costo per visita | Spesa LLM per cliente |

I dati sono aggregati e anonimi; nessuna metrica richiede di identificare il singolo visitatore.

## 16. Perimetro: PoC, MVP e fuori ambito

Il PoC dimostra che l'idea funziona su un sito reale; l'MVP la rende vendibile a un primo cliente.

| Funzionalità | PoC (3-4 settimane) | MVP (8-12 settimane) | Dopo |
| --- | --- | --- | --- |
| Crawler del sito esistente | Sì | Sì | Aggiornamento automatico |
| Parsing PDF e foto | Base | Completo | Fonti aggiuntive |
| Base di conoscenza e RAG | Sì | Sì | Multi-lingua avanzata |
| Profili di visitatore | 2-3 | 5 | Profili personalizzati |
| Lingue | 2-3 | Tutte le lingue europee | Glossari estesi |
| Componenti | 5-6 | Libreria completa | Componenti su misura |
| Assistente conversazionale | Sì | Sì, con raccolta contatti | Integrazione CRM |
| Page plan e validazione | Sì | Sì | Test A/B automatici |
| Guardrail e revisione | Regole base | Coda di revisione | Controlli avanzati |
| Widget embed | No, versione ospitata su quuipu.me (pagine chiave) | Sì | Sottodominio sul dominio del cliente e plugin WordPress |
| Pannello cliente | File di configurazione | Versione minima | Pannello completo |
| Privacy e consenso | Bozza | Informativa e DPA rivisti | Audit periodici |
| Multi-tenant | No | Un cliente | Più clienti |

Fuori ambito per ora: e-commerce e pagamenti, integrazioni con gestionali, generazione di immagini, voce.

Modello commerciale: pilota gratuito; poi canone annuale o mensile, a scelta del cliente, con una possibile variante a consumo (costo a token, attivata quando serve).

## 17. Decisioni prese e punti ancora aperti

Decisioni prese:

- Primi settori: agrifood (cantina vitivinicola) e packaging (profili in EPS)
- Nome del prodotto: Quuipu
- Modello linguistico: Mistral
- Pilota gratuito; poi canone annuale o mensile a scelta del cliente, con opzione a consumo da valutare
- Lingue: tutte le lingue europee; il PoC è limitato a 2-3 lingue
- Dominio del pilota ospitato: quuipu.me
- Revisione di informativa e DPA: Flavio
- Sito demo del PoC: sito di un cliente reale
- Pagina standard quando mancano informazioni sulle preferenze del visitatore o l'abbonamento non è pagato

Punti ancora aperti:

- [ ] Durata e metriche del pilota gratuito
- [ ] Strumento per la cartella dedicata (Drive, OneDrive o altro) e chi ne cura l'ordine
- [ ] Profili di visitatore specifici per la cantina e per l'azienda EPS
- [ ] Glossario dei termini tecnici per le traduzioni
- [ ] Accordo di pilota e DPA firmati prima di lavorare sul sito reale
- [ ] Importi del canone annuale e del canone mensile
- [ ] Quali 2-3 lingue usare nel PoC
- [ ] Scelta degli altri modelli (embedding, vision) e del database vettoriale, tutti con hosting in UE
