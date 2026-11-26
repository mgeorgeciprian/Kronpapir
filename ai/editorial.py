"""
KronPapir - Agent Editorial Dedicat
Scrie editoriale zilnice: național, internațional, tematic

Editorialele Redacției KronPapir — voce analitică, perspectivă locală,
conectează evenimentele mari la viața brașovenilor.
"""

import os
import json
import time
import uuid
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

logger = logging.getLogger("KronPapir.Editorial")

# Editoriale tematice pe zile
TEME_ZILNICE = {
    0: {"tema": "Retrospectiva weekendului", "focus": "Ce s-a întâmplat în weekend în Brașov și în țară — evenimente, incidente, decizii", "slug_prefix": "retrospectiva-weekend"},
    1: {"tema": "Cultură & Educație", "focus": "Evenimente culturale, educație, școli, universități, festivaluri, artă din Brașov și România", "slug_prefix": "editorial-cultura"},
    2: {"tema": "Politică & Administrație", "focus": "Decizii politice, consilii locale, primării, guvern — ce afectează direct comunitățile din Brașov", "slug_prefix": "editorial-politic"},
    3: {"tema": "Tehnologie & Inovație", "focus": "IT, startup-uri, digitalizare, inovație în Brașov și România, industria tech locală", "slug_prefix": "editorial-tehnologie"},
    4: {"tema": "Economie & Finanțe", "focus": "Piață, investiții, prețuri, afaceri locale, economia Brașovului, curs valutar, inflație", "slug_prefix": "editorial-financiar"},
    5: {"tema": "Social & Comunitate", "focus": "Viața comunității, ONG-uri, voluntariat, probleme sociale, sănătate, mediu în Brașov", "slug_prefix": "editorial-social"},
    6: {"tema": "Retrospectiva săptămânii", "focus": "Cele mai importante 7-10 evenimente ale săptămânii — ce a contat și ce urmează", "slug_prefix": "retrospectiva-saptamana"},
}

# Personalitatea editorialistului
from ai.rewriter import EDITORIAL_MIN_CHARS, EDITORIAL_SOURCE_CHARS, editorial_text  # noqa: E402

MIN_EDITORIAL_STORIES = 3
TRUTH_RULES = """ADEVĂRUL ÎNAINTE DE TOATE (regula care nu se negociază):
- Fiecare fapt (nume, funcție, cifră, dată, loc, citat, eveniment) trebuie să fie în textele știrilor de mai jos. Nu adăuga nimic din memorie, nici „context istoric” pe care știrile nu îl dau.
- Funcțiile oamenilor le scrii exact cum apar în știri; dacă nu apar, nu le scrii.
- O acuzație rămâne acuzație („X susține că…”), nu o prezinți ca fapt.
- Opinia e permisă doar formulată clar ca opinie, fără fapte noi.
- Nu inventa legături cu Brașovul: îl pomenești doar dacă o știre vorbește despre el.
- Dacă o știre are prea puțin text ca să spui ceva sigur, o lași deoparte."""

EDITORIAL_PERSONA = """Scrii editorialele Redacției KronPapir (kronpapir.ro), ziarul online local al Brașovului.
Nu ești o persoană anume și nu semnezi cu un nume: editorialul apare cu semnătura redacției.

REGULI DE ADEVĂR:
- Folosești doar faptele din știrile primite. Nu inventezi cifre, nume, citate, întâmplări sau experiențe personale.
- Opiniile sunt argumentate din faptele primite și se formulează ca opinii, nu ca fapte.
- Analizezi echilibrat, fără partizanat; conectezi știrile mari cu impactul lor asupra vieții din Brașov doar acolo unde legătura reiese din fapte.

STILUL TĂU:
- Deschizi cu un paragraf puternic care captează atenția
- Analizezi, nu doar rezumi — oferi CONTEXT și PERSPECTIVĂ
- Conectezi știrile între ele pentru a arăta imaginea de ansamblu
- Închei mereu cu o reflecție sau o întrebare care lasă cititorul să gândească
- Ton: profesional dar cald, accesibil dar inteligent
- NU folosești clișee jurnalistice ("rămâne de văzut", "timpul va decide")
- Nu adaugi nicio semnătură la final; semnătura o pune sistemul.

LIMBA ROMÂNĂ CORECTĂ — ai facultate de jurnalism, nu scrii cu greșeli:
- Acorduri gramaticale corecte: "sunt bani" NU "e bani", "sunt oameni" NU "e oameni", "există probleme" NU "e probleme". Subiect plural = verb la plural. ÎNTOTDEAUNA.
- Pronume reflexive și forme verbale corecte: "care își găsesc drumul" NU "care-i găsesc drum"
- Diacritice obligatorii: ă, â, î, ș, ț — mereu, fără excepție
- Virgula înainte de "care", "dar", "iar", "însă", "deși", "pentru că" — regulă de bază
- Articol hotărât corect: "economia locală" NU "economia local"
- Topică naturală românească: nu calchia structuri englezești
- Verifică fiecare propoziție: subiectul și predicatul trebuie să fie în acord (număr, gen, persoană)
"""


# Schema JSON: API-ul garantează un răspuns valid, inclusiv cu ghilimele în HTML
EDITORIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "seo_title": {"type": "string"},
        "content": {"type": "string"},
        "meta_description": {"type": "string"},
        "slug": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "seo_title", "content", "meta_description", "slug", "keywords"],
    "additionalProperties": False,
}


class EditorialAgent:
    """
    Agent editorial dedicat care scrie editoriale zilnice.
    Trei tipuri: național, internațional, tematic (variază pe zi).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-5-5",
        rate_limit_delay: float = 1.5,
    ):
        self.model = model
        self.rate_limit_delay = rate_limit_delay
        self.last_api_call = 0

        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:
            logger.warning("⚠️ ANTHROPIC_API_KEY nu e setat.")
            self.client = None
        elif Anthropic:
            self.client = Anthropic(api_key=api_key)
        else:
            logger.error("❌ Modulul 'anthropic' nu e instalat.")
            self.client = None

    def _rate_limit(self):
        elapsed = time.time() - self.last_api_call
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_api_call = time.time()

    def _call_claude(self, prompt: str, max_tokens: int = 16000) -> Optional[Dict]:
        """Apelează Claude cu schema JSON, cu o reîncercare; returnează JSON parsat."""
        if not self.client:
            return None

        try:
            for attempt in (1, 2):
                self._rate_limit()
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    output_config={"format": {"type": "json_schema", "schema": EDITORIAL_SCHEMA}},
                    messages=[{"role": "user", "content": prompt}]
                )
                if message.stop_reason == "end_turn":
                    text = next((b.text for b in message.content if b.type == "text"), "")
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError as e:
                        logger.error(f"❌ JSON invalid: {e}")
                logger.warning(f"⚠️ Răspuns neutilizabil (încercarea {attempt}, stop: {message.stop_reason})")
            return None

        except Exception as e:
            logger.error(f"❌ Eroare API: {e}")
            return None

    def _format_stiri(self, articles: List[Dict]) -> str:
        """Formatează lista de știri pentru prompt (text simplu, până la EDITORIAL_SOURCE_CHARS pe știre)."""
        text = ""
        self._last_inputs = list(articles)
        for i, art in enumerate(articles, 1):
            title = art.get('title', 'Fără titlu')
            content = editorial_text(art)[:EDITORIAL_SOURCE_CHARS]
            source = art.get('source', 'Necunoscut')
            text += f"\n--- Știrea {i} ---\nTitlu: {title}\nSursă: {source}\nLink: {art.get('url', '')}\nConținut: {content}\n"
        return text

    @staticmethod
    def _usable(articles: List[Dict], limit: int) -> List[Dict]:
        """Doar știrile cu text suficient: din titlu și o frază modelul ar inventa restul."""
        return [a for a in articles if len(editorial_text(a)) >= EDITORIAL_MIN_CHARS][:limit]

    @staticmethod
    def _markdown_to_html(text: str) -> str:
        """Convert markdown-formatted content to HTML if needed."""
        import re
        # Already HTML
        if '<p>' in text or '<h2>' in text:
            return text
        lines = text.split('\n')
        html_parts = []
        paragraph = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if paragraph:
                    html_parts.append('<p>' + ' '.join(paragraph) + '</p>')
                    paragraph = []
                continue
            # ## headings -> <h2>
            h2_match = re.match(r'^##\s+(.+)$', stripped)
            if h2_match:
                if paragraph:
                    html_parts.append('<p>' + ' '.join(paragraph) + '</p>')
                    paragraph = []
                html_parts.append(f'<h2>{h2_match.group(1)}</h2>')
                continue
            # # headings -> <h2> (skip h1 since title is separate)
            h1_match = re.match(r'^#\s+(.+)$', stripped)
            if h1_match:
                if paragraph:
                    html_parts.append('<p>' + ' '.join(paragraph) + '</p>')
                    paragraph = []
                html_parts.append(f'<h2>{h1_match.group(1)}</h2>')
                continue
            # **bold** -> <strong>
            stripped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
            # *italic* -> <em>
            stripped = re.sub(r'\*(.+?)\*', r'<em>\1</em>', stripped)
            paragraph.append(stripped)
        if paragraph:
            html_parts.append('<p>' + ' '.join(paragraph) + '</p>')
        return '\n'.join(html_parts)

    def _build_editorial(self, result: Dict, editorial_type: str, sources: List[str]) -> Dict:
        """Construiește articolul editorial final."""
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        type_map = {
            "national": "national",
            "international": "international",
            "tematic": "editorial",
        }

        content = self._markdown_to_html(result.get('content', ''))

        # Build proper excerpt from content
        import re
        paragraphs = re.findall(r'<p>(.*?)</p>', content, re.DOTALL)
        if paragraphs:
            clean = ' '.join(re.sub(r'<[^>]+>', '', p).strip() for p in paragraphs)
        else:
            clean = re.sub(r'<[^>]+>', '', content).strip()
        excerpt = clean[:200]
        # Cut at last sentence or space
        for match in re.finditer(r'[.!?](?:\s|$)', excerpt):
            pos = match.start()
            if pos >= 40:
                excerpt = excerpt[:pos + 1]
                break
        else:
            last_sp = excerpt.rfind(' ')
            if last_sp > 50:
                excerpt = excerpt[:last_sp] + '...'

        return {
            'id': str(uuid.uuid4()),
            'title': result.get('title', f'Editorial {editorial_type} - {today}'),
            'seo_title': result.get('seo_title', ''),
            'content': content,
            'excerpt': excerpt,
            'meta_description': result.get('meta_description', ''),
            'slug': result.get('slug', f'editorial-{editorial_type}-{today}'),
            'keywords': result.get('keywords', []),
            'category': 'editorial',
            'type': type_map.get(editorial_type, 'local'),
            'source': 'KronPapir Editorial',
            'url': f"https://kronpapir.ro/stiri/{result.get('slug', f'editorial-{today}')}",
            'image': '',
            'date': datetime.now().isoformat(),
            'publish_date': tomorrow,
            'author': 'Redacția KronPapir',
            'processed': True,
            'is_editorial': True,
            'editorial_type': editorial_type,
            'sources_used': list(set(sources)),
            'sources': [{'source': x.get('source', ''), 'title': x.get('title', ''), 'url': x.get('url', '')}
                        for x in getattr(self, '_last_inputs', [])],
            '_inputs': list(getattr(self, '_last_inputs', [])),  # pentru fact-check; nu se salvează
        }

    def write_national(self, articles: List[Dict]) -> Optional[Dict]:
        """Scrie editorialul național zilnic."""
        if not articles:
            logger.warning("⚠️ Nu sunt știri naționale pentru editorial.")
            return None

        articles = self._usable(articles, 5)
        if len(articles) < MIN_EDITORIAL_STORIES:
            logger.warning(f"⚠️ Doar {len(articles)} știri cu text suficient; nu scriu editorialul.")
            return None
        stiri = self._format_stiri(articles)
        sources = [a.get('source', '') for a in articles]

        prompt = f"""{EDITORIAL_PERSONA}

MISIUNEA TA ACUM: Scrie EDITORIALUL NAȚIONAL al zilei pentru KronPapir.ro.

INSTRUCȚIUNI:
- Compilează și analizează cele mai importante știri NAȚIONALE ale zilei
{TRUTH_RULES}
- Explică de ce contează, doar cu ce spun știrile
- Leagă știrile între ele doar unde legătura e reală
- Lungime: 350-600 cuvinte
- Structura: intro puternica → sectiuni cu subtitluri <h2> pe teme → concluzie cu perspectiva
- IMPORTANT: Scrie continutul in HTML cu tag-uri <h2> pentru subtitluri si <p> pentru paragrafe. NU folosi Markdown.

SEO:
- Titlu: 55-65 caractere, captivant, cu "România" sau subiectul principal
- Meta description: 150-160 caractere
- Slug: descriptiv, fără diacritice, cu "editorial-national"
- 3-5 cuvinte cheie

ȘTIRILE NAȚIONALE ALE ZILEI ({len(articles[:5])} știri):
{stiri}

Nu adăuga semnătură la final.

Returnează DOAR JSON valid (fără markdown, fără ```):
{{
  "title": "Titlul editorialului (55-65 caractere)",
  "seo_title": "Titlu | Editorial Național | KronPapir.ro",
  "content": "Conținutul complet in HTML cu <h2> subtitluri si <p> paragrafe. Semneaza la final.",
  "meta_description": "Descriere SEO 150-160 caractere",
  "slug": "editorial-national-descriere",
  "keywords": ["cuvânt1", "cuvânt2", "cuvânt3"]
}}"""

        result = self._call_claude(prompt)
        if result:
            editorial = self._build_editorial(result, "national", sources)
            logger.info(f"✅ Editorial național: {editorial['title'][:50]}...")
            return editorial
        return None

    def write_international(self, articles: List[Dict]) -> Optional[Dict]:
        """Scrie editorialul internațional zilnic."""
        if not articles:
            logger.warning("⚠️ Nu sunt știri internaționale pentru editorial.")
            return None

        articles = self._usable(articles, 5)
        if len(articles) < MIN_EDITORIAL_STORIES:
            logger.warning(f"⚠️ Doar {len(articles)} știri cu text suficient; nu scriu editorialul.")
            return None
        stiri = self._format_stiri(articles)
        sources = [a.get('source', '') for a in articles]

        prompt = f"""{EDITORIAL_PERSONA}

MISIUNEA TA ACUM: Scrie EDITORIALUL INTERNAȚIONAL & EUROPEAN al zilei pentru KronPapir.ro.

INSTRUCȚIUNI:
- Compilează cele mai importante știri din Europa și din lume
{TRUTH_RULES}
- Spune ce înseamnă pentru România doar dacă știrile o spun; altfel rămâi la ce s-a întâmplat
- Lungime: 350-600 cuvinte
- Structura: intro cu cele 2-3 stiri majore → sectiuni cu <h2> subtitluri → perspectiva ta
- IMPORTANT: Scrie continutul in HTML cu tag-uri <h2> si <p>. NU folosi Markdown.

SEO:
- Titlu: 55-65 caractere, cu "Europa" / "mondial" / subiectul principal
- Meta description: 150-160 caractere
- Slug: cu "radar-european" sau "editorial-international"
- 3-5 cuvinte cheie

ȘTIRILE INTERNAȚIONALE ALE ZILEI ({len(articles[:5])} știri):
{stiri}

Nu adăuga semnătură la final.

Returnează DOAR JSON valid:
{{
  "title": "Titlul editorialului (55-65 caractere)",
  "seo_title": "Titlu | Radar European | KronPapir.ro",
  "content": "Conținutul complet in HTML cu <h2> subtitluri si <p> paragrafe. Semneaza la final.",
  "meta_description": "Descriere SEO 150-160 caractere",
  "slug": "radar-european-descriere",
  "keywords": ["cuvânt1", "cuvânt2", "cuvânt3"]
}}"""

        result = self._call_claude(prompt)
        if result:
            editorial = self._build_editorial(result, "international", sources)
            logger.info(f"✅ Editorial internațional: {editorial['title'][:50]}...")
            return editorial
        return None

    def write_tematic(self, articles: List[Dict], day_of_week: Optional[int] = None) -> Optional[Dict]:
        """Scrie editorialul tematic al zilei (variază pe zi a săptămânii)."""
        if day_of_week is None:
            day_of_week = datetime.now().weekday()

        tema_info = TEME_ZILNICE.get(day_of_week, TEME_ZILNICE[0])
        tema = tema_info["tema"]
        focus = tema_info["focus"]
        slug_prefix = tema_info["slug_prefix"]

        if not articles:
            logger.warning(f"⚠️ Nu sunt știri pentru editorialul tematic: {tema}")
            return None

        articles = self._usable(articles, 7)
        if len(articles) < MIN_EDITORIAL_STORIES:
            logger.warning(f"⚠️ Doar {len(articles)} știri cu text suficient; nu scriu editorialul tematic.")
            return None
        stiri = self._format_stiri(articles)
        sources = [a.get('source', '') for a in articles]

        zile_ro = ['Luni', 'Marți', 'Miercuri', 'Joi', 'Vineri', 'Sâmbătă', 'Duminică']
        zi_ro = zile_ro[day_of_week]

        prompt = f"""{EDITORIAL_PERSONA}

MISIUNEA TA ACUM: Scrie EDITORIALUL TEMATIC DE {zi_ro.upper()} pentru KronPapir.ro.

TEMA ZILEI: {tema}
FOCUSUL: {focus}

INSTRUCȚIUNI:
- Scrie un editorial analitic pe tema "{tema}"
{TRUTH_RULES}
- Folosește doar faptele din știrile de mai jos; analiza ta e opinie, formulată ca opinie
- Fii mai personal decât la editoriale, dar fără fapte noi
- Dacă e retrospectivă (luni/duminică), fă un rezumat cronologic al evenimentelor
- Lungime: 400-700 cuvinte
- Structura: intro tematica → sectiuni cu <h2> subtitluri → concluzie reflexiva
- IMPORTANT: Scrie continutul in HTML cu tag-uri <h2> si <p>. NU folosi Markdown.

SEO:
- Titlu: 55-70 caractere, include tema "{tema}" sau cuvinte cheie relevante
- Meta description: 150-160 caractere
- Slug: începe cu "{slug_prefix}"
- 3-5 cuvinte cheie relevante temei

ȘTIRI RELEVANTE PENTRU TEMĂ ({len(articles[:7])} știri):
{stiri}

Nu adăuga semnătură la final.

Returnează DOAR JSON valid:
{{
  "title": "Titlul editorialului tematic (55-70 caractere)",
  "seo_title": "Titlu | {tema} | KronPapir.ro",
  "content": "Conținutul complet in HTML cu <h2> subtitluri si <p> paragrafe. Semneaza la final.",
  "meta_description": "Descriere SEO 150-160 caractere",
  "slug": "{slug_prefix}-descriere",
  "keywords": ["cuvânt1", "cuvânt2", "cuvânt3"]
}}"""

        result = self._call_claude(prompt)
        if result:
            editorial = self._build_editorial(result, "tematic", sources)
            editorial['editorial_tema'] = tema
            editorial['editorial_zi'] = zi_ro
            logger.info(f"✅ Editorial tematic ({zi_ro} — {tema}): {editorial['title'][:50]}...")
            return editorial
        return None

    def run_all_editorials(self, national_articles: List[Dict],
                           intl_articles: List[Dict],
                           all_articles: List[Dict]) -> Dict:
        """
        Rulează toate editorialele pentru seară.
        Returnează dict cu rezultatele.
        """
        results = {
            "national": None,
            "international": None,
            "tematic": None,
            "total_written": 0,
        }

        # 1. Editorial Național
        logger.info("📰 Scriu editorialul NAȚIONAL...")
        editorial = self.write_national(national_articles)
        if editorial:
            results["national"] = editorial
            results["total_written"] += 1

        # 2. Editorial Internațional
        logger.info("🌍 Scriu editorialul INTERNAȚIONAL...")
        editorial = self.write_international(intl_articles)
        if editorial:
            results["international"] = editorial
            results["total_written"] += 1

        # 3. Editorial Tematic (bazat pe ziua săptămânii)
        day = datetime.now().weekday()
        tema = TEME_ZILNICE[day]["tema"]
        logger.info(f"📝 Scriu editorialul TEMATIC: {tema}...")
        editorial = self.write_tematic(all_articles)
        if editorial:
            results["tematic"] = editorial
            results["total_written"] += 1

        logger.info(f"✅ Editoriale finalizate: {results['total_written']}/3 scrise")
        return results
