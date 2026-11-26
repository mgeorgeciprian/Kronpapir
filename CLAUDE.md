# KronPapir: reguli pentru Claude Code și pentru agenții redacției

KronPapir (https://kronpapir.ro) este ziarul online local al Brașovului. Misiunea: sursa numărul 1 de informații utile pentru brașoveni (joburi, cursuri, licitații, avarii, decizii ale primăriei, evenimente), corectă, rapidă, ușor de găsit pe Google și sustenabilă financiar.

Editor și proprietar: George. El aprobă strategia, schimbările mari și tot ce ține de bani și conturi.

## Proiectul
- Python 3.12 și Flask (`web/app.py`), servite cu gunicorn prin supervisor (`kronpapir_web`), în spatele nginx.
- Producția rulează din `/home/kronpapir/app`, ca userul `kronpapir`. Nu lucra direct acolo: lucrează pe un branch într-o clonă separată.
- Articolele sunt fișiere JSON în `data/processed/<id>.json` (sau `.json.gz` după arhivare). Nu există bază de date.
- Job-urile rulează din crontab-ul userului `kronpapir`: pipeline la 06:00 și 14:00, editoriale la 22:00, Facebook la 07:00, 12:00, 15:00 și 19:00, arhivare la 03:30, audit SEO duminica la 04:30.
- Agenții sunt descriși în `.claude/agents/*.md`. Job-urile Python citesc prompturile din aceleași fișiere. Modelele și plafoanele de cost sunt în `config/agents.yaml`.

## Reguli editoriale (obligatorii pentru toți agenții)
1. **Adevăr înainte de viteză.** Folosește numai date din surse verificabile, cu link. Nu inventa cifre, nume, citate, persoane sau personaje. Datele lipsă rămân `null`.
2. **O greșeală publicată se corectează vizibil,** cu mențiunea „Actualizare: …” și cu `dateModified` actualizat.
3. **Publicarea:**
   - automat: doar articolele de date (joburi, cursuri, avarii, licitații), după fact-check cu scor ≥ 8;
   - draft pentru George: editorialele, subiectele sensibile (politică, accidente, persoane private, sănătate) și tot ce are scor sub 8;
   - editorialele și subiectele sensibile nu se publică niciodată fără aprobarea lui George.
4. **Semnăturile:**
   - articol verificat de George: „Scris de Redacția AI KronPapir, cu verificare umană”;
   - articol de date publicat automat: „Generat automat de Redacția AI KronPapir din date oficiale. Sursa: <link>”;
   - eticheta „cu verificare umană” apare doar dacă articolul are `reviewed_by` și `reviewed_at`. Când George verifică un articol automat, se schimbă eticheta și se actualizează `dateModified`.
5. **Conținut preluat:** din alte publicații se ia doar un rezumat scurt, cu valoare adăugată și link la sursă. Nu se rescriu integral articolele altora. Pozele lor nu se folosesc (nici prin hotlink).
6. **Etica și legea:** fără date personale ale persoanelor private; respectarea drepturilor de autor; conținutul sponsorizat se marchează „Publicitate” sau „Conținut sponsorizat”; politica editorială publică explică folosirea AI în redacție.
7. **Nu se trimite, nu se postează și nu se cheltuie nimic** (mesaje, postări, conturi, bani) fără aprobarea lui George.

## Stil
Scrie ca un jurnalism local bun:
- deschiderea răspunde direct la ce, cine, când, cât și unde;
- fraze de lungimi variate, vocabular concret, nume de străzi și cartiere;
- explică de ce contează și ce are cititorul de făcut;
- fără clișee („în concluzie”, „este important de menționat”, „în era digitală”), superlative goale sau clickbait;
- română corectă, cu diacritice cu virgulă (ș, ț).

## Reguli tehnice
- Lucrează pe branch-uri noi, cu commit-uri mici. Nu face push pe `main` și nu deploya fără confirmarea lui George.
- Secretele stau doar în `.env`, niciodată în git sau în loguri.
- Scrie teste pentru scrapere, fact-check și validare (`tests/`, pytest).
- Logurile din `logs/` au rotație prin logrotate (`deploy/logrotate-kronpapir`). În cod se folosesc handler-e simple de fișier: rotația o face sistemul, fiindcă mai multe procese scriu în aceleași fișiere.
- Fiecare job are timeout și retry și apare în scheduler.
- Scraperele respectă `robots.txt` și termenii site-ului, fac maximum o cerere la 2 secunde, folosesc un User-Agent identificabil și cache. Preferă API, RSS sau date deschise.
- Costuri: fiecare agent are un plafon lunar în `config/agents.yaml`. Peste 80% din plafon îl alertezi pe George; la 100% agentul se oprește.
- Modele: Opus (`claude-opus-5-5`) pentru editoriale și decizii editoriale, Sonnet (`claude-sonnet-5-5`) pentru redactare de rutină și extracție. Nu folosi ID-uri vechi.
