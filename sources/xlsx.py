"""Cititor minimal de .xlsx (doar biblioteca standard): foi -> rânduri -> {coloană: text}.

ONRC publică fișiere .xls care sunt de fapt .xlsx (arhive zip). Nu evaluăm formule; luăm valorile salvate.
"""
import io
import re
import zipfile
import xml.etree.ElementTree as ET

M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REF = re.compile(r"([A-Z]+)(\d+)")


def col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheets(raw):
    """Întoarce [(nume_foaie, {nr_rând: {index_coloană: text}})] în ordinea din registru."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = set(z.namelist())
    strings = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(M + "si"):
            strings.append("".join(t.text or "" for t in si.iter(M + "t")))
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
            rels[rel.get("Id")] = rel.get("Target", "").lstrip("/").removeprefix("xl/")
    sheets = []
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(M + "sheet"):
        target = rels.get(sheet.get(R + "id"))
        path = f"xl/{target}" if target else None
        if path not in names:
            continue
        rows = {}
        for row in ET.fromstring(z.read(path)).iter(M + "row"):
            cells = {}
            for c in row.findall(M + "c"):
                m = _REF.match(c.get("r") or "")
                if not m:
                    continue
                v = c.find(M + "v")
                text = v.text if v is not None and v.text is not None else ""
                if c.get("t") == "s" and text:
                    text = strings[int(text)]
                elif c.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in c.iter(M + "t"))
                text = " ".join(text.split())
                if text:
                    cells[col_index(m.group(1))] = text
            if cells:
                rows[int(row.get("r") or len(rows) + 1)] = cells
        sheets.append((sheet.get("name") or "", rows))
    return sheets
