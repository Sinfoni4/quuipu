"""Sito della cantina inventata "Cantina Valmora", usato dalla demo.

Tutti i nomi, gli indirizzi e i dati sono inventati. Il sito è in italiano
e inglese, con un catalogo PDF e alcune foto (immagini a tinta unita che il
modello simulato riconosce dal colore).
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from quuipu.demo.files import make_pdf, solid_png

IMAGES = {
    "vigneto.png": (74, 124, 58),
    "bottiglia.png": (110, 20, 40),
    "cantina.png": (120, 84, 52),
    "degustazione.png": (196, 154, 58),
    "facciata.png": (128, 128, 128),
}
CATALOG = "media/catalogo-valmora-2026.pdf"

# Il catalogo: righe senza accenti (font base del PDF).
CATALOG_PAGES = [
    [
        "Cantina Valmora - Catalogo 2026",
        "",
        "Vino: Valmora Prosecco Superiore DOCG Brut",
        "Categoria: spumante",
        "Descrizione: Bollicina fresca e floreale, perfetta come aperitivo.",
        "Vitigno: Glera",
        "Gradazione: 11,5% vol",
        "Formato: 0,75 l",
        "Certificazioni: Biologico",
        "",
        "Vino: Valmora Soave Classico DOC",
        "Categoria: bianco",
        "Descrizione: Bianco minerale con note di mandorla.",
        "Vitigno: Garganega",
        "Gradazione: 12,5% vol",
        "Formato: 0,75 l",
        "Certificazioni: Biologico",
    ],
    [
        "Vino: Valmora Valpolicella Ripasso DOC",
        "Categoria: rosso",
        "Descrizione: Rosso morbido e speziato, ripassato sulle vinacce dell'Amarone.",
        "Vitigno: Corvina, Rondinella",
        "Gradazione: 14% vol",
        "Formato: 0,75 l",
        "Prezzo: 18,00 euro",
        "Certificazioni: Biologico",
        "",
        "Vino: Valmora Amarone della Valpolicella DOCG",
        "Categoria: rosso",
        "Descrizione: Rosso strutturato da uve appassite, per lunghi invecchiamenti.",
        "Vitigno: Corvina, Corvinone",
        "Gradazione: 15,5% vol",
        "Formato: 0,75 l",
        "Certificazioni: Biologico",
    ],
]

# percorso: (lingua, titolo, descrizione, corpo HTML, immagine, traduzione)
PAGES: dict[str, tuple[str, str, str, str, str | None, str | None]] = {
    "/": ("it", "Cantina Valmora – Vini delle colline venete",
          "Cantina di famiglia sulle colline venete dal 1962.",
          "<h1>Cantina Valmora</h1>"
          "<p>Siamo una cantina di famiglia sulle colline venete. Dal 1962 coltiviamo 40 ettari "
          "di vigneto e produciamo vini che raccontano il nostro territorio.</p>"
          "<p>Scopri i nostri vini, vieni a trovarci per una degustazione o scrivici.</p>",
          "vigneto.png", "/en/"),
    "/storia/": ("it", "La nostra storia – Cantina Valmora",
                 "Tre generazioni di vignaioli a Valmora.",
                 "<h1>La nostra storia</h1>"
                 "<p>Nel 1962 nonno Giovanni pianta le prime viti sulle colline di Valmora. Oggi la terza "
                 "generazione della famiglia guida la cantina con lo stesso rispetto per la terra: "
                 "vendemmia a mano, rese basse, nessun diserbante.</p>",
                 "cantina.png", "/en/our-story/"),
    "/vini/": ("it", "I nostri vini – Cantina Valmora",
               "Prosecco, Soave, Ripasso e Amarone da agricoltura biologica.",
               "<h1>I nostri vini</h1>"
               "<p>Quattro vini, tutti da agricoltura biologica: Prosecco Superiore, Soave Classico, "
               "Valpolicella Ripasso e Amarone della Valpolicella.</p>"
               f'<p><a href="/{CATALOG}">Scarica il catalogo 2026 (PDF)</a></p>',
               "bottiglia.png", "/en/wines/"),
    "/certificazioni/": ("it", "Certificazioni – Cantina Valmora",
                         "Biologico, sostenibilità e sicurezza alimentare.",
                         "<h1>Certificazioni</h1>"
                         "<p>Dal 2015 tutti i nostri vigneti sono certificati in agricoltura biologica "
                         "(Reg. UE 2018/848), con controlli annuali dell'organismo di certificazione.</p>"
                         "<p>La cantina è certificata Equalitas per la sostenibilità e applica un sistema "
                         "HACCP per la sicurezza alimentare. Su richiesta forniamo schede tecniche, "
                         "analisi e certificati per ogni lotto.</p>",
                         None, "/en/certifications/"),
    "/export/": ("it", "Export – Cantina Valmora",
                 "Vini Valmora per importatori e distributori.",
                 "<h1>Export</h1>"
                 "<p>Esportiamo in 25 paesi tra Europa, Nord America e Asia. Produciamo 250.000 bottiglie "
                 "l'anno e lavoriamo con importatori e distributori selezionati.</p>"
                 "<p>Per gli importatori: etichette conformi ai requisiti di ogni paese, spedizioni su "
                 "pallet o container, documentazione doganale completa.</p>"
                 f'<p><a href="/{CATALOG}">Catalogo 2026 (PDF)</a></p>',
                 "facciata.png", "/en/export/"),
    "/referenze/": ("it", "Referenze – Cantina Valmora",
                    "Chi lavora con noi.",
                    "<h1>Referenze</h1>"
                    "<p>Enoteca Rossi, Milano: «Lavoriamo con Valmora dal 2018, i loro rossi sono tra i "
                    "più richiesti dai nostri clienti.»</p>"
                    "<p>Weinhaus Bauer, Monaco di Baviera: importatore per la Germania dal 2020.</p>",
                    None, "/en/references/"),
    "/degustazioni/": ("it", "Degustazioni e visite – Cantina Valmora",
                       "Visita i vigneti e la cantina.",
                       "<h1>Degustazioni e visite</h1>"
                       "<p>Visita guidata ai vigneti e alla cantina con degustazione di quattro vini. "
                       "Dal martedì alla domenica, su prenotazione. Durata 90 minuti.</p>",
                       "degustazione.png", "/en/tastings/"),
    "/faq/": ("it", "Domande frequenti – Cantina Valmora",
              "Spedizioni, ordini, visite.",
              "<h1>Domande frequenti</h1>"
              "<p><strong>Spedite all'estero?</strong> Sì, in tutta l'Unione Europea e, tramite i nostri "
              "importatori, in 25 paesi.</p>"
              "<p><strong>Qual è l'ordine minimo per i rivenditori?</strong> 60 bottiglie, anche assortite.</p>"
              "<p><strong>Avete vini biologici?</strong> Sì, tutti i nostri vini sono certificati biologici.</p>"
              "<p><strong>Si può visitare la cantina?</strong> Sì, su prenotazione.</p>",
              None, "/en/faq/"),
    "/contatti/": ("it", "Contatti – Cantina Valmora",
                   "Come raggiungerci e scriverci.",
                   "<h1>Contatti</h1>"
                   "<p>Via delle Vigne 12, Valmora (VR). Telefono +39 045 000000. "
                   "Email info@valmora.example. Ufficio export: export@valmora.example.</p>",
                   None, "/en/contacts/"),
    "/news/vinitaly-2026/": ("it", "Valmora al Vinitaly 2026 – Cantina Valmora",
                             "La nuova annata dell'Amarone.",
                             "<h1>Valmora al Vinitaly 2026</h1>"
                             "<p>Ad aprile 2026 abbiamo presentato al Vinitaly la nuova annata del nostro "
                             "Amarone. Grazie a chi è passato a trovarci.</p>",
                             None, None),
    "/privacy/": ("it", "Privacy policy – Cantina Valmora", "",
                  "<h1>Privacy policy</h1><p>Informativa sul trattamento dei dati personali dei visitatori "
                  "del sito.</p>", None, None),
    "/en/": ("en", "Cantina Valmora – Wines from the Venetian hills",
             "Family winery in the Venetian hills since 1962.",
             "<h1>Cantina Valmora</h1>"
             "<p>We are a family winery in the Venetian hills. Since 1962 we have farmed 40 hectares of "
             "vineyards and made wines that tell the story of our land.</p>",
             "vigneto.png", "/"),
    "/en/our-story/": ("en", "Our story – Cantina Valmora", "Three generations of winegrowers.",
                       "<h1>Our story</h1>"
                       "<p>In 1962 grandfather Giovanni planted the first vines on the Valmora hills. "
                       "Today the third generation runs the winery: hand harvest, low yields, no herbicides.</p>",
                       "cantina.png", "/storia/"),
    "/en/wines/": ("en", "Our wines – Cantina Valmora", "Organic Prosecco, Soave, Ripasso and Amarone.",
                   "<h1>Our wines</h1>"
                   "<p>Four wines, all from organic farming: Prosecco Superiore, Soave Classico, "
                   "Valpolicella Ripasso and Amarone della Valpolicella.</p>"
                   f'<p><a href="/{CATALOG}">Download the 2026 catalogue (PDF)</a></p>',
                   "bottiglia.png", "/vini/"),
    "/en/certifications/": ("en", "Certifications – Cantina Valmora", "Organic, sustainability, food safety.",
                            "<h1>Certifications</h1>"
                            "<p>Since 2015 all our vineyards have been certified organic (EU Reg. 2018/848), "
                            "with annual inspections by the certification body.</p>"
                            "<p>The winery is Equalitas certified for sustainability and applies an HACCP "
                            "food safety system. Technical sheets, analyses and certificates are available "
                            "for every lot on request.</p>",
                            None, "/certificazioni/"),
    "/en/export/": ("en", "Export – Cantina Valmora", "Valmora wines for importers and distributors.",
                    "<h1>Export</h1>"
                    "<p>We export to 25 countries across Europe, North America and Asia. We produce "
                    "250,000 bottles a year and work with selected importers and distributors.</p>"
                    "<p>For importers: labels compliant with each country, shipping on pallets or in "
                    "containers, complete customs documents.</p>"
                    f'<p><a href="/{CATALOG}">2026 catalogue (PDF)</a></p>',
                    "facciata.png", "/export/"),
    "/en/references/": ("en", "References – Cantina Valmora", "Who works with us.",
                        "<h1>References</h1>"
                        "<p>Enoteca Rossi, Milan: “We have worked with Valmora since 2018; their reds are "
                        "among our customers' favourites.”</p>"
                        "<p>Weinhaus Bauer, Munich: our importer for Germany since 2020.</p>",
                        None, "/referenze/"),
    "/en/tastings/": ("en", "Tastings and visits – Cantina Valmora", "Visit the vineyards and the winery.",
                      "<h1>Tastings and visits</h1>"
                      "<p>Guided tour of the vineyards and the winery with a tasting of four wines. "
                      "Tuesday to Sunday, by reservation. Duration 90 minutes.</p>",
                      "degustazione.png", "/degustazioni/"),
    "/en/faq/": ("en", "Frequently asked questions – Cantina Valmora", "Shipping, orders, visits.",
                 "<h1>Frequently asked questions</h1>"
                 "<p><strong>Do you ship abroad?</strong> Yes, across the European Union and, through our "
                 "importers, to 25 countries.</p>"
                 "<p><strong>What is the minimum order for retailers?</strong> 60 bottles, mixed cases allowed.</p>"
                 "<p><strong>Are your wines organic?</strong> Yes, all our wines are certified organic.</p>"
                 "<p><strong>Can I visit the winery?</strong> Yes, by reservation.</p>",
                 None, "/faq/"),
    "/en/contacts/": ("en", "Contacts – Cantina Valmora", "How to reach us.",
                      "<h1>Contacts</h1>"
                      "<p>Via delle Vigne 12, Valmora (VR), Italy. Phone +39 045 000000. "
                      "Email info@valmora.example. Export office: export@valmora.example.</p>",
                      None, "/contatti/"),
}

NAV = {
    "it": [("/", "Home"), ("/storia/", "Storia"), ("/vini/", "Vini"), ("/certificazioni/", "Certificazioni"),
           ("/export/", "Export"), ("/degustazioni/", "Degustazioni"), ("/faq/", "FAQ"),
           ("/contatti/", "Contatti"), ("/en/", "English")],
    "en": [("/en/", "Home"), ("/en/our-story/", "Story"), ("/en/wines/", "Wines"),
           ("/en/certifications/", "Certifications"), ("/en/export/", "Export"),
           ("/en/tastings/", "Tastings"), ("/en/faq/", "FAQ"), ("/en/contacts/", "Contacts"),
           ("/", "Italiano")],
}

STYLE = """
body{margin:0;font-family:Georgia,serif;color:#2b2420;background:#faf7f2}
header{background:#3d1f24;color:#f3e9dc;padding:18px 24px}
header .brand{font-size:22px;letter-spacing:.06em}
nav a{color:#f3e9dc;margin-right:14px;font-family:system-ui,sans-serif;font-size:14px;text-decoration:none}
main{max-width:760px;margin:0 auto;padding:24px 20px 48px}
main img{width:100%;height:auto;border-radius:6px;margin:12px 0}
footer{border-top:1px solid #e0d6c8;padding:16px 24px;font:13px system-ui,sans-serif;color:#7a6e64}
footer a{color:#7a6e64}
@media (max-width:600px){nav a{display:inline-block;margin:4px 10px 4px 0}}
"""


def render_page(path: str) -> str:
    lang, title, description, body, image, alternate = PAGES[path]
    nav = " ".join(f'<a href="{href}">{escape(label)}</a>' for href, label in NAV[lang])
    links = ""
    if alternate:
        other = PAGES[alternate][0]
        links = (f'<link rel="alternate" hreflang="{lang}" href="{path}">'
                 f'<link rel="alternate" hreflang="{other}" href="{alternate}">')
    img = f'<img src="/media/{image}" alt="{escape(title.split(" – ")[0])}">' if image else ""
    privacy = "Privacy" if lang == "it" else "Privacy policy"
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(description)}">{links}
<style>{STYLE}</style></head>
<body><header><div class="brand">CANTINA VALMORA</div><nav>{nav}</nav></header>
<main>{body}{img}</main>
<footer>Cantina Valmora · sito dimostrativo con dati inventati ·
<a href="/privacy/">{privacy}</a> · <a href="/area-riservata/login/">Area riservata</a></footer>
</body></html>"""


def build_site(root: Path, base_url: str) -> None:
    """Scrive il sito statico in root: pagine, sitemap, robots, PDF e immagini."""
    for path in PAGES:
        target = root / path.strip("/") / "index.html" if path != "/" else root / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_page(path), encoding="utf-8")

    login = root / "area-riservata" / "login" / "index.html"
    login.parent.mkdir(parents=True, exist_ok=True)
    login.write_text("<html><body><form>Login riservato</form></body></html>", encoding="utf-8")

    media = root / "media"
    media.mkdir(parents=True, exist_ok=True)
    for name, color in IMAGES.items():
        (media / name).write_bytes(solid_png(color))
    (root / CATALOG).write_bytes(make_pdf(CATALOG_PAGES))

    base = base_url.rstrip("/")
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in PAGES)
    (root / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        encoding="utf-8",
    )
    (root / "robots.txt").write_text(
        f"User-agent: *\nDisallow: /area-riservata/\n\nSitemap: {base}/sitemap.xml\n", encoding="utf-8"
    )
