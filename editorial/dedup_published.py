"""Dublurile deja publicate: aceeași știre din două surse, apărută pe site de două ori.

Nu ștergem nimic (paginile pot fi deja indexate). Din fiecare grup păstrăm un articol, iar
celelalte primesc `duplicate_of`: pagina lor face 301 spre cel păstrat, dispar din liste și
sitemap, iar sursa lor apare la articolul păstrat („Au relatat și”).

Rulare: python -m editorial.dedup_published [--days 30] [--apply] [--skip id1,id2]
Fără --apply doar afișează grupurile.
"""
import argparse
import itertools
import json
import logging
import sys
from datetime import datetime

from editorial import dedup
from editorial import store as editorial_store

log = logging.getLogger("editorial.dedup_published")


def _length(a):
    return len(dedup._plain(a.get("content") or ""))


def keeper(group):
    """Primul publicat, cu excepția cazului în care un articol de mai târziu e mult mai complet."""
    by_date = sorted(group, key=lambda a: (a.get("date") or "", a.get("id") or ""))
    first = by_date[0]
    longest = max(group, key=_length)
    return longest if _length(longest) > 1.5 * max(_length(first), 1) else first


def clusters(articles, threshold=None):
    threshold = dedup.SURE if threshold is None else threshold
    arts = [a for a in articles if not a.get("duplicate_of")]
    fps = [dedup.fingerprint(a) for a in arts]
    parent = list(range(len(arts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    scores = {}
    for i, j in itertools.combinations(range(len(arts)), 2):
        s = dedup.similarity(fps[i], fps[j])
        if s >= threshold:
            parent[find(i)] = find(j)
            scores[(i, j)] = s
    groups = {}
    for i in range(len(arts)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in groups.values():
        if len(members) > 1:
            best = max((scores.get((min(a, b), max(a, b)), 0) for a, b in itertools.combinations(members, 2)))
            out.append(([arts[m] for m in members], best))
    return sorted(out, key=lambda g: -g[1])


def load_published():
    items = []
    for path in editorial_store.PROCESSED_DIR.glob("*.json"):
        try:
            a = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(a, dict) and a.get("id") and a.get("title"):
            items.append(a)
    return items


def mark(group, keep):
    now = datetime.now().isoformat(timespec="seconds")
    kept_path = editorial_store.PROCESSED_DIR / f"{keep['id']}.json"
    kept = json.loads(kept_path.read_text(encoding="utf-8"))
    for a in group:
        if a["id"] == keep["id"]:
            continue
        path = editorial_store.PROCESSED_DIR / f"{a['id']}.json"
        fresh = json.loads(path.read_text(encoding="utf-8"))
        fresh["duplicate_of"] = {"id": keep["id"], "slug": keep.get("slug"), "title": keep.get("title"),
                                 "marked_at": now}
        editorial_store._write_json_atomic(path, fresh)
        dedup.merge_source(kept, {"url": fresh.get("url"), "source": fresh.get("source"),
                                  "title": fresh.get("source_title") or fresh.get("title")})
    editorial_store._write_json_atomic(kept_path, kept)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--skip", default="", help="id-uri (sau începutul lor) de articole lăsate neatinse, separate prin virgulă")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    skip = {s for s in args.skip.split(",") if s}
    candidates = [a for a in dedup.recent(load_published(), days=args.days)
                  if not any(a["id"].startswith(s) for s in skip)]
    groups = clusters(candidates)
    for n, (group, score) in enumerate(groups, 1):
        keep = keeper(group)
        print(f"\n#{n} scor {score:.2f}")
        for a in sorted(group, key=lambda a: a.get("date") or ""):
            tag = "PĂSTRAT " if a is keep else "dublură "
            print(f"  {tag}{(a.get('date') or '')[:10]} {a.get('source', '?')[:14]:14} {_length(a):5} car. "
                  f"{a['id'][:8]} {a['title'][:70]}")
        if args.apply:
            mark(group, keep)
    print(f"\n{len(groups)} grupuri{' marcate' if args.apply else ' (probă, nimic modificat)'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
