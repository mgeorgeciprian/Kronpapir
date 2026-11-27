import json
from datetime import datetime, timedelta, timezone

from editorial.presentation import placeholder_image
from social import facebook_poster as fp


def test_mixed_naive_and_aware_dates(tmp_path, monkeypatch):
    now = datetime.now()
    items = {
        "a": now.isoformat(),
        "b": datetime.now(timezone.utc).isoformat(),
        "c": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        "d": "nu-e-data",
    }
    for k, d in items.items():
        (tmp_path / f"{k}.json").write_text(json.dumps({"id": k, "date": d}))
    monkeypatch.setattr(fp, "PROCESSED_DIR", tmp_path)
    got = sorted(a["id"] for a in fp.load_recent_articles(days=2))
    assert got == ["a", "b"]


def test_placeholder_known_alias_and_unknown():
    assert placeholder_image({"category": "sport"}) == "images/placeholders/sport.svg"
    assert placeholder_image({"category": "culture"}) == "images/placeholders/cultura.svg"
    assert placeholder_image({"category": "editorial"}) == "images/placeholders/default.svg"
    assert placeholder_image({"category": "ceva-nou"}) == "images/placeholders/default.svg"
    assert placeholder_image({}, "local") == "images/placeholders/local.svg"
