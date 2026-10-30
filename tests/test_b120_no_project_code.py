"""B-120 (hosted FOUND 2): a new test that never touches project code says so.

On the hosted model a written tests/test_notes.py defined ``NOTE = "two"``
itself and never imported src.notes: it checked a copy. A warning next to the
verified line, never a refusal and never a verdict. Source is read only.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from ract.import_check import is_test_file, uses_project_code
from ract.session_events import EventStream, SessionEvent
from ract.session_render import PlainRenderer
from ract.session_turn import TurnRequest, run_turn
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo

COPY = 'NOTE = "two"\n\n\ndef test_note():\n    assert NOTE == "two"\n'
WARNING = "tests/test_notes.py does not use project code"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "notes.py").write_text('NOTE = "two"\n', encoding="utf-8")
    (tmp_path / "tests").mkdir()
    return tmp_path


@pytest.mark.parametrize(
    "text",
    [
        COPY,
        "import pytest\nimport os\n\n\ndef test_env():\n    assert os.sep\n",
        "from collections import Counter\n\n\ndef test_c():\n    assert Counter()\n",
    ],
)
def test_a_test_with_no_project_code(repo: Path, text: str) -> None:
    assert uses_project_code(repo, "tests/test_notes.py", text) is False


@pytest.mark.parametrize(
    "text",
    [
        "from src.notes import NOTE\n\n\ndef test_note():\n    assert NOTE\n",
        "import src.notes\n",
        "from .helpers import x\n",
        # Runs the project's CLI as a process: may test project code.
        "import subprocess\n\n\ndef test_cli():\n    subprocess.run(['python', 'app.py'])\n",
        "import os\n\n\ndef test_cli():\n    os.system('python app.py')\n",
    ],
)
def test_a_test_that_touches_project_code(repo: Path, text: str) -> None:
    assert uses_project_code(repo, "tests/test_notes.py", text) is True


def test_a_file_that_does_not_parse_is_not_judged(repo: Path) -> None:
    assert uses_project_code(repo, "tests/test_notes.py", "def (:\n") is None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_notes.py", True),
        ("test_top.py", True),
        ("pkg/calc_test.py", True),
        ("tests/helpers.py", True),
        ("tests/conftest.py", False),
        ("tests/__init__.py", False),
        ("src/notes.py", False),
        ("tests/data.json", False),
    ],
)
def test_which_files_are_tests(path: str, expected: bool) -> None:
    assert is_test_file(path) is expected


# ------------------------------------------------------------------ a real turn


def _run(
    tmp_path: Path,
    fake_model_server: Any,
    text: str,
    target: str = "tests/test_notes.py",
) -> tuple[int, list[SessionEvent], str]:
    plan = {
        "assumption": "a",
        "confidence": 0.9,
        "steps": [
            {
                "action": f"Write {target}",
                "provider_hint": "local",
                "expected_artifact": target,
            }
        ],
    }
    server = fake_model_server(
        Scenario.from_dict(
            {
                "name": "b120",
                "turns": [
                    {"reply": {"kind": "text", "content": json.dumps(plan)}},
                    {"reply": {"kind": "text", "content": text}, "repeat": True},
                ],
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    out: list[str] = []
    stream = EventStream(session="s-b120")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    stream.subscribe(PlainRenderer(out.append))
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="add a test for the note",
        session_id="s-b120",
        resume=False,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events, "".join(out)


def test_wrights_copy_test_is_named_next_to_the_verified_line(
    tmp_path: Path, fake_model_server: Any
) -> None:
    code, events, text = _run(tmp_path, fake_model_server, COPY)

    assert code == 0  # a warning, not a refusal
    finished = events[-1].data
    assert finished["verification"]["no_project_code"] == ["tests/test_notes.py"]
    assert finished["verification"]["status"] == "not-run"  # never a verdict
    lines = [line.strip() for line in text.splitlines()]
    verified_at = next(
        i for i, line in enumerate(lines) if line.startswith("verified:")
    )
    assert lines[verified_at + 1] == WARNING


def test_a_test_that_imports_the_project_has_no_warning(
    tmp_path: Path, fake_model_server: Any
) -> None:
    # Unlike the project's own tests, so the duplication guard lets it through.
    good = (
        "from src import calc\n\n\ndef test_add_is_commutative():\n"
        "    for a, b in [(1, 2), (5, -3)]:\n"
        "        assert calc.add(a, b) == calc.add(b, a)\n"
    )
    code, events, text = _run(tmp_path, fake_model_server, good)

    assert code == 0
    assert "no_project_code" not in events[-1].data["verification"]
    assert "does not use project code" not in text


def test_a_non_test_file_has_no_warning(tmp_path: Path, fake_model_server: Any) -> None:
    code, events, text = _run(
        tmp_path, fake_model_server, 'NOTE = "two"\n', target="src/notes.py"
    )

    assert code == 0
    assert "does not use project code" not in text
