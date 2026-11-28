"""Titlul, descrierea și introducerea fiecărei pagini /categorie/<cheie>.

Fără ele, toate categoriile aveau aceeași meta description (cea a site-ului) și un titlu de un
cuvânt („Sport - KronPapir”), iar lista conține mai ales rezumate cu noindex: pagina avea nevoie
de text propriu ca să nu fie subțire.
"""

CATEGORY_SEO = {
    "local": {
        "h1": "Știri locale din Brașov",
        "title": "Știri locale Brașov: ce se întâmplă în oraș și în județ",
        "description": "Știrile locale din Brașov și din județ, pe scurt și cu link la publicația care le-a scris: primărie, cartiere, trafic, evenimente.",
        "intro": "Ce se întâmplă în Brașov și în localitățile din jur, adunat din presa locală și din comunicatele instituțiilor. Fiecare știre are link la publicația care a scris-o.",
    },
    "politica": {
        "h1": "Știri politice din Brașov",
        "title": "Politică Brașov: Primăria, Consiliul Local și Consiliul Județean",
        "description": "Știri politice din Brașov: deciziile Primăriei, votul din Consiliul Local, Consiliul Județean, parlamentarii de Brașov și alegerile locale.",
        "intro": "Deciziile care se iau la Primăria Brașov, în Consiliul Local și în Consiliul Județean, plus ce fac parlamentarii aleși în Brașov. Proiectele de hotărâre explicate pe înțeles le găsești pe pagina <a href=\"/afaceri-brasov/primaria-brasov\">Primăria Brașov</a>.",
    },
    "economie": {
        "h1": "Știri economice din Brașov",
        "title": "Economie Brașov: firme, investiții, locuri de muncă",
        "description": "Economia Brașovului: firme noi și închise (date ONRC), investiții, fabrici, licitații ale primăriilor și piața muncii din județ.",
        "intro": "Investiții, fabrici, firme noi și închise, licitații și piața muncii din județul Brașov. Cifrele lunare despre firme sunt pe <a href=\"/afaceri-brasov\">Afaceri în Brașov</a>, iar ofertele de muncă pe <a href=\"/locuri-de-munca-brasov\">Locuri de muncă Brașov</a>.",
    },
    "cultura": {
        "h1": "Cultură și evenimente în Brașov",
        "title": "Cultură Brașov: spectacole, concerte, expoziții și festivaluri",
        "description": "Evenimente culturale în Brașov: spectacole, concerte, expoziții, festivaluri și ce se deschide în oraș, cu data și locul fiecărui eveniment.",
        "intro": "Spectacole, concerte, expoziții și festivaluri din Brașov și din județ: ce se întâmplă, când și unde.",
    },
    "sport": {
        "h1": "Știri sportive din Brașov",
        "title": "Sport Brașov: fotbal, hochei, handbal și competiții locale",
        "description": "Știri sportive din Brașov: fotbal, hochei, handbal, schi și competițiile cluburilor din județ, cu rezultate și programul meciurilor.",
        "intro": "Rezultatele și meciurile echipelor din Brașov și din județ: fotbal, hochei, handbal, sporturi de iarnă și competiții locale.",
    },
    "sanatate": {
        "h1": "Știri de sănătate din Brașov",
        "title": "Sănătate Brașov: spitale, medici, programe și campanii",
        "description": "Știri de sănătate din Brașov: Spitalul Județean, spitalele din județ, programe de screening, campanii de vaccinare și schimbări pentru pacienți.",
        "intro": "Ce se schimbă la spitalele din Brașov și din județ, programe de prevenție și informații utile pentru pacienți.",
    },
    "social": {
        "h1": "Știri sociale din Brașov",
        "title": "Social Brașov: educație, comunitate, ajutoare și servicii publice",
        "description": "Știri sociale din Brașov: școli, ajutoare, servicii publice, transport și viața din cartiere, cu link la sursă.",
        "intro": "Școli, ajutoare sociale, servicii publice, transport și viața din cartierele Brașovului.",
    },
    "mediu": {
        "h1": "Știri de mediu din Brașov",
        "title": "Mediu Brașov: aer, păduri, urși, deșeuri și spații verzi",
        "description": "Știri de mediu din Brașov: calitatea aerului, păduri, urși în oraș, deșeuri, parcuri și spații verzi din județ.",
        "intro": "Calitatea aerului, pădurile, urșii care coboară în oraș, deșeurile și spațiile verzi din Brașov și din județ.",
    },
}


def seo_for(key, fallback_name):
    return CATEGORY_SEO.get(key) or {"h1": fallback_name, "title": f"{fallback_name} Brașov",
                                     "description": f"Știri {fallback_name.lower()} din Brașov, cu link la sursă.", "intro": ""}
