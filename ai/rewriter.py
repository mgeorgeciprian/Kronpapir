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
        model: str = "claude-sonnet-4-5-20250929",
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

        # Last resort: extract fields manually with regex
        try:
            import re as _re_json
            fields = {}
            for key in ['title', 'seo_title', 'content', 'meta_description', 'slug', 'category', 'type']:
                match = _re_json.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', json_str, _re_json.DOTALL)
                if match:
                    fields[key] = match.group(1).replace('\\n', '\n').replace('\\"', '"')
            kw_match = _re_json.search(r'"keywords"\s*:\s*\[(.*?)\]', json_str, _re_json.DOTALL)
            if kw_match:
                fields['keywords'] = _re_json.findall(r'"([^"]*)"', kw_match.group(1))
            if fields.get('title') and fields.get('content'):
                logger.warning("⚠️  JSON reparat cu regex extraction")
                return fields
        except Exception:
            pass

        logger.error(f"❌ JSON imposibil de reparat")
        logger.debug(f"Răspuns: {json_str[:300]}...")
        return None

    def _rate_limit(self):
        """Implementează rate limiting între API calls."""
        elapsed = time.time() - self.last_api_call
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_api_call = time.time()

    def _build_prompt(self, article: Dict[str, Any]) -> str:
        """
        Construiește promptul pentru Claude — conținut original cu valoare adăugată.

        Args:
            article: Articolul brut cu title, content, source, url, date, category

        Returns:
            Prompt complet pentru Claude
        """
        title = article.get('title', 'Fără titlu')
        content = article.get('content') or article.get('text') or article.get('original_text', '')
        source = article.get('source', 'Necunoscut')
        url = article.get('url', '')

        prompt = f"""Ești Andrei, jurnalist local în Brașov de 12 ani, care scrie pentru KronPapir.ro. Ai lucrat la Gazeta de Transilvania, cunoști orașul și comunitatea.

MISIUNEA TA: Folosind informația din articolul de mai jos ca punct de plecare, scrie un ARTICOL EDITORIAL ORIGINAL. Nu parafraza — creează conținut nou cu perspectivă, analiză și valoare adăugată pentru cititorii din Brașov.

PERSONALITATE:
- Scrii ca un om, nu ca un robot. Ai opinii, observații, umor uscat ardelenesc
- Folosești expresii naturale ocazional: un "mă rog", "ce să zic", "hai că" — dar NU în deschidere și nu repetate. Sunt sare, nu mâncare.
- INTERZIS să începi articolul cu "Stai...", "Stai să...", "Stai că...", "Stai puțin", "Stai aşa", "Stai ață". Sună a clișeu de AI. Deschide cu un fapt, o scenă, o întrebare, un detaliu — orice altceva.
- Alternezi între informație factuală și comentariu personal
- NU folosești cuvinte de lemn: "în cadrul", "cu privire la", "totodată", "în acest context"
- NU începi cu "În ultimele zile..." sau "Recent, autoritățile..."
- Variezi lungimea propozițiilor. Unele scurte. Sec. Altele mai lungi.

STRUCTURA OBLIGATORIE A ARTICOLULUI (în HTML):

1. <div class="tldr"> — "Pe scurt" (3 bullet points cu esența știrii, max 15 cuvinte fiecare)

2. CORPUL ARTICOLULUI (rescris complet, cu perspectivă proprie):
   - Primul paragraf: un unghi uman, o scenă, o întrebare — NU începe cu fapte seci
   - Dezvoltă povestea cu context: de ce s-a ajuns aici, ce s-a întâmplat înainte
   - Adaugă perspectivă personală: "Dacă treci pe acolo dimineața...", "Oricine a stat la coadă la X știe că..."
   - Structurează cu <h2> subtitluri naturale (nu "Secțiunea 1", ci titluri descriptive)

3. <div class="local-impact"> — "De ce contează pentru Brașov" (sau pentru România, dacă e știre națională):
   - 2-3 paragrafe cu impact concret, local, pentru cititori
   - Conectează știrea cu realitatea zilnică din Brașov/România
   - Adaugă context pe care doar un local îl știe

4. <div class="faq"> — "Întrebări frecvente" (2-3 întrebări + răspunsuri scurte):
   - Întrebări pe care un cititor normal le-ar pune
   - Răspunsuri concrete, 2-3 propoziții fiecare
   - Schema FAQ ajută SEO

LUNGIME TOTALĂ: 600-900 cuvinte (articol substanțial, nu rezumat)

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
- MUNICIPII: Brașov (circa 250.000 loc., reședință de județ), Săcele (circa 36.000 loc., al doilea oraș ca mărime), Făgăraș (circa 30.000 loc., centru industrial), Codlea (circa 25.000 loc.)
- ORAȘE: Râșnov (circa 17.000 loc., stațiune turistică lângă Bran), Zărnești (circa 23.000 loc., poarta Parcului Național Piatra Craiului), Predeal (circa 5.000 loc., stațiune montană la cea mai mare altitudine din România), Victoria (circa 7.000 loc., oraș industrial la poalele Munților Făgăraș), Rupea (circa 5.500 loc., cetate medievală), Ghimbav (circa 8.000 loc., zona industrială/aeroport)
- Săcele este MUNICIPIU, nu comună și nu sat. Are 4 cartiere istorice (Baciu, Gârcini, Cernatu, Turcheș) și Electroprecizia ca zonă industrială.
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

            message = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            # Parse response
            response_text = message.content[0].text.strip()

            # Extrage JSON din răspuns cu repair logic
            rewritten = self._parse_json_response(response_text)
            if rewritten is None:
                # Retry once — AI models are non-deterministic
                logger.warning("⚠️  Prima încercare eșuată, reîncerc...")
                self._rate_limit()
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}]
                )
                response_text = message.content[0].text.strip()
                rewritten = self._parse_json_response(response_text)
                if rewritten is None:
                    logger.error(f"❌ JSON invalid după retry pentru: {raw_article.get('title', 'Necunoscut')}")
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

        # Construiesc rezumatul știrilor pentru prompt
        stiri_text = ""
        sources_list = []
        for i, art in enumerate(articles, 1):
            title = art.get('title', 'Fără titlu')
            content = (art.get('content') or art.get('text') or '')[:500]
            source = art.get('source', 'Necunoscut')
            stiri_text += f"\n--- Știrea {i} ---\nTitlu: {title}\nSursă: {source}\nConținut: {content}\n"
            sources_list.append(source)

        type_label = "naționale" if editorial_type == "national" else "europene și internaționale"
        type_cat = "national" if editorial_type == "national" else "international"

        prompt = f"""Ești editorialistul-șef al portalului de știri KronPapir.ro din Brașov.

MISIUNEA TA: Scrie un EDITORIAL ZILNIC care compilează și analizează cele mai importante știri {type_label} ale zilei. NU copia textele originale — scrie un articol original de analiză.

STIL:
- Stil editorial de analiză — nu doar rezumat, ci și context și perspectivă
- Conectează știrile între ele unde e posibil
- Adaugă perspectiva locală (cum afectează Brașovul/România)
- Ton profesional dar accesibil, cu personalitate
- Fii obiectiv dar oferă context critic

STRUCTURĂ:
- Titlu editorial captivant (60-70 caractere)
- Paragraf introductiv cu cele mai importante 2-3 știri
- Secțiuni <h2> pentru fiecare știre majoră cu analiză scurtă
- Paragraf final cu perspectivă de ansamblu
- Lungime totală: 600-900 cuvinte

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
            self._rate_limit()

            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            # Parse JSON
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1

            if start_idx < 0 or end_idx <= start_idx:
                logger.error("❌ Nu e JSON în răspunsul editorial")
                return None

            rewritten = json.loads(response_text[start_idx:end_idx])

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
            }

            logger.info(f"✅ Editorial {type_label}: {editorial['title'][:50]}...")
            return editorial

        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON invalid în editorial: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Eroare la scrierea editorialului: {e}")
            return None
