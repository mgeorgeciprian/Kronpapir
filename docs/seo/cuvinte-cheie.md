# Harta cuvintelor cheie (28.11.2026)

O căutare = o pagină. Cuvântul cheie stă în `<title>`, în H1 și în prima frază. Nu facem două pagini pentru aceeași căutare (s-ar concura între ele).

| Căutare țintă | Pagina | Unde e cuvântul |
|---|---|---|
| știri Brașov, știri Brașov azi | `/` | title, H1 (sr-only), description |
| știri locale Brașov | `/local` | title, H1, description |
| locuri de muncă Brașov, angajări Brașov | `/locuri-de-munca-brasov` | title, H1 |
| locuri de muncă Făgăraș / Săcele / Ghimbav / Bran / Șercaia … | `/locuri-de-munca-brasov/<localitate>` | title, H1, intro |
| locuri de muncă fără experiență Brașov | `/locuri-de-munca-brasov/fara-experienta` | title, H1, intro |
| muncitor necalificat Brașov | `/locuri-de-munca-brasov/muncitor-necalificat` | idem |
| angajări șofer Brașov | `/locuri-de-munca-brasov/sofer` | idem |
| locuri de muncă construcții / producție / turism / medical / pază / vânzări / ingineri / part-time Brașov | `/locuri-de-munca-brasov/<tip>` | idem |
| firme noi Brașov, afaceri Brașov, ONRC Brașov | `/afaceri-brasov` | title, H1, description |
| licitații Brașov, achiziții primării Brașov | `/afaceri-brasov/licitatii` | title, H1 |
| licitații <localitate> | `/afaceri-brasov/licitatii/<slug>` (indexat de la 3 anunțuri) | title, H1 |
| HCL Brașov, hotărâri Consiliul Local Brașov | `/afaceri-brasov/primaria-brasov` | title, H1, description |

Reguli pentru paginile de joburi (`web/job_topics.py`):
- index și sitemap doar de la 5 oferte active (`MIN_INDEX`); sub prag pagina rămâne, cu `noindex`;
- municipiul Brașov nu are pagină separată: ar concura cu `/locuri-de-munca-brasov`;
- textul de introducere se calculează din oferte (număr, posturi, salariu median de la 3 salarii brute, angajatori); nu se scrie nimic ce nu e în date;
- un tip nou de job se adaugă în `TOPICS`, cu test în `tests/test_job_topics.py`.
