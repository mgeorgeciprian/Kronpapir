"""Grafice SVG generate pe server pentru paginile de date (fără JavaScript, fără biblioteci).

Fiecare grafic:
- are `viewBox` fix (nu mișcă pagina la încărcare: CLS 0);
- are role="img", <title> și <desc> cu cifrele principale, pentru cititoarele de ecran și pentru Google;
- folosește clase CSS (culorile vin din tema site-ului, merg și pe modul întunecat);
- e însoțit în template de un tabel cu aceleași cifre.
"""
from markupsafe import Markup, escape

MONTHS_SHORT = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec"]


def _num(n):
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else f"{n:,.1f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _nice_max(v):
    """Un plafon „rotund” pentru axă: 187 -> 200, 1.430 -> 1.500."""
    if v <= 0:
        return 1
    mag = 10 ** (len(str(int(v))) - 1)
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= step * mag:
            return int(step * mag)
    return int(10 * mag)


def _ticks(vmax):
    """În câte părți împărțim axa ca liniile să cadă pe numere rotunde (600 -> 3 × 200, 500 -> 5 × 100)."""
    def nice(step):
        if step != int(step) or step <= 0:
            return False
        mag = 10 ** (len(str(int(step))) - 1)
        return step / mag in (1, 2, 2.5, 5)
    for n in (4, 5, 3, 2):
        if nice(vmax / n):
            return n
    return 4


def month_label(ym):
    """'2026-03' -> 'mar 26'."""
    return f"{MONTHS_SHORT[int(ym[5:7]) - 1]} {ym[2:4]}"


def monthly_bars(points, title, desc, width=640, height=220, unit=""):
    """Bare verticale pe luni. points: [(„AAAA-LL”, valoare)], cronologic. Ultima lună e evidențiată."""
    points = [(m, v) for m, v in points if v is not None]
    if not points:
        return Markup("")
    left, right, top, bottom = 44, 8, 14, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    vmax = _nice_max(max(v for _, v in points))
    slot = plot_w / len(points)
    bar = max(4.0, slot * 0.68)
    out = [f'<svg class="kp-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
           f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>"]
    parts = _ticks(vmax)
    for i in range(parts + 1):
        val = vmax * i / parts
        y = top + plot_h - plot_h * i / parts
        out.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="axis" x="{left - 6}" y="{y + 3:.1f}" text-anchor="end">{_num(int(round(val)))}</text>')
    every = 1 if len(points) <= 12 else 2
    for i, (m, v) in enumerate(points):
        h = plot_h * v / vmax
        x = left + i * slot + (slot - bar) / 2
        last = i == len(points) - 1
        out.append(f'<rect class="bar{" now" if last else ""}" x="{x:.1f}" y="{top + plot_h - h:.1f}" '
                   f'width="{bar:.1f}" height="{h:.1f}"><title>{escape(month_label(m))}: {_num(v)}{unit}</title></rect>')
        if last:
            out.append(f'<text class="val" x="{x + bar / 2:.1f}" y="{top + plot_h - h - 4:.1f}" text-anchor="middle">{_num(v)}</text>')
        if (len(points) - 1 - i) % every == 0:  # numărăm de la ultima lună, care are mereu etichetă
            out.append(f'<text class="axis" x="{x + bar / 2:.1f}" y="{height - 10}" text-anchor="middle">{escape(month_label(m))}</text>')
    out.append("</svg>")
    return Markup("".join(out))


def hbars(items, title, desc, width=640, label_w=170, row=26, fmt=None):
    """Bare orizontale. items: [(etichetă, valoare, evidențiat)]. Valorile pozitive."""
    items = [it for it in items if it[1] is not None]
    if not items:
        return Markup("")
    fmt = fmt or _num
    height = row * len(items) + 6
    vmax = max(v for _, v, _ in items) or 1
    plot_w = width - label_w - 70
    out = [f'<svg class="kp-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
           f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>"]
    for i, (label, v, hi) in enumerate(items):
        y = 3 + i * row
        w = max(2.0, plot_w * v / vmax)
        cls = "bar now" if hi else "bar"
        out.append(f'<text class="lab{" hi" if hi else ""}" x="{label_w - 8}" y="{y + row * 0.62:.1f}" text-anchor="end">{escape(label)}</text>')
        out.append(f'<rect class="{cls}" x="{label_w}" y="{y + 4}" width="{w:.1f}" height="{row - 10}" rx="2"/>')
        out.append(f'<text class="val" x="{label_w + w + 6:.1f}" y="{y + row * 0.62:.1f}">{escape(fmt(v))}</text>')
    out.append("</svg>")
    return Markup("".join(out))


def diverging(items, title, desc, series=("Brașov", "România"), width=640, label_w=150, row=44):
    """Variații procentuale pereche (județ vs țară), centrate pe zero.

    items: [(etichetă, variație_județ, variație_țară)]. Bara e marcată ▲/▼ în text, nu doar prin culoare.
    """
    items = [it for it in items if it[1] is not None or it[2] is not None]
    if not items:
        return Markup("")
    height = row * len(items) + 28
    vals = [abs(v) for _, a, b in items for v in (a, b) if v is not None]
    vmax = max(vals + [1.0])
    room = 64  # loc pentru eticheta „▲ +37,4%” la capătul barei, de fiecare parte
    half = (width - label_w - 2 * room) / 2
    zero = label_w + room + half
    out = [f'<svg class="kp-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
           f"<title>{escape(title)}</title><desc>{escape(desc)}</desc>",
           f'<rect class="bar now" x="{label_w}" y="4" width="10" height="10"/><text class="axis" x="{label_w + 14}" y="13">{escape(series[0])}</text>',
           f'<rect class="bar alt" x="{label_w + 90}" y="4" width="10" height="10"/><text class="axis" x="{label_w + 104}" y="13">{escape(series[1])}</text>',
           f'<line class="zero" x1="{zero:.1f}" x2="{zero:.1f}" y1="22" y2="{height - 2}"/>']
    for i, (label, a, b) in enumerate(items):
        y = 24 + i * row
        out.append(f'<text class="lab" x="{label_w - 8}" y="{y + row / 2 + 3:.1f}" text-anchor="end">{escape(label)}</text>')
        for j, (v, cls) in enumerate(((a, "bar now"), (b, "bar alt"))):
            if v is None:
                continue
            w = max(1.5, half * abs(v) / vmax)
            x = zero if v >= 0 else zero - w
            yy = y + 6 + j * 16
            out.append(f'<rect class="{cls}" x="{x:.1f}" y="{yy}" width="{w:.1f}" height="13" rx="2"/>')
            txt = ("▲ +" if v > 0 else "▼ −" if v < 0 else "") + f"{abs(v):.1f}".replace(".", ",") + "%"
            tx = x + w + 5 if v >= 0 else x - 5
            anchor = "start" if v >= 0 else "end"
            out.append(f'<text class="val" x="{tx:.1f}" y="{yy + 10}" text-anchor="{anchor}">{txt}</text>')
    out.append("</svg>")
    return Markup("".join(out))
