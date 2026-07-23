__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

import pytest

from rootact.receipt_export import export_receipts, main


def test_export_receipts_loads_dict_and_list(tmp_path):
    (tmp_path / "a.receipt.json").write_text(
        json.dumps({"run_id": "r1", "signer_id": "s1", "signature": "sig1"}),
        encoding="utf-8",
    )
    (tmp_path / "b.receipt.json").write_text(
        json.dumps([{"run_id": "r2", "signer_id": "s2", "signature": "sig2"}]),
        encoding="utf-8",
    )
    data = export_receipts(str(tmp_path))
    assert len(data) == 2
    assert all("signer_id" not in d for d in data)
    assert all("signature" not in d for d in data)
    assert {d["run_id"] for d in data} == {"r1", "r2"}


def test_export_receipts_skips_malformed_files(tmp_path):
    (tmp_path / "good.receipt.json").write_text(
        json.dumps({"run_id": "r1"}), encoding="utf-8"
    )
    (tmp_path / "bad.receipt.json").write_text("not json", encoding="utf-8")
    data = export_receipts(str(tmp_path))
    assert len(data) == 1
    assert data[0]["run_id"] == "r1"


def test_export_receipts_missing_directory_raises():
    with pytest.raises(FileNotFoundError):
        export_receipts("/nonexistent/path/for/receipts")


def test_main_prints_json_on_success(tmp_path, capsys):
    (tmp_path / "a.receipt.json").write_text(
        json.dumps({"run_id": "r1", "signer_id": "s1", "signature": "sig1"}),
        encoding="utf-8",
    )
    main(["receipt_export", "--directory", str(tmp_path)])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) == 1
    assert data[0]["run_id"] == "r1"


def test_main_requires_directory(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["receipt_export"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "--directory is required" in captured.err


def test_export_receipts_markdown(tmp_path):
    (tmp_path / "a.receipt.json").write_text(
        json.dumps({"run_id": "r1", "plan_hash": "p1", "diff_hash": "d1"}),
        encoding="utf-8",
    )
    result = export_receipts(str(tmp_path), fmt="markdown")
    assert isinstance(result, str)
    assert "# Receipt Export" in result
    assert "| run_id |" in result
    assert "r1" in result


def test_main_markdown_output(tmp_path, capsys):
    (tmp_path / "a.receipt.json").write_text(
        json.dumps({"run_id": "r1", "plan_hash": "p1", "diff_hash": "d1"}),
        encoding="utf-8",
    )
    main(["receipt_export", "--directory", str(tmp_path), "--markdown"])
    captured = capsys.readouterr()
    assert "# Receipt Export" in captured.out
    assert "| run_id |" in captured.out


# RACT 0.1.1 - Trust and Tooling
