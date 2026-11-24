#!/usr/bin/env python3
"""
Corectează articolele deja publicate (data/processed/):
  - autorul "Andrei Varga" -> "Redacția KronPapir"
  - elimină semnătura "— Andrei Varga, editorialist KronPapir" din conținut
  - marchează ai_generated=True pentru editoriale și articolele procesate cu AI
    (nu atinge articolele colaboratorilor sau cele scrise manual din admin)

Rulare:
  python fix_bylines.py            # arată ce s-ar schimba
  python fix_bylines.py --apply    # aplică modificările (face backup .bak)
"""

import json
import re
import shutil
import sys
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent / "data" / "processed"
OLD_AUTHORS = {"Andrei Varga", "Andrei M.", "Andrei"}
NEW_AUTHOR = "Redacția KronPapir"
SIGNATURE_RX = re.compile(
    r"(<p>\s*(<em>|<i>|<strong>)?\s*)?[—–-]?\s*Andrei( Varga| M\.)?,?\s*(editorialist|redacția)[^<\n]*"
    r"((</em>|</i>|</strong>)?\s*</p>)?",
    re.IGNORECASE,
)


def fix(article: dict) -> list:
    changes = []
    if article.get("author") in OLD_AUTHORS:
        article["author"] = NEW_AUTHOR
        changes.append("autor")

    content = article.get("content") or ""
    new_content = SIGNATURE_RX.sub("", content).rstrip()
    if new_content != content.rstrip():
        article["content"] = new_content
        changes.append("semnătură")

    is_ai = article.get("is_editorial") or (article.get("processed") and not article.get("contributor_id"))
    if is_ai and not article.get("ai_generated"):
        article["ai_generated"] = True
        changes.append("ai_generated")
    return changes


def main():
    apply = "--apply" in sys.argv
    files = sorted(PROCESSED_DIR.glob("*.json"))
    touched = 0
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️  {f.name}: {e}")
            continue
        items = data if isinstance(data, list) else [data]
        changes = [c for item in items if isinstance(item, dict) for c in fix(item)]
        if not changes:
            continue
        touched += 1
        title = (items[0].get("title", "") if items and isinstance(items[0], dict) else "")[:60]
        print(f"{'✏️ ' if apply else '•'} {f.name}: {', '.join(sorted(set(changes)))} — {title}")
        if apply:
            shutil.copy2(f, f.with_suffix(".json.bak"))
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{touched}/{len(files)} fișiere {'modificate' if apply else 'de modificat (rulează cu --apply)'}")


if __name__ == "__main__":
    main()
