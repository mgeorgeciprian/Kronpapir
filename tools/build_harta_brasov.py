"""Construiește harta UAT-urilor din județul Brașov pentru pagina de licitații.

Sursa: geoBoundaries ROU ADM1 (județe) și ADM2 (UAT-uri, date ANCPI), licență CC BY 4.0,
https://www.geoboundaries.org. Fișierele GeoJSON se descarcă manual și se dau ca argumente;
scriptul nu face cereri în rețea. Rezultatul, data/geo/harta_brasov.json, se pune în git.

Păstrăm UAT-urile al căror punct interior cade în poligonul județului Brașov, proiectăm
coordonatele (echirectangular, corectat cu cos(latitudine)), simplificăm conturul
(Douglas-Peucker) și scriem un path SVG pentru fiecare.

Rulare: python -m tools.build_harta_brasov ADM1.geojson ADM2.geojson
"""
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "geo" / "harta_brasov.json"
WIDTH = 600
TOLERANCE = 0.9  # în pixeli SVG
SOURCE = {
    "name": "geoBoundaries ROU ADM2 (ANCPI)",
    "url": "https://www.geoboundaries.org",
    "license": "CC BY 4.0",
}


def slug(name):
    t = unicodedata.normalize("NFKD", name)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def in_ring(pt, ring):
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def in_geom(pt, geom):
    return any(in_ring(pt, poly[0]) and not any(in_ring(pt, h) for h in poly[1:]) for poly in polygons(geom))


def interior_point(geom):
    """Un punct sigur în interior: mijlocul celui mai lung segment orizontal prin centrul de greutate."""
    poly = max(polygons(geom), key=lambda p: len(p[0]))
    ring = poly[0]
    ys = sorted(p[1] for p in ring)
    y = (ys[0] + ys[-1]) / 2
    xs = []
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y):
            xs.append((x2 - x1) * (y - y1) / (y2 - y1) + x1)
    xs.sort()
    best = max(((xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)), key=lambda s: s[1] - s[0])
    return ((best[0] + best[1]) / 2, y)


def simplify_ring(pts, tol):
    """Inel închis: îl tăiem în două la punctul cel mai depărtat de primul, apoi Douglas-Peucker pe fiecare."""
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 4:
        return pts
    far = max(range(len(pts)), key=lambda i: math.dist(pts[0], pts[i]))
    a = simplify(pts[:far + 1], tol)
    b = simplify(pts[far:] + [pts[0]], tol)
    return a[:-1] + b[:-1]


def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, idx = 0.0, None
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def build(adm1_path, adm2_path, county="Brasov"):
    adm1 = json.loads(Path(adm1_path).read_text(encoding="utf-8"))
    county_geom = next(f["geometry"] for f in adm1["features"] if f["properties"]["shapeName"] == county)
    adm2 = json.loads(Path(adm2_path).read_text(encoding="utf-8"))
    feats = [f for f in adm2["features"] if in_geom(interior_point(f["geometry"]), county_geom)]

    allpts = [pt for f in feats for poly in polygons(f["geometry"]) for pt in poly[0]]
    lon0 = min(p[0] for p in allpts)
    lat1 = max(p[1] for p in allpts)
    k = math.cos(math.radians(sum(p[1] for p in allpts) / len(allpts)))
    span_x = (max(p[0] for p in allpts) - lon0) * k
    span_y = lat1 - min(p[1] for p in allpts)
    scale = WIDTH / span_x
    height = round(span_y * scale)

    def proj(p):
        return ((p[0] - lon0) * k * scale, (lat1 - p[1]) * scale)

    # Un UAT cu exclave (ex. Rupea) vine în mai multe bucăți: le unim, eticheta stă pe cea mai mare.
    merged = {}
    for f in feats:
        name = f["properties"]["shapeName"]
        g = merged.setdefault(name, {"type": "MultiPolygon", "coordinates": []})
        g["coordinates"] += polygons(f["geometry"])
    feats = [{"properties": {"shapeName": n}, "geometry": g} for n, g in merged.items()]

    out = []
    for f in feats:
        parts = []
        for poly in polygons(f["geometry"]):
            for ring in poly:
                pts = simplify_ring([proj(p) for p in ring], TOLERANCE)
                if len(pts) >= 3:
                    parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        lx, ly = proj(interior_point(f["geometry"]))
        name = f["properties"]["shapeName"]
        out.append({"slug": slug(name), "name": name, "d": "".join(parts), "label": [round(lx, 1), round(ly, 1)]})
    out.sort(key=lambda u: u["slug"])
    return {"width": WIDTH, "height": height, "source": SOURCE, "uat": out}


def main(argv):
    data = build(argv[0], argv[1])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(data['uat'])} UAT-uri, {OUT.stat().st_size // 1024} KB -> {OUT}")
    print(", ".join(u["name"] for u in data["uat"]))


if __name__ == "__main__":
    main(sys.argv[1:])
