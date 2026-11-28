"""Este știrea despre Brașov/Covasna?

Sursele locale (News BV, BZB etc.) publică și știri din alte județe: „Accident grav în Teleorman”
venea de la News BV și era tratată ca știre locală doar pentru că sursa e locală.

Regula, în ordine:
1. textul (titlu + începutul) pomenește o localitate din Brașov sau Covasna → local;
2. titlul numește alt județ sau un oraș mare din afara zonei → nu e local;
3. altfel nu putem spune nimic → decide categoria sursei.
"""
import re
import unicodedata

# Cele 58 de UAT-uri din județul Brașov (config/primarii_brasov.yaml), fără numele care sunt
# și cuvinte obișnuite, prenume sau localități omonime din alte județe (Victoria, Cristian, Lisa,
# Mândra, Bod, Comana, Recea, Augustin, Beclean, Dumbrăvița, Părău, Vulcan). La fel în Covasna:
# Catalina, Reci, Mereni, Turia lipsesc; cartierul Noua lipsește („Nouă spitale”).
BRASOV_PLACES = [
    "Brașov", "Apața", "Bran", "Budila", "Bunești", "Cața", "Cincu", "Codlea", "Crizbav",
    "Drăguș", "Făgăraș", "Feldioara", "Fundata", "Ghimbav", "Hălchiu", "Hărman", "Hârseni",
    "Hoghiz", "Holbav", "Homorod", "Jibert", "Măieruș", "Moieciu", "Ormeniș", "Poiana Mărului",
    "Predeal", "Prejmer", "Racoș", "Râșnov", "Rupea", "Săcele", "Sâmbăta de Sus", "Sânpetru",
    "Șercaia", "Șinca", "Șoarș", "Tărlungeni", "Teliu", "Ticușu", "Ucea", "Ungra",
    "Vama Buzăului", "Viștea", "Voila", "Zărnești",
    # repere frecvente în știri
    "Poiana Brașov", "Tâmpa", "Postăvarul", "Piatra Craiului", "Timișu de Sus", "Dârste",
    "Răcădău", "Stupini", "Valea Prahovei", "Sepsi",
]

COVASNA_PLACES = [
    "Covasna", "Sfântu Gheorghe", "Târgu Secuiesc", "Baraolt", "Întorsura Buzăului",
    "Aita Mare", "Arcuș", "Barcani", "Bățani", "Belin", "Bixad", "Bodoc", "Boroșneu Mare",
    "Brăduț", "Brateș", "Brețcu", "Cernat", "Chichiș", "Comandău", "Dalnic",
    "Dobârlău", "Estelnic", "Ghelința", "Ghidfalău", "Hăghig", "Ilieni", "Lemnia", "Malnaș",
    "Micfalău", "Moacșa", "Ojdula", "Ozun", "Sânzieni", "Sita Buzăului",
    "Valea Crișului", "Vâlcele", "Vârghiș", "Zagon", "Zăbala",
]

# Alte județe și orașe mari. Alba, Olt și Mureș sunt și cuvinte/râuri care trec prin zonă,
# deci contează doar în forma „județul X” sau cu numele orașului.
OTHER_REGIONS = [
    "Arad", "Argeș", "Bacău", "Bihor", "Bistrița", "Botoșani", "Brăila", "Buzău",
    "Caraș-Severin", "Călărași", "Cluj", "Constanța", "Dâmbovița", "Dolj", "Galați", "Giurgiu",
    "Gorj", "Harghita", "Hunedoara", "Ialomița", "Iași", "Ilfov", "Maramureș", "Mehedinți",
    "Neamț", "Prahova", "Satu Mare", "Sălaj", "Sibiu", "Suceava", "Teleorman", "Timiș",
    "Tulcea", "Vaslui", "Vâlcea", "Vrancea",
    "București", "Capitală", "Capitalei", "Timișoara", "Craiova", "Ploiești", "Pitești",
    "Oradea", "Alba Iulia", "Târgu Mureș", "Târgu Jiu", "Râmnicu Vâlcea", "Miercurea Ciuc",
    "Odorheiu Secuiesc", "Baia Mare", "Drobeta-Turnu Severin", "Focșani", "Piatra Neamț",
    "Slatina", "Deva", "Zalău", "Reșița", "Sinaia", "Bușteni", "Azuga",
    "județul Alba", "județul Olt", "județul Mureș",
]


def _fold(text):
    """Fără diacritice, litere mici: „Brașov” și „Brasov” sunt același cuvânt."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


# „Brașovului”, „Brașovul”, „brașovenii”, „Făgărașului”
_LOCAL_SUFFIX = r"(?:ul|ului|ean|eana|eanca|eni|enii|enilor|ence|encele)?"


def _pattern(names, suffix=""):
    alts = sorted({re.escape(_fold(n)) for n in names}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")" + suffix + r"(?![a-z0-9])")


_LOCAL_RE = _pattern(BRASOV_PLACES + COVASNA_PLACES, _LOCAL_SUFFIX)
_OTHER_RE = _pattern(OTHER_REGIONS)


def mentions_local_place(text):
    return bool(_LOCAL_RE.search(_fold(text)))


def other_region_in(title):
    """Primul județ/oraș din afara zonei numit în titlu, sau None."""
    m = _OTHER_RE.search(_fold(title))
    return m.group(0) if m else None


def scope(article, head_chars=1500):
    """'local', 'alta_zona' sau None (nu reiese din text)."""
    title = article.get("title") or ""
    body = (article.get("content") or article.get("text") or "")[:head_chars]
    if mentions_local_place(title + "\n" + body):
        return "local"
    if other_region_in(title):
        return "alta_zona"
    return None
