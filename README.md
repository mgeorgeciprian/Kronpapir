# KronPapir - Agregator de Știri Locale Brașov/Covasna

Un agregator modern și profesional de știri locale din Brașov și Covasna, powered by AI.

**Slogan:** "Știri din inima Transilvaniei"

## Despre Proiect

KronPapir este un website de noutăți cu design modern de ziar, care agregează și prezintă automat articole din surse locale și naționale. Proiectul combine tehnologia AI cu o interfață curată și ușor de utilizat.

Denumirea "KronPapir" este o combinație între:
- **Kronstadt** - denumirea germană istorică a Brașovului
- **Papir** - hârtie, reflectând natura tradițională a unui ziar

## Caracteristici

✅ Design Profesional - Aspect modern de ziar online cu tipografie elegantă
✅ Responsiv - Funcționează perfect pe desktop, tablet și mobile
✅ Organizat - 8 categorii principale (politică, economie, cultură, sport, etc.)
✅ Dark Mode - Suport pentru modul întunecat
✅ Optimizat SEO - Meta tags, Open Graph, și structured data
✅ API JSON - Endpoint pentru accesul programatic la articole
✅ Pagini Dedicate - Homepage, pagina articol, categorii, și despre
✅ Paginare - Navigare prin articole cu paginație
✅ Newsletter - Placeholder pentru abonare la newsletter

## Instalare și Rulare

1. Instalare dependențe:
   pip install -r requirements.txt

2. Pornire server:
   cd web && python app.py

3. Acces: http://localhost:5000

## Structura JSON Articole

Plasează fișiere JSON în data/processed/ cu structura:

{
  "id": "1",
  "title": "Titlu",
  "excerpt": "Rezumat",
  "content": "Conținut",
  "category": "politica|economie|cultura|sport|sanatate|social|mediu|local",
  "date": "2024-02-08",
  "source": "Publicație",
  "type": "local|national",
  "author": "Autor (optional)",
  "image": "URL imagine",
  "url": "URL original (optional)"
}

## Rutele Disponibile

/ - Homepage
/local - Știri locale
/national - Știri naționale  
/categorie/<cat> - După categorie
/articol/<id> - Articol singular
/despre - Pagina Despre
/api/articles - API JSON

## Culori

- Verde Închis (#1a472a) - Principale
- Verde Mediu (#2d6a42) - Secundare
- Roșu (#c41e3a) - Ultimă oră
- Crem (#f5f0e8) - Background

## Tipografie

- Headlines: Playfair Display
- Body: Inter
- Code: Courier New

Toate din Google Fonts

---

Gândite și realizate pentru Brașov și Covasna.
Rămâi informat, rămâi conectat.
