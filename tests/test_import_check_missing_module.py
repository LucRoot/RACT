"""B-119 (hosted FOUND 1): an import of a project module that does not exist is refused.

On the hosted model a written ``tests/test_missing.py`` began
``from src.notes import NOTEX`` while ``src/notes.py`` did not exist, and the
harness wrote it and said done. The check reads source only.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from ract.executor.steps import Executor
from ract.import_check import missing_names
from ract.manager import Plan, Step
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from tests.fixtures.fake_model_server import Scenario
from tests.test_reasoning_model_handling import _Adapter, _response, _Router
from tests.test_session_turn import _repo

MISSING = (
    "from src.notes import NOTEX\n\n\ndef test_note():\n    assert NOTEX == 'two'\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    return tmp_path


def _found(repo: Path, text: str, planned: tuple[str, ...] = ()) -> list[str]:
    return [m.describe() for m in missing_names(repo, "tests/test_x.py", text, planned)]


def test_wrights_case_names_the_missing_module(repo: Path) -> None:
    assert _found(repo, MISSING) == [
        "it imports src.notes, which does not exist (line 1)"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "import src.notes\n",
        "from src.calcc import add\n",  # a typo in a project module name
        "import src.calc.deeper\n",
        "from .helpers import x\n",  # relative: always the project's
    ],
)
def test_other_shapes_of_a_missing_project_module(repo: Path, text: str) -> None:
    found = _found(repo, text)
    assert len(found) == 1 and "which does not exist (line 1)" in found[0], found


@pytest.mark.parametrize(
    "text",
    [
        "import os\nfrom collections import OrderedDict\n",
        "import requests\nfrom yaml import safe_load\n",  # installed or not: not checked
        "from notaprojectdir.sub import thing\n",
        "from src.calc import add\nimport src.calc\nfrom src import calc\n",
    ],
)
def test_the_standard_library_dependencies_and_real_modules_pass(
    repo: Path, text: str
) -> None:
    assert _found(repo, text) == []


def test_a_module_a_later_step_writes_counts_as_existing(repo: Path) -> None:
    # The file is planned, not written: its names cannot be read yet, so only
    # the module's existence is decided here.
    assert _found(repo, MISSING, planned=("src/notes.py",)) == []
    assert _found(repo, "from src.notes import NOTE\n", planned=("src/notes.py",)) == []
    assert _found(repo, "import pkg.mod\n", planned=("src/pkg/mod.py",)) == []


def test_a_step_that_writes_wrights_file_is_refused(repo: Path) -> None:
    plan = Plan(
        assumption="a",
        confidence=0.9,
        steps=[
            Step(
                action="Add tests/test_missing.py",
                provider_hint="x",
                expected_artifact="tests/test_missing.py",
            )
        ],
    )
    result = Executor(_Router(_Adapter(_response(MISSING))), project_dir=repo).execute(
        intent="i", plan=plan
    )
    assert not result.is_ok()
    assert "it imports src.notes, which does not exist (line 1)" in result.error
    assert not (repo / "tests" / "test_missing.py").exists()


# ------------------------------------------------------------------ a real turn


def _turn(ws: Path) -> tuple[int, list[SessionEvent]]:
    stream = EventStream(session="s-b119")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="add a test for the notes",
        session_id="s-b119",
        resume=False,
    )
    return run_turn(stream, request, turn=1, cancel=threading.Event()), events


def _plan(*targets: str) -> dict[str, Any]:
    steps = [
        {"action": f"Write {t}", "provider_hint": "local", "expected_artifact": t}
        for t in targets
    ]
    content = json.dumps({"assumption": "a", "confidence": 0.9, "steps": steps})
    return {"reply": {"kind": "text", "content": content}}


def _text(content: str, repeat: bool = False) -> dict[str, Any]:
    turn: dict[str, Any] = {"reply": {"kind": "text", "content": content}}
    if repeat:
        turn["repeat"] = True
    return turn


def test_wrights_hosted_case_on_the_fake_server_is_refused_not_done(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "name": "b119_nofile",
                "turns": [_plan("tests/test_missing.py"), _text(MISSING, True)],
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)

    code, events = _turn(ws)

    assert code != 0
    assert not (ws / "tests" / "test_missing.py").exists()
    error = next(e.data for e in events if e.kind == "error.surfaced")
    assert "src.notes, which does not exist (line 1)" in error["message"]
    assert events[-1].data["outcome"] != "done"


def test_a_plan_whose_later_file_is_imported_passes(
    tmp_path: Path, fake_model_server: Any
) -> None:
    # Step 1 writes the test that imports src/notes.py; step 2 writes that module.
    test_text = (
        "from src.notes import NOTE\n\n\ndef test_note():\n    assert NOTE == 'two'\n"
    )
    server = fake_model_server(
        Scenario.from_dict(
            {
                "name": "b119_planned",
                "turns": [
                    _plan("tests/test_notes.py", "src/notes.py"),
                    _text(test_text),
                    _text('NOTE = "two"\n', True),
                ],
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)

    code, events = _turn(ws)

    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    assert (ws / "tests" / "test_notes.py").exists()
    assert (ws / "src" / "notes.py").exists()
