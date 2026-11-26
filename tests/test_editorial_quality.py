import run_pipeline
from ai.editorial import EditorialAgent, TRUTH_RULES
from ai.rewriter import editorial_text


def _art(n, chars):
    return {"title": f"Știrea {n}", "source": "Digi24", "url": f"https://x/{n}", "content": "<p>" + "a " * (chars // 2) + "</p>"}


def test_editorial_text_strips_html():
    assert editorial_text({"content": "<p>Unu</p>\n<p>doi</p>"}) == "Unu doi"


def test_short_stories_are_not_used_and_no_call_is_made():
    agent = EditorialAgent.__new__(EditorialAgent)
    agent._call_claude = lambda *a, **k: (_ for _ in ()).throw(AssertionError("nu trebuia apelat"))
    assert agent.write_national([_art(1, 1000), _art(2, 100), _art(3, 50)]) is None


def test_usable_keeps_long_stories():
    assert [a["title"] for a in EditorialAgent._usable([_art(1, 1000), _art(2, 100), _art(3, 900)], 5)] == ["Știrea 1", "Știrea 3"]


def test_prompts_carry_truth_rules():
    assert "Nu adăuga nimic din memorie" in TRUTH_RULES


def test_draft_gets_fact_check_and_drops_inputs(monkeypatch):
    saved = {}
    monkeypatch.setattr(run_pipeline, "fact_check_editorial",
                        lambda ed, inputs: {"scor": 4, "erori_blocante": [{"tip": "x"}], "recomandari": [], "model": "m"} if inputs else None)
    import editorial.store as store
    monkeypatch.setattr(store, "save_draft", lambda art, reason="": saved.update(art=art, reason=reason) or art)
    run_pipeline.save_editorial_draft({"title": "T", "content": "C", "_inputs": [_art(1, 1000)]})
    assert "_inputs" not in saved["art"]
    assert saved["art"]["fact_check"]["scor"] == 4
    assert "scor 4/10, 1 eroare" in saved["reason"]
