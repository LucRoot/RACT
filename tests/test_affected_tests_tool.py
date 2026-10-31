"""B-141: tools/affected_tests.py maps a change to its test files and runs them one by one."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "affected_tests.py"

_spec = importlib.util.spec_from_file_location("affected_tests", TOOL)
assert _spec is not None and _spec.loader is not None
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tmp_path


FIXTURE = {
    "src/ract/__init__.py": "",
    "src/ract/calc.py": "def add(a, b):\n    return a + b\n",
    "src/ract/shapes/__init__.py": "",
    "src/ract/shapes/box.py": "WIDTH = 1\n",
    "tests/__init__.py": "",
    "tests/helpers.py": "from ract.calc import add\n",
    "tests/test_calc.py": "def test_x():\n    pass\n",  # by name
    "tests/test_uses_add.py": "from ract.calc import add\n",  # by import
    "tests/test_uses_box.py": "from ract.shapes import box, other\n",
    "tests/test_uses_helper.py": "from tests.helpers import add\n",
    "tests/test_reads_readme.py": 'README = "README.md"\n',
    "tests/test_unrelated.py": "import json\n",
    "tests/architecture/test_rule.py": "",
    "tests/test_source_digest.py": "",
}


def test_a_source_module_maps_to_its_importers_and_its_named_test(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path, FIXTURE)
    targets, notes = tool.affected(["src/ract/calc.py"], root)
    assert targets[:2] == ["tests/test_calc.py", "tests/test_uses_add.py"]
    assert "tests/test_unrelated.py" not in targets
    assert "tests/test_uses_helper.py" not in targets  # through a helper: not by import
    assert notes == []
    # The always-run set comes last, only the parts that exist.
    assert targets[-2:] == ["tests/architecture", "tests/test_source_digest.py"]


def test_from_a_package_import_a_module_counts(tmp_path: Path) -> None:
    root = _tree(tmp_path, FIXTURE)
    targets, _ = tool.affected(["src/ract/shapes/box.py"], root)
    assert "tests/test_uses_box.py" in targets


def test_a_helper_a_doc_and_a_test_file(tmp_path: Path) -> None:
    root = _tree(tmp_path, FIXTURE)
    targets, _ = tool.affected(
        ["tests/helpers.py", "README.md", "tests/test_unrelated.py"], root
    )
    assert {
        "tests/test_uses_helper.py",
        "tests/test_reads_readme.py",
        "tests/test_unrelated.py",
    } <= set(targets)
    assert "tests/test_uses_add.py" not in targets


def test_a_changed_conftest_is_a_note(tmp_path: Path) -> None:
    root = _tree(tmp_path, FIXTURE)
    targets, notes = tool.affected(["tests/conftest.py"], root)
    assert notes and "full suite" in notes[0]
    assert targets == ["tests/architecture", "tests/test_source_digest.py"]


def test_run_prints_one_line_per_file_and_fails_on_a_failure(
    tmp_path: Path, capsys
) -> None:
    root = _tree(
        tmp_path,
        {
            "tests/test_ok.py": "def test_ok():\n    assert True\n",
            "tests/test_bad.py": "def test_bad():\n    assert False\n",
        },
    )
    code = tool.run(["tests/test_ok.py", "tests/test_bad.py"], root)
    lines = capsys.readouterr().out.splitlines()
    assert code == 1
    assert lines[0].startswith("tests/test_ok.py | 1 passed")
    assert lines[1].startswith("tests/test_bad.py | 1 failed")


def test_the_script_lists_the_targets_for_a_path_in_this_repository() -> None:
    proc = subprocess.run(
        [sys.executable, str(TOOL), "src/ract/manager.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    listed = proc.stdout.splitlines()
    assert "tests/test_manager.py" in listed
    assert listed[-1] == "tests/unit/test_readme_verb_index_matches_parser.py"
