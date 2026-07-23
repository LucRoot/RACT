from ract.experimental.leaderboard_loader import load_receipts


def test_load_receipts_loads_valid_json_files(tmp_path):
    (tmp_path / "a.json").write_text('{"model": "m1"}', encoding="utf-8")
    (tmp_path / "b.json").write_text('{"model": "m2"}', encoding="utf-8")
    data = load_receipts(str(tmp_path))
    assert len(data) == 2
    assert {d["model"] for d in data} == {"m1", "m2"}


def test_load_receipts_skips_non_json_files(tmp_path):
    (tmp_path / "a.json").write_text('{"model": "m1"}', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    data = load_receipts(str(tmp_path))
    assert len(data) == 1
    assert data[0]["model"] == "m1"


def test_load_receipts_skips_malformed_json(tmp_path):
    (tmp_path / "good.json").write_text('{"model": "m1"}', encoding="utf-8")
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    data = load_receipts(str(tmp_path))
    assert len(data) == 1
    assert data[0]["model"] == "m1"


def test_load_receipts_returns_empty_list_for_empty_directory(tmp_path):
    data = load_receipts(str(tmp_path))
    assert data == []


# RACT 0.1.1 - Trust and Tooling
