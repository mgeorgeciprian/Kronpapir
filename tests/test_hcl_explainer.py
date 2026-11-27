import json
from datetime import datetime
from types import SimpleNamespace

from ai import hcl_explainer as hx

NOW = datetime(2026, 11, 27, 6, 0)
SOURCE = ("Proiect de hotărâre privind stabilirea taxei de promovare turistică de 7 lei/noapte/turist. "
          "Referat de aprobare: bonificația pentru plata până la 31 martie este de 10 %. ") * 20
GOOD = {"titlu_simplu": "Taxa de promovare turistică: 7 lei pe noapte", "pe_scurt": "Cine oferă cazare plătește 7 lei/noapte/turist.",
        "ce_se_schimba": ["Taxa de promovare turistică de 7 lei/noapte/turist."], "pe_cine_afecteaza": ["pensiunile"],
        "cifre_cheie": [{"cifra": "10 %", "ce_inseamna": "bonificația până la 31 martie"}],
        "ce_poti_face": "Plătește până la 31 martie.", "ce_nu_stim": "Data ședinței."}


class FakeMessages:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def create(self, **kw):
        out = self.outputs.pop(0)
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10, output_tokens=10),
                               content=[SimpleNamespace(type="text", text=json.dumps(out))])


class FakeClient:
    def __init__(self, outputs):
        self.beta = SimpleNamespace(messages=FakeMessages(outputs))


class FakeChecker:
    def __init__(self, score):
        self.score = score

    def check(self, src, art, source_chars=0, note=""):
        return {"scor": self.score, "erori_blocante": [], "subiect_sensibil": False, "motiv_sensibil": "", "model": "x"}


ITEM = {"id": "hcl-1", "kind": "hcl", "title": "PROIECT DE HOTĂRÂRE privind taxele", "url": "https://www.brasovcity.ro/x",
        "status": "În dezbatere publică", "published": "2026-10-30", "deadline": "2026-11-16", "files": []}


def explainer(outputs, score, monkeypatch, tmp_path):
    monkeypatch.setattr(hx.costs, "COSTS_DIR", tmp_path / "costs")
    monkeypatch.setattr(hx.costs, "check", lambda cfg, now: None)
    return hx.Explainer(client=FakeClient(outputs), fact_checker=FakeChecker(score))


def test_good_explanation_is_published(monkeypatch, tmp_path):
    rec = explainer([GOOD], 9, monkeypatch, tmp_path).explain(ITEM, SOURCE, NOW)
    assert rec["status"] == "published" and rec["factcheck"]["scor"] == 9
    assert rec["label"].startswith("Explicație generată automat")


def test_invented_number_is_retried_then_draft(monkeypatch, tmp_path):
    bad = dict(GOOD, pe_scurt="Taxa crește la 9 lei/noapte, de la 3.500 de turiști.")
    rec = explainer([bad, bad], 9, monkeypatch, tmp_path).explain(ITEM, SOURCE, NOW)
    assert rec["status"] == "draft" and any(e["valoare"] == "3.500" for e in rec["factcheck"]["erori"])


def test_low_score_is_draft(monkeypatch, tmp_path):
    rec = explainer([GOOD, GOOD], 6, monkeypatch, tmp_path).explain(ITEM, SOURCE, NOW)
    assert rec["status"] == "draft"


def test_pick_documents_skips_plans_and_announcements():
    files = [{"name": "01. Anunt dezbatere PHCL [100 KB]", "url": "a"}, {"name": "02. PHCL Criterii [120 KB]", "url": "b"},
             {"name": "03. Referat de aprobare [100 KB]", "url": "c"}, {"name": "PLAN REGLEMENTARI PUZ [4 MB]", "url": "d"},
             {"name": "04. Raport de specialitate [200 KB]", "url": "e"}, {"name": "05. Anexa 1 [12 MB]", "url": "f"}]
    assert [f["url"] for f in hx.pick_documents(files)] == ["b", "c", "e"]


def test_candidates_open_first_and_year_filter():
    store = {"items": {"hcl-a": dict(ITEM, status="Aprobat prin HCL", published="2026-09-01"),
                       "hcl-b": dict(ITEM, published="2026-10-30"),
                       "hcl-c": dict(ITEM, status="Aprobat prin HCL", published="2024-01-01"),
                       "hcl-d": dict(ITEM, published="2024-01-08")}}  # „în dezbatere” rămas din 2024 pe site
    assert [c["id"] for c in hx.candidates(store, {}, year=2026)] == ["hcl-b", "hcl-a"]
    assert [c["id"] for c in hx.candidates(store, {"hcl-b": {}}, year=2026)] == ["hcl-a"]


def test_page_shows_only_published_explanations(tmp_path):
    from web.app import app
    from web import business
    store = {"items": {"hcl-1": dict(ITEM, deadline="2099-01-01", n_files=5,
                                     files=[{"name": "PLAN REGLEMENTARI PUZ NISTOR RODICA [4 MB]", "url": "p"},
                                            {"name": "02. Proiect de hotarare [100 KB]", "url": "q"}]),
                       "hcl-2": dict(ITEM, status="Aprobat prin HCL", title="Proiect de hotărâre privind parcările")}}
    (tmp_path / "store.json").write_text(json.dumps(store), encoding="utf-8")
    (tmp_path / "explicatii").mkdir()
    (tmp_path / "explicatii" / "hcl-1.json").write_text(json.dumps({"id": "hcl-1", "status": "published", "explicatie": GOOD, "label": hx.LABEL}), encoding="utf-8")
    (tmp_path / "explicatii" / "hcl-2.json").write_text(json.dumps({"id": "hcl-2", "status": "draft", "explicatie": dict(GOOD, titlu_simplu="CIORNA ASCUNSA")}), encoding="utf-8")
    app.config["BRASOVCITY_STORE"] = str(tmp_path / "store.json")
    try:
        html = app.test_client().get(business.PRIMARIA_PATH).get_data(as_text=True)
        assert "Pe înțelesul tuturor" in html and "Taxa de promovare turistică: 7 lei pe noapte" in html
        assert "CIORNA ASCUNSA" not in html and "NISTOR" not in html
        home = app.test_client().get("/").get_data(as_text=True)
        assert "Consiliul Local Brașov" in home and "#hcl-1" in home
        assert app.test_client().get("/admin/explicatii-hcl").status_code == 302  # doar cu login
    finally:
        app.config.pop("BRASOVCITY_STORE")


def test_costs_ledger_counts_tokens_and_cache(monkeypatch, tmp_path):
    from ai import costs
    monkeypatch.setattr(costs, "COSTS_DIR", tmp_path)
    u = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=30000, cache_creation_input_tokens=0)
    usd, total = costs.record("explicator-hcl", "claude-sonnet-5-5", u, NOW)
    assert round(usd, 6) == round((1000 * 2 + 500 * 10 + 30000 * 2 * 0.05) / 1e6, 6)
    w = SimpleNamespace(input_tokens=10, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=30000)
    costs.record("explicator-hcl", "claude-sonnet-5-5", w, NOW)
    row = costs.report(NOW, tmp_path)[0]
    assert row[0] == "explicator-hcl" and row[2] == 2 and row[3] == 1010 and row[4] == 500 and row[5] == 30000


def test_documents_go_in_cached_block(monkeypatch, tmp_path):
    ex = explainer([GOOD], 9, monkeypatch, tmp_path)
    seen = {}
    orig = ex.client.beta.messages.create
    ex.client.beta.messages.create = lambda **kw: (seen.update(kw), orig(**kw))[1]
    ex.write(ITEM, SOURCE, feedback="cifra 9 nu apare")
    blocks = seen["messages"][0]["content"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"} and SOURCE[:50] in blocks[0]["text"]
    assert "cifra 9" in blocks[1]["text"] and "cache_control" not in blocks[1]


def test_numbers_glued_to_units_in_pdf_are_found():
    from editorial import factcheck as fc
    art = {"title": "x", "content": "<p>Între 501 lei și 800 lei; linia de 400 kV.</p>", "url": "u"}
    assert fc.deterministic("Sub 500 lei – 0; 501lei – 800lei – 300; LEA 400kV", art, NOW, official=True)["erori"] == []


def test_redo_drafts_only_unreviewed():
    store = {"items": {"hcl-a": dict(ITEM), "hcl-b": dict(ITEM), "hcl-c": dict(ITEM)}}
    done = {"hcl-a": {"status": "draft"}, "hcl-b": {"status": "published"}, "hcl-c": {"status": "draft", "reviewed_at": "x"}}
    assert [c["id"] for c in hx.candidates(store, done, redo_drafts=True)] == ["hcl-a"]
