from editorial import review_editorials as rv


def test_candidate_sources_window_source_and_similarity():
    ed = {"date": "2026-11-20T22:00:00", "sources_used": ["Digi24"],
          "title": "Bugetul Brașovului", "content": "<p>Consiliul local a votat bugetul pentru autostrada Brașov</p>"}
    raw = [
        {"source": "Digi24", "created_at": "2026-11-20T10:00:00", "title": "Bugetul votat", "content": "Consiliul local a votat bugetul pentru autostrada"},
        {"source": "Digi24", "created_at": "2026-11-20T11:00:00", "title": "Fotbal", "content": "Meciul de aseară s-a terminat egal"},
        {"source": "Digi24", "created_at": "2026-11-15T10:00:00", "title": "Bugetul vechi", "content": "Consiliul local a votat bugetul"},
        {"source": "HotNews", "created_at": "2026-11-20T10:00:00", "title": "Bugetul", "content": "Consiliul local a votat bugetul"},
    ]
    got = rv.candidate_sources(ed, raw, limit=5)
    assert [a["title"] for a in got] == ["Bugetul votat", "Fotbal"]


def test_passes_requires_score_and_no_blocking_errors():
    assert rv.passes({"scor": 8, "erori_blocante": []})
    assert not rv.passes({"scor": 9, "erori_blocante": [{"tip": "x", "valoare": "y", "motiv": "z"}]})
    assert not rv.passes({"scor": 7, "erori_blocante": []})
    assert not rv.passes(None)


def test_build_message_marks_editorial():
    msg = rv.build_message({"title": "T", "content": "C"}, [{"source": "S", "url": "u", "title": "x", "content": "y"}])
    assert "EDITORIAL" in msg and "TEXTUL SURSĂ 1" in msg
