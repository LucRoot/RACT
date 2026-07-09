# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the dead-code auction."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import os
import time
from pathlib import Path
from unittest.mock import patch

from rootact.cli import main
from rootact.dead_code_auction import AuctionItem, DeadCodeAuction


def _set_old_mtime(path: Path, days: int = 200) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_auction_finds_unreferenced_old_file(tmp_path: Path):
    target = tmp_path / "old_module.py"
    target.write_text("def unused():\n    pass\n", encoding="utf-8")
    _set_old_mtime(target)

    items = DeadCodeAuction(tmp_path).scan()

    assert len(items) == 1
    assert items[0].relative_path == "old_module.py"
    assert items[0].inbound_references == 0
    assert items[0].last_modified_days >= 200


def test_auction_ignores_recent_files(tmp_path: Path):
    target = tmp_path / "recent.py"
    target.write_text("def fresh():\n    pass\n", encoding="utf-8")

    items = DeadCodeAuction(tmp_path).scan()

    assert items == []


def test_auction_ignores_referenced_files(tmp_path: Path):
    old = tmp_path / "old_module.py"
    old.write_text("def helper():\n    pass\n", encoding="utf-8")
    _set_old_mtime(old)
    user = tmp_path / "user.py"
    user.write_text("from old_module import helper\n\nhelper()\n", encoding="utf-8")
    _set_old_mtime(user, days=10)

    items = DeadCodeAuction(tmp_path).scan()

    assert all(item.relative_path != "old_module.py" for item in items)


def test_auction_respects_min_age_days(tmp_path: Path):
    target = tmp_path / "middle_aged.py"
    target.write_text("def maybe():\n    pass\n", encoding="utf-8")
    _set_old_mtime(target, days=100)

    assert DeadCodeAuction(tmp_path, config={"min_age_days": 90}).scan()
    assert not DeadCodeAuction(tmp_path, config={"min_age_days": 120}).scan()


def test_auction_ignores_test_files_by_default(tmp_path: Path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_x.py"
    target.write_text("def test_x():\n    pass\n", encoding="utf-8")
    _set_old_mtime(target)

    assert DeadCodeAuction(tmp_path).scan() == []
    items = DeadCodeAuction(tmp_path, config={"include_tests": True}).scan()
    assert len(items) == 1
    assert items[0].relative_path == str(Path("tests/test_x.py"))


def test_auction_ignores_dependency_dirs(tmp_path: Path):
    venv = tmp_path / ".venv" / "Lib" / "site-packages"
    venv.mkdir(parents=True)
    target = venv / "old_pkg.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _set_old_mtime(target)

    items = DeadCodeAuction(tmp_path).scan()
    assert items == []


def test_auction_flags_module_imported_only_by_its_test(tmp_path: Path):
    """A production module referenced only by its paired test is still dead."""
    prod = tmp_path / "prod_module.py"
    prod.write_text("def helper():\n    pass\n", encoding="utf-8")
    _set_old_mtime(prod)

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_prod_module.py"
    test_file.write_text(
        "from prod_module import helper\n\ndef test_helper():\n    helper()\n",
        encoding="utf-8",
    )
    _set_old_mtime(test_file)

    items = DeadCodeAuction(tmp_path).scan()
    paths = [item.relative_path for item in items]
    assert "prod_module.py" in paths
    assert all("test_" not in p for p in paths)


def test_cli_auction_list_json(capsys, tmp_path: Path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")

    fake_item = AuctionItem(
        path=tmp_path / "dead.py",
        relative_path="dead.py",
        last_modified_days=250,
        inbound_references=0,
        reason="no inbound references",
    )

    with patch("rootact.cli.DeadCodeAuction") as MockAuction:
        MockAuction.return_value.scan.return_value = [fake_item]
        code = main(["auction", "list", "--json", "--config", str(config)])
        out = capsys.readouterr().out

    assert code == 0
    assert "dead.py" in out
    assert "250" in out


def test_ract_auction_reports_zero_dead_modules():
    """Release gate: the RACT source tree must not accumulate dead modules.

    This test runs the auction against RACT itself. If it fails, the offending
    module(s) must either be wired back into production code or removed.
    """
    project_root = Path(__file__).parent.parent / "src" / "rootact"
    items = DeadCodeAuction(
        project_root, config={"min_age_days": 0}
    ).scan()
    assert items == [], f"dead-code auction found: {[i.relative_path for i in items]}"


# RACT 0.1.0 - Initial Public Release
