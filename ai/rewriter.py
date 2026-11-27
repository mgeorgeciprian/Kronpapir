"""
KronPapir - Article Rewriter with Claude AI
Rescrie articolele cu stil jurnalistic local și empatie
"""

import os
import json
import time
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

# Logging
logger = logging.getLogger("KronPapir.Rewriter")


# Scheme JSON: API-ul garantează un răspuns valid, inclusiv cu ghilimele în HTML
_TEXT = {"type": "string"}
_KEYWORDS = {"type": "array", "items": {"type": "string"}}
EDITORIAL_SCHEMA = {
    "type": "object",
    "properties": {"title": _TEXT, "seo_title": _TEXT, "content": _TEXT,
                   "meta_description": _TEXT, "slug": _TEXT, "keywords": _KEYWORDS},
    "required": ["title", "seo_title", "content", "meta_description", "slug", "keywords"],
    "additionalProperties": False,
}
ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {**EDITORIAL_SCHEMA["properties"], "category": _TEXT, "type": _TEXT},
    "required": EDITORIAL_SCHEMA["required"] + ["category", "type"],
    "additionalProperties": False,
}



EDITORIAL_SOURCE_CHARS = 3000
EDITORIAL_MIN_CHARS = 400  # știrile mai scurte (doar titlu și o frază) nu intră în editorial


def editorial_text(article):
    """Textul simplu al unei știri pentru editorial (fără HTML)."""
    import re as _re
    raw = article.get('content') or article.get('text') or article.get('original_text') or ''
    return _re.sub(r'\s+', ' ', _re.sub(r'<[^>]+>', ' ', raw)).strip()



def _record_cost(agent, model, message):
    """Trece costul apelului în registrul din data/costs/ (evidența; plafonul se verifică în _budget_ok)."""
    try:
        from ai import costs
        costs.record(agent, model, message.usage, datetime.now())
    except Exception as e:  # evidența costurilor nu are voie să oprească rescrierea
        logger.warning(f"Costul apelului nu s-a putut înregistra: {e}")


def _budget_ok(agent, model):
    """Plafonul lunar din config/agents.yaml: la 80% alertă pentru George, la 100% nu mai apelăm API-ul."""
    from ai import costs
    try:
        return costs.allowed(agent, model)
    except Exception as e:  # o eroare a evidenței (fișier, config) nu oprește redacția; o vedem în log
        logger.warning(f"Plafonul nu s-a putut verifica: {e}")
        return True

class ArticleRewriter:
    """
    Rescrie articole folosind Claude AI cu stil de jurnalist local.

    Transformă articole brute în versiuni reescrise cu:
    - Stil jurnalistic empatic și personal
    - Titluri mai atractive
    - Categorizare automată
    - Determinare local/national
    - Rate limiting între API calls
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-5-5",
        rate_limit_delay: float = 1.0,
    ):
        """
        Inițializează rewriterul.

        Args:
            api_key: Anthropic API key. Dacă nu e dat, citește din env var ANTHROPIC_API_KEY
            model: Model Claude de folosit
            rate_limit_delay: Delay în secunde între API calls
        """
        self.model = model
        self.rate_limit_delay = rate_limit_delay
        self.last_api_call = 0

        # Caută API key din mediu
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")

            # Caută în .env dacă nu e în environ
            if not api_key:
                env_file = Path.home() / ".env"
                if env_file.exists():
                    try:
                        with open(env_file, 'r', encoding='utf-8') as f:
                            for line in f:
                                if line.startswith("ANTHROPIC_API_KEY="):
                                    api_key = line.split("=", 1)[1].strip()
                                    break
                    except Exception:
                        pass

        if not api_key:
            logger.warning("⚠️  ANTHROPIC_API_KEY nu e setat. Rewriterul va întoarce None.")
            self.client = None
            self.api_key = None
        else:
            self.api_key = api_key
            if Anthropic:
                self.client = Anthropic(api_key=api_key)
            else:
                logger.error("❌ Modulul 'anthropic' nu e instalat. Instalează: pip install anthropic")
                self.client = None

    @staticmethod
    def _truncate_at_sentence(text, max_len=200):
        """Truncate text at the first complete sentence within max_len."""
        import re as _re_trunc
        # Extract only <p> paragraph text, skip headings
        paragraphs = _re_trunc.findall(r'<p>(.*?)</p>', text, _re_trunc.DOTALL)
        if paragraphs:
            clean = ' '.join(_re_trunc.sub(r'<[^>]+>', '', p).strip() for p in paragraphs)
        else:
            clean = _re_trunc.sub(r'<[^>]+>', '', text).strip()
        if len(clean) <= max_len:
            return clean
        # Find first real sentence end: .!? followed by space/end, not a decimal in a number
        for match in _re_trunc.finditer(r'[.!?](?:\s|$)', clean):
            pos = match.start()
            # Skip decimal points between digits (e.g. "337.000")
            if clean[pos] == '.' and pos > 0 and clean[pos - 1].isdigit():
                continue
            if pos + 1 <= max_len and pos >= 40:
                return clean[:pos + 1]
        # No good sentence boundary — cut at last space
        truncated = clean[:max_len]
        last_space = truncated.rfind(' ')
        if last_space > 50:
            return truncated[:last_space] + '...'
        return truncated + '...'

    def _parse_json_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from AI response with repair logic for common issues."""
        # Strip markdown code fences
        text = response_text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()

        start_idx = text.find('{')
        end_idx = text.rfind('}') + 1

        if start_idx < 0 or end_idx <= start_idx:
            logger.error("❌ Nu e JSON în răspuns")
            return None

        json_str = text[start_idx:end_idx]

        # Try direct parse first
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Repair: fix unescaped quotes inside string values
        # Replace problematic characters and retry
        try:
            import re as _re_json
            # Fix unescaped newlines inside JSON string values
            repaired = json_str.replace('\n', '\\n')
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        logger.error(f"❌ JSON imposibil de reparat")
        logger.debug(f"Răspuns: {json_str[:300]}...")
        return None

    def _request_json(self, prompt: str, schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Cere lui Claude un JSON după schemă, cu o reîncercare. None dacă eșuează."""
        if not _budget_ok("jurnalist", self.model):
            return None
        for attempt in (1, 2):
            self._rate_limit()
            message = self.client.messages.create(
                model=self.model,
                max_tokens=16000,  # include și gândirea modelului (Sonnet 5.5 gândește implicit)
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}],
            )
            _record_cost("jurnalist", self.model, message)
            if message.stop_reason == "end_turn":
                text = next((b.text for b in message.content if b.type == "text"), "")
                result = self._parse_json_response(text)
                if result:
                    return result
            logger.warning(f"⚠️  Răspuns neutilizabil (încercarea {attempt}, stop: {message.stop_reason})")
        return None

    def _rate_limit(self):
        """Implementează rate limiting între API calls."""
        elapsed = time.time() - self.last_api_call
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_api_call = time.time()

    def _build_summary_prompt(self, article: Dict[str, Any]) -> str:
        """Rezumat scurt pentru știrile altor publicații (CLAUDE.md, regula 5): ~120 de cuvinte și link."""
        title = article.get('title', 'Fără titlu')
        content = article.get('content') or article.get('text') or article.get('original_text', '')
        source = article.get('source', 'Necunoscut')
        url = article.get('url', '')
        return f"""Scrii pentru Redacția KronPapir (kronpapir.ro), site de știri locale din Brașov. Nu semnezi cu un nume.

SARCINA: un REZUMAT SCURT al articolului publicat de {source}, cu link la articolul complet. Nu rescrii articolul: spui pe scurt ce s-a întâmplat și ce înseamnă pentru cititor, ca cine vrea detalii să meargă la sursă.

REGULI DE ADEVĂR (mai presus de orice):
- Folosești DOAR faptele din articolul sursă. Nu inventezi și nu adaugi nimic: nici cifre, nici nume, nici citate, nici context din cunoștințele tale.
- Orice număr din rezumat trebuie să apară în sursă. Fiecare rezumat trece printr-un fact-check automat care respinge orice cifră sau afirmație care nu e în sursă.
- Nu copia fraze întregi din sursă. Spune cu cuvintele tale.

STRUCTURA (HTML):
1. <p> Primul paragraf: ce, cine, când, unde, cu atribuirea „potrivit {source}” sau „scrie {source}”.
2. <p> Un paragraf cu detaliile esențiale (cel mult 3 fapte).
3. Doar dacă sursa spune concret ce are cititorul de făcut sau ce se schimbă pentru el (termen, adresă, program, restricție): <div class="local-impact"><h2>Ce înseamnă pentru tine</h2><p>…</p></div>. Altfel lași secțiunea afară.
4. <p class="sursa-completa">Citește articolul complet pe <a href="{url}" target="_blank" rel="noopener">{source}</a>.</p>

LUNGIME: 80–150 de cuvinte în total. Nu mai mult.

STIL: română corectă, cu ș și ț; fraze clare, fără clișee („în concluzie”, „este important de menționat”), fără clickbait, fără limbaj vulgar. Titlul spune exact ce s-a întâmplat.

ANUL CURENT: {datetime.now().year} (doar ca reper). Nu adăuga anul în titlu sau text dacă sursa nu îl spune.

SEO: title 50–60 de caractere; seo_title cu „| KronPapir.ro” la final; meta_description 140–160 de caractere; slug de 4–6 cuvinte fără diacritice; 4–6 cuvinte cheie.
CATEGORIE: una din local, national, politica, economie, cultura, sport, sanatate, social, mediu, tehnologie, accidente, evenimente.
TIP: "local" dacă e despre județul Brașov, altfel "national".

ARTICOL SURSĂ:
Titlu: {title}
Sursă: {source}
URL: {url}
Conținut: {content}

Returnează JSON cu: title, seo_title, content (HTML-ul de mai sus), meta_description, slug, keywords, category, type."""

    def _build_prompt(self, article: Dict[str, Any]) -> str:
        """
        Construiește promptul pentru Claude — conținut original cu valoare adăugată.

        Args:
            article: Articolul brut cu title, content, source, url, date, category

        Returns:
            Prompt complet pentru Claude
        """
        if article.get('source_kind') != 'oficial':
            prompt = self._build_summary_prompt(article)
        else:
            prompt = self._build_full_prompt(article)
        feedback = article.get('_factcheck_feedback')
        if feedback:
            prompt += ("\n\nCORECTURĂ CERUTĂ DE FACT-CHECK (încercarea anterioară a fost respinsă): "
                       + feedback + "\nScrie din nou textul fără aceste probleme.")
        return prompt

    def _build_full_prompt(self, article: Dict[str, Any]) -> str:
        """Articol complet: doar pentru sursele oficiale (comunicate, anunțuri ale instituțiilor)."""
        title = article.get('title', 'Fără titlu')
        content = article.get('content') or article.get('text') or article.get('original_text', '')
        source = article.get('source', 'Necunoscut')
        url = article.get('url', '')

        prompt = f"""Scrii pentru Redacția KronPapir (kronpapir.ro), ziarul online local al Brașovului. Nu ești o persoană anume și nu semnezi cu un nume.

REGULĂ DE ADEVĂR (mai presus de orice altă instrucțiune de mai jos): folosești DOAR faptele din articolul sursă. Nu inventezi cifre, nume, citate, scene, întâmplări sau experiențe personale. Dacă o informație nu e în sursă, nu o scrii.
CIFRELE: orice număr din articolul tău (sume, prețuri, distanțe, durate, procente, populații, ore, date) trebuie să apară în sursă. Nu estima și nu adăuga cifre „de context” din cunoștințele tale (de exemplu cât costă un aparat, câți kilometri are un ocol, câți locuitori are un oraș). Fiecare articol trece printr-un fact-check automat care respinge orice cifră care nu e în sursă. Valoarea adăugată vine din explicații practice și din ordinea clară a faptelor, nu din cifre noi. Nu calcula tu totaluri, sume, medii sau numărul elementelor dintr-o listă (de exemplu „22 de spații”, „peste 10 adrese”): dacă sursa nu dă totalul, scrie fără el („mai multe spații”).

MISIUNEA TA: Textul de mai jos e un comunicat sau un anunț oficial al unei instituții publice. Scrie un articol de știri care îl explică pe înțelesul brașovenilor: ce se întâmplă, unde, când, pe cine afectează și ce au de făcut. Nu copia formulările de comunicat și nu prelua tonul laudativ al instituției („municipalitatea se mândrește”); păstrează doar faptele. Atribuie clar sursa („anunță Primăria Brașov”).

PERSONALITATE:
- Scrii natural, nu ca un robot, cu observații sobre și argumentate din fapte
- Folosești expresii naturale ocazional: un "mă rog", "ce să zic", "hai că" — dar NU în deschidere și nu repetate. Sunt sare, nu mâncare.
- INTERZIS să începi articolul cu "Stai...", "Stai să...", "Stai că...", "Stai puțin", "Stai aşa", "Stai ață". Sună a clișeu de AI. Deschide cu un fapt, o scenă, o întrebare, un detaliu — orice altceva.
- Separi clar faptele (din sursă) de explicațiile pentru cititor
- NU folosești cuvinte de lemn: "în cadrul", "cu privire la", "totodată", "în acest context"
- NU începi cu "În ultimele zile..." sau "Recent, autoritățile..."
- Variezi lungimea propozițiilor. Unele scurte. Sec. Altele mai lungi.

REGISTRU ȘI LIMBAJ — INTERZIS limbaj vulgar, obscen sau argou grosolan:
- NICIODATĂ expresii vulgare, sexuale sau triviale (ex. "și-o freacă/frec", "se cacă pe", "băga-mi-aș", "se f*te") — nici măcar în glumă, ironic sau ca "umor ardelenesc". Sunt INTERZISE total.
- Umorul tău e fin și aluziv, NU trivial. Singurele "expresii naturale" permise sunt de tipul "mă rog", "ce să zic" — atât, nimic mai colorat de atât.
- NU stâlci expresii și zicale. Un antrenor concediat "i se arată ușa" / "este demis" / "pleacă de pe bancă" — scrie idiomul CORECT și complet. Folosește o expresie idiomatică DOAR dacă o știi exact; altfel scrie simplu și direct, fără să inventezi.
- Ton de ziar serios, publicabil oriunde și care poate fi citit cu voce tare fără jenă. Conținutul trebuie să rămână eligibil pentru Google AdSense — orice vulgaritate îl descalifică automat.

LIMBA ROMÂNĂ CORECTĂ — Ești absolvent de jurnalism, nu scrii cu greșeli:
- Acorduri gramaticale corecte: "sunt bani" NU "e bani", "sunt oameni" NU "e oameni", "există probleme" NU "e probleme". Subiect plural = verb la plural. ÎNTOTDEAUNA.
- Pronume reflexive corecte: "care își găsesc drumul" NU "care-i gsesc drum"
- Diacritice obligatorii: ă, â, î, ș, ț — mereu, fără excepție
- Virgula înainte de "care", "dar", "iar", "însă", "deși", "pentru că" — regulă de bază
- Articol hotărât corect: "economia locală" NU "economia local"
- Topică naturală românească: nu calchia structuri englezești
- Verifică fiecare propoziție: subiectul și predicatul trebuie să fie în acord (număr, gen)
- Scrii ca un profesionist cu facultate de jurnalism, nu ca un mesaj de pe Facebook

ANUL CURENT: {datetime.now().year} (doar ca reper pentru „astăzi”, „luna viitoare”). Nu adăuga anul în titlu, text sau slug dacă sursa nu îl spune.

STRUCTURA OBLIGATORIE A ARTICOLULUI (în HTML):

1. <div class="tldr"> — "Pe scurt" (3 bullet points cu esența știrii, max 15 cuvinte fiecare)

2. CORPUL ARTICOLULUI (rescris complet, cu perspectivă proprie):
   - Primul paragraf răspunde direct: ce, cine, când, cât, unde
   - Dezvoltă povestea cu context: de ce s-a ajuns aici, ce s-a întâmplat înainte
   - Explică ce înseamnă pentru cititor, doar pe baza faptelor din sursă
   - Structurează cu <h2> subtitluri naturale (nu "Secțiunea 1", ci titluri descriptive)

3. <div class="local-impact"> — "Ce înseamnă pentru tine": DOAR ce reiese direct din sursă (termene, restricții, program, unde te adresezi, cine e afectat). Fără aprecieri de tipul „strada e îndrăgită de turiști” dacă sursa nu le spune. Dacă sursa nu oferă nimic concret, lași secțiunea afară.

4. <div class="faq"> — "Întrebări frecvente": DOAR întrebări la care sursa are răspuns explicit (2-3). Dacă nu sunt, lași secțiunea afară.

LUNGIME: cât e nevoie ca să spui faptele din sursă clar, de obicei 250-500 de cuvinte. Nu lungi textul cu descrieri, aprecieri sau context care nu sunt în sursă: fact-check-ul respinge orice afirmație care nu e în comunicat.
TITLUL spune ce se întâmplă acum (de exemplu „Au început lucrările”), nu un rezultat viitor prezentat ca fapt.

OPTIMIZARE SEO:
- Titlu: 50-60 caractere, captivant, include context local dacă e cazul
- Primul paragraf conține cuvintele cheie principale natural
- Meta description: 150-160 caractere, rezumă și atrage click-uri
- Slug URL: 4-6 cuvinte, descriptiv, fără diacritice
- 4-6 cuvinte cheie SEO relevante
- seo_title: include "| KronPapir.ro" la final

CATEGORIZARE: Alege UNA din: local, national, politica, economie, cultura, sport, sanatate, social, mediu, tehnologie, accidente, evenimente
TIPUL: "local" dacă e legat de Brașov/județul Brașov, "national" dacă e interes general

GEOGRAFIE JUDEȚUL BRAȘOV — OBLIGATORIU de respectat, NU inventa informații despre localități:
- MUNICIPII: Brașov (reședință de județ), Săcele (al doilea oraș ca mărime), Făgăraș (centru industrial), Codlea
- ORAȘE: Râșnov (stațiune turistică lângă Bran), Zărnești (poarta Parcului Național Piatra Craiului), Predeal (stațiune montană la cea mai mare altitudine din România), Victoria (oraș industrial la poalele Munților Făgăraș), Rupea (cetate medievală), Ghimbav (zona industrială/aeroport)
- Săcele este MUNICIPIU, nu comună și nu sat. Are 4 cartiere istorice (Baciu, Gârcini, Cernatu, Turcheș) și Electroprecizia ca zonă industrială.
- OBIECTIVE TURISTICE — localizare corectă:
  * Canionul 7 Scări se află pe teritoriul municipiului SĂCELE (nu Zărnești!), în Munții Piatra Mare
  * Parcul Național Piatra Craiului — accesibil din Zărnești
  * Cetatea Râșnov — în Râșnov
  * Castelul Bran — în Bran (comuna Bran)
  * Poiana Brașov — stațiune aparținând municipiului Brașov
  * Tâmpa — munte în interiorul municipiului Brașov
- Sfântu Gheorghe, Covasna, Întorsura Buzăului sunt în JUDEȚUL COVASNA, nu Brașov
- REGULĂ: Dacă nu ești sigur de statutul sau detaliile unei localități, NU inventa. Menționeaz-o doar pe nume fără a-i atribui un statut administrativ greșit.

ARTICOL SURSĂ (folosește ca material, NU copia):
Titlu: {title}
Sursă: {source}
URL: {url}
Conținut: {content}

IMPORTANT:
- Finalizează complet fiecare propoziție. Conținutul trebuie să fie complet și coerent.
- Conținutul din "content" trebuie să fie HTML valid cu <p>, <h2>, <ul>, <div> — NU markdown.
- Secțiunile tldr, local-impact și faq sunt <div> cu clase CSS, conținând <h2> și <p>/<ul> în interior.

Returnează DOAR un obiect JSON valid (fără markdown, fără ```):
{{
  "title": "Titlul optimizat SEO (50-60 caractere)",
  "seo_title": "Titlu descriptiv | Categorie | KronPapir.ro",
  "content": "Conținutul complet al articolului în HTML cu toate cele 4 secțiuni",
  "meta_description": "Descriere SEO de 150-160 caractere",
  "slug": "slug-url-fara-diacritice",
  "keywords": ["cuvânt1", "cuvânt2", "cuvânt3", "cuvânt4", "cuvânt5"],
  "category": "categoria_aleasă",
  "type": "local sau national"
}}"""

        return prompt

    def rewrite_article(self, raw_article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Rescrie un articol brut folosind Claude.

        Args:
            raw_article: Dict cu title, content, source, url, date, category

        Returns:
            Dict cu articolul procesat sau None dacă API falează
        """
        if not self.client:
            logger.warning("❌ Client Anthropic nu e disponibil. Returnez None.")
            return None

        if not raw_article.get('content') and not raw_article.get('text'):
            logger.warning(f"⚠️  Articol fără conținut: {raw_article.get('title', 'Necunoscut')}")
            return None

        try:
            # Rate limiting
            self._rate_limit()

            # Build prompt
            prompt = self._build_prompt(raw_article)

            # Call Claude
            logger.debug(f"📝 Rescript articol: {raw_article.get('title', 'Necunoscut')[:50]}...")

            rewritten = self._request_json(prompt, ARTICLE_SCHEMA)
            if rewritten is None:
                logger.error(f"❌ JSON invalid după retry pentru: {raw_article.get('title', 'Necunoscut')[:50]}")
                return None

            # Validează câmpuri obligatorii
            required_fields = ['title', 'content', 'category', 'type', 'seo_title', 'meta_description', 'slug', 'keywords']
            for field in required_fields:
                if field not in rewritten or not rewritten[field]:
                    logger.error(f"❌ Câmp lipsă în răspuns: {field}")
                    return None

            # Generează excerpt dacă nu e (primele ~200 caractere din conținut)
            if not rewritten.get('excerpt'):
                rewritten['excerpt'] = self._truncate_at_sentence(rewritten['content'], 200)

            # Validează lungimea meta_description (trebuie să fie 150-160 caractere)
            meta_desc = rewritten.get('meta_description', '')
            if len(meta_desc) < 150 or len(meta_desc) > 160:
                logger.warning(f"⚠️  meta_description nu e în intervalul 150-160 caractere ({len(meta_desc)}), dar e acceptat")

            # Convertește markdown în HTML dacă AI-ul a returnat markdown
            import re as _re
            content = rewritten['content']
            if '##' in content or '\n\n' in content:
                # Convert ## headers to <h2>
                content = _re.sub(r'^### (.+)$', r'<h3>\1</h3>', content, flags=_re.MULTILINE)
                content = _re.sub(r'^## (.+)$', r'<h2>\1</h2>', content, flags=_re.MULTILINE)
                # Wrap remaining plain text paragraphs in <p> tags
                lines = content.split('\n')
                result_lines = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('<h') or line.startswith('<p') or line.startswith('<ul') or line.startswith('<ol') or line.startswith('<li') or line.startswith('<block'):
                        result_lines.append(line)
                    else:
                        result_lines.append(f'<p>{line}</p>')
                content = '\n'.join(result_lines)
            rewritten['content'] = content

            # Also clean excerpt of any HTML/markdown
            excerpt = rewritten.get('excerpt', rewritten['content'][:250])
            excerpt = _re.sub(r'<[^>]+>', '', excerpt) if '<' in excerpt else excerpt
            excerpt = excerpt.replace('## ', '').replace('### ', '')
            rewritten['excerpt'] = self._truncate_at_sentence(excerpt, 200)

            # Construiește articolul final cu SEO fields
            processed_article = {
                'id': str(uuid.uuid4()),
                'title': rewritten['title'],
                'seo_title': rewritten['seo_title'],
                'content': rewritten['content'],
                'excerpt': rewritten['excerpt'],
                'meta_description': rewritten['meta_description'],
                'slug': rewritten['slug'],
                'keywords': rewritten['keywords'],
                'category': rewritten['category'].lower(),
                'type': rewritten['type'].lower(),
                'source': raw_article.get('source', 'Necunoscut'),
                'source_title': raw_article.get('title', ''),
                'format': 'articol' if raw_article.get('source_kind') == 'oficial' else 'rezumat',
                'url': raw_article.get('url', ''),
                'image': raw_article.get('image_url') or raw_article.get('image', ''),
                'date': raw_article.get('date') or raw_article.get('published') or datetime.now().isoformat(),
                'author': 'Redacția KronPapir',
                'processed': True,
            }

            # Fallback 1: extract og:image from original HTML
            if not processed_article['image']:
                try:
                    from bs4 import BeautifulSoup as _BS
                    orig_html = raw_article.get('original_text', '')
                    if orig_html and '<' in orig_html:
                        _soup = _BS(orig_html, 'html.parser')
                        og = _soup.find('meta', property='og:image')
                        if og and og.get('content', '').strip():
                            processed_article['image'] = og['content'].strip()
                except Exception:
                    pass

            # Fallback 2: Pixabay search
            if not processed_article['image']:
                try:
                    from utils.pixabay import get_article_image
                    processed_article['image'] = get_article_image(
                        processed_article['title'], processed_article['category']
                    )
                except Exception as e:
                    logger.debug(f"Pixabay fallback failed: {e}")

            logger.info(f"✅ Rescris: {processed_article['title'][:50]}... [{processed_article['category']}]")
            return processed_article

        except Exception as e:
            logger.error(f"❌ Eroare la rescrierea articolului: {e}")
            return None

    @staticmethod
    def _get_editorial_image(editorial_type):
        """Get a Pixabay image for an editorial based on its type."""
        try:
            from utils.pixabay import search_pixabay
            search_map = {
                "national": "Romania parliament Bucharest",
                "international": "world globe Europe",
            }
            query = search_map.get(editorial_type, "newspaper journalism editorial")
            return search_pixabay(query)
        except Exception:
            return ""

    def write_editorial(self, articles: list, editorial_type: str = "national") -> Optional[Dict[str, Any]]:
        """
        Scrie un editorial zilnic care compilează mai multe știri într-un singur articol de analiză.

        Args:
            articles: Lista de articole brute de compilat
            editorial_type: "national" sau "international"

        Returns:
            Dict cu editorialul procesat sau None dacă API falează
        """
        if not self.client:
            logger.warning("❌ Client Anthropic nu e disponibil.")
            return None

        if not articles:
            logger.warning("⚠️  Nu sunt articole pentru editorial.")
            return None
        articles = [a for a in articles if len(editorial_text(a)) >= EDITORIAL_MIN_CHARS]
        if len(articles) < 3:
            logger.warning(f"⚠️  Doar {len(articles)} știri cu text suficient; nu scriu editorialul.")
            return None

        # Construiesc rezumatul știrilor pentru prompt
        stiri_text = ""
        sources_list = []
        sources_detail = []
        for i, art in enumerate(articles, 1):
            title = art.get('title', 'Fără titlu')
            content = editorial_text(art)[:EDITORIAL_SOURCE_CHARS]
            source = art.get('source', 'Necunoscut')
            stiri_text += f"\n--- Știrea {i} ---\nTitlu: {title}\nSursă: {source}\nLink: {art.get('url', '')}\nConținut: {content}\n"
            sources_list.append(source)
            sources_detail.append({'source': source, 'title': title, 'url': art.get('url', '')})

        type_label = "naționale" if editorial_type == "national" else "europene și internaționale"
        type_cat = "national" if editorial_type == "national" else "international"

        prompt = f"""Ești editorialistul-șef al portalului de știri KronPapir.ro din Brașov.

MISIUNEA TA: Scrie un EDITORIAL ZILNIC care compilează și analizează cele mai importante știri {type_label} ale zilei. NU copia textele originale — scrie un articol original de analiză.

ADEVĂRUL ÎNAINTE DE TOATE (regula care nu se negociază):
- Fiecare fapt (nume, funcție, cifră, dată, loc, citat, eveniment) trebuie să fie în textele știrilor de mai jos. Nu adăuga nimic din memorie, nici „context” pe care știrile nu îl dau.
- Funcțiile oamenilor le scrii exact cum apar în știri. Dacă o știre nu spune funcția cuiva, nu o scrie.
- O acuzație rămâne acuzație („X susține că…”), nu o prezinți ca fapt.
- Opinia și interpretarea sunt permise doar formulate clar ca opinie („pare că”, „rămâne de văzut”), fără fapte noi.
- Nu inventa legături cu Brașovul. Pomenești Brașovul doar dacă o știre vorbește despre el.
- Dacă o știre are prea puțin text ca să spui ceva sigur, o lași deoparte.

STIL:
- Analiză scurtă, nu doar rezumat: legi știrile între ele doar unde legătura e reală
- Ton profesional dar accesibil, fără clișee și fără superlative goale

LIMBA ROMÂNĂ CORECTĂ — ai facultate de jurnalism, nu scrii cu greșeli:
- Acorduri gramaticale corecte: "sunt bani" NU "e bani", "sunt oameni" NU "e oameni", "există probleme" NU "e probleme". Subiect plural = verb la plural. ÎNTOTDEAUNA.
- Pronume reflexive și forme verbale corecte: "care își găsesc drumul" NU "care-i găsesc drum"
- Diacritice obligatorii: ă, â, î, ș, ț — mereu, fără excepție
- Virgula înainte de "care", "dar", "iar", "însă", "deși", "pentru că" — regulă de bază
- Articol hotărât corect: "economia locală" NU "economia local"
- Topică naturală românească: nu calchia structuri englezești
- Verifică fiecare propoziție: subiectul și predicatul trebuie să fie în acord (număr, gen, persoană)

STRUCTURĂ:
- Titlu editorial captivant (60-70 caractere)
- Paragraf introductiv cu cele mai importante 2-3 știri
- Secțiuni <h2> pentru fiecare știre majoră cu analiză scurtă
- Paragraf final cu perspectivă de ansamblu
- Lungime: 350-600 cuvinte; mai scurt e mai bine decât umplut cu fapte nesigure

SEO:
- Meta description: 150-160 caractere
- Slug URL descriptiv fără diacritice
- 3-5 cuvinte cheie SEO

ȘTIRILE ZILEI ({len(articles)} știri {type_label}):
{stiri_text}

Returnează DOAR un obiect JSON valid (fără markdown, fără ```):
{{
  "title": "Titlul editorialului (60-70 caractere)",
  "seo_title": "Titlu SEO | Editorial {type_label.title()} | KronPapir.ro",
  "content": "Conținutul complet al editorialului in HTML cu <h2> subtitluri și <p> paragrafe",
  "meta_description": "Descriere SEO 150-160 caractere",
  "slug": "editorial-{type_cat}-data",
  "keywords": ["cuvânt1", "cuvânt2", "cuvânt3"]
}}"""

        try:
            rewritten = self._request_json(prompt, EDITORIAL_SCHEMA)
            if rewritten is None:
                logger.error("❌ Editorial fără JSON valid după retry")
                return None

            # Construiesc editorialul final
            today = datetime.now().strftime("%Y-%m-%d")
            editorial = {
                'id': str(uuid.uuid4()),
                'title': rewritten.get('title', f'Editorial {type_label} - {today}'),
                'seo_title': rewritten.get('seo_title', ''),
                'content': rewritten.get('content', ''),
                'excerpt': self._truncate_at_sentence(rewritten.get('content', ''), 200),
                'meta_description': rewritten.get('meta_description', ''),
                'slug': rewritten.get('slug', f'editorial-{type_cat}-{today}'),
                'keywords': rewritten.get('keywords', []),
                'category': 'editorial',
                'type': type_cat,
                'source': 'KronPapir Editorial',
                'url': f'https://kronpapir.ro/stiri/editorial-{type_cat}-{today}',
                'image': self._get_editorial_image(type_cat),
                'date': datetime.now().isoformat(),
                'author': 'Redacția KronPapir',
                'processed': True,
                'is_editorial': True,
                'sources_used': list(set(sources_list)),
                'sources': sources_detail,
                '_inputs': list(articles),  # pentru fact-check; nu se salvează
            }

            logger.info(f"✅ Editorial {type_label}: {editorial['title'][:50]}...")
            return editorial

        except Exception as e:
            logger.error(f"❌ Eroare la scrierea editorialului: {e}")
            return None
