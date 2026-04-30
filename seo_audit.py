#!/usr/bin/env python3
"""
SEO Audit — scanează articolele procesate și raportează probleme SEO.

Utilizare:
    python seo_audit.py              # Audit complet
    python seo_audit.py --limit 50   # Doar ultimele 50 articole
"""

import json
import sys
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent / 'data' / 'processed'

# Praguri
TITLE_MIN = 30
TITLE_MAX = 60
META_DESC_MIN = 50
META_DESC_MAX = 160


def audit_article(article):
    """Returnează o listă de probleme SEO pentru un articol."""
    issues = []
    title = article.get('title', '')
    meta_desc = article.get('meta_description', '')
    slug = article.get('slug', '')
    image = article.get('image', '')
    keywords = article.get('keywords', [])

    # Titlu
    if not title:
        issues.append(('CRITIC', 'Titlu lipsă'))
    elif len(title) < TITLE_MIN:
        issues.append(('WARN', f'Titlu prea scurt ({len(title)} chars, min {TITLE_MIN})'))
    elif len(title) > TITLE_MAX:
        issues.append(('WARN', f'Titlu prea lung ({len(title)} chars, max {TITLE_MAX})'))

    # Meta description
    if not meta_desc:
        issues.append(('WARN', 'Meta description lipsă'))
    elif len(meta_desc) < META_DESC_MIN:
        issues.append(('WARN', f'Meta description prea scurtă ({len(meta_desc)} chars, min {META_DESC_MIN})'))
    elif len(meta_desc) > META_DESC_MAX:
        issues.append(('WARN', f'Meta description prea lungă ({len(meta_desc)} chars, max {META_DESC_MAX})'))

    # Slug
    if not slug:
        issues.append(('WARN', 'Slug lipsă'))

    # Imagine
    if not image:
        issues.append(('WARN', 'Imagine lipsă'))

    # Keywords
    if not keywords:
        issues.append(('WARN', 'Keywords lipsă'))

    return issues


def seo_score(article):
    """Calculează un scor SEO 0-100."""
    score = 100
    penalties = {
        'Titlu lipsă': 30,
        'Meta description lipsă': 20,
        'Slug lipsă': 15,
        'Imagine lipsă': 15,
        'Keywords lipsă': 10,
    }
    issues = audit_article(article)
    for level, msg in issues:
        if level == 'CRITIC':
            score -= 30
        else:
            for key, penalty in penalties.items():
                if key in msg:
                    score -= penalty
                    break
            else:
                score -= 5
    return max(0, score)


def run_audit(limit=None):
    """Rulează auditul SEO pe toate articolele procesate."""
    if not PROCESSED_DIR.exists():
        print(f"Directorul {PROCESSED_DIR} nu există.")
        return

    files = sorted(PROCESSED_DIR.glob('*.json'), key=lambda f: f.stat().st_mtime, reverse=True)
    if limit:
        files = files[:limit]

    total = len(files)
    total_issues = 0
    total_score = 0
    problematic = []

    stats = {
        'titlu_scurt': 0,
        'titlu_lung': 0,
        'meta_desc_lipsa': 0,
        'imagine_lipsa': 0,
        'slug_lipsa': 0,
        'keywords_lipsa': 0,
    }

    for f in files:
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                article = json.load(fh)
        except Exception:
            continue

        issues = audit_article(article)
        score = seo_score(article)
        total_score += score

        if issues:
            total_issues += len(issues)
            problematic.append((article.get('title', f.name)[:60], score, issues))

        # Contorizare statistici
        for _, msg in issues:
            if 'prea scurt' in msg and 'Titlu' in msg:
                stats['titlu_scurt'] += 1
            elif 'prea lung' in msg and 'Titlu' in msg:
                stats['titlu_lung'] += 1
            elif 'Meta description lipsă' in msg:
                stats['meta_desc_lipsa'] += 1
            elif 'Imagine lipsă' in msg:
                stats['imagine_lipsa'] += 1
            elif 'Slug lipsă' in msg:
                stats['slug_lipsa'] += 1
            elif 'Keywords lipsă' in msg:
                stats['keywords_lipsa'] += 1

    avg_score = total_score / total if total else 0

    # Raport
    print("=" * 60)
    print("📊 SEO AUDIT — KronPapir.ro")
    print("=" * 60)
    print(f"Articole scanate: {total}")
    print(f"Scor SEO mediu:   {avg_score:.0f}/100")
    print(f"Probleme totale:  {total_issues}")
    print()
    print("📋 Statistici:")
    print(f"  Titluri prea scurte (<{TITLE_MIN} chars): {stats['titlu_scurt']}")
    print(f"  Titluri prea lungi  (>{TITLE_MAX} chars): {stats['titlu_lung']}")
    print(f"  Meta description lipsă:                   {stats['meta_desc_lipsa']}")
    print(f"  Imagine lipsă:                            {stats['imagine_lipsa']}")
    print(f"  Slug lipsă:                               {stats['slug_lipsa']}")
    print(f"  Keywords lipsă:                           {stats['keywords_lipsa']}")

    if problematic:
        print()
        print("⚠️  Top articole cu probleme:")
        problematic.sort(key=lambda x: x[1])
        for title, score, issues in problematic[:15]:
            print(f"\n  [{score}/100] {title}")
            for level, msg in issues:
                marker = '❌' if level == 'CRITIC' else '⚠️'
                print(f"    {marker} {msg}")

    print()
    print("=" * 60)
    return avg_score


if __name__ == '__main__':
    limit_arg = None
    if '--limit' in sys.argv:
        idx = sys.argv.index('--limit')
        if idx + 1 < len(sys.argv):
            limit_arg = int(sys.argv[idx + 1])
    run_audit(limit=limit_arg)
