"""S-026: a step's reply never silently replaces a file with something else.

The probe from G-048: the v0.5.2 manager prompt taught "for reads use the
target file path", so a plan step `read src/calc.py` with expected_artifact
src/calc.py replaced calc.py with the model's prose and the turn said Done.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ract import undo_backup
from ract.write_gate import (
    QUESTION_VERBS,
    ReplacementRefused,
    check_replacement,
    reads_like_a_question,
)
from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import FIXED, _repo

PROSE = "The file defines add(a, b) which currently subtracts. I would change it."


def _git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.strip()


def _one_step(action: str, artifact: str, reply: str) -> Scenario:
    plan = json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {
                    "action": action,
                    "provider_hint": "local",
                    "expected_artifact": artifact,
                }
            ],
        }
    )
    return Scenario.from_dict(
        {
            "turns": [
                {"reply": {"kind": "text", "content": plan}},
                {"reply": {"kind": "text", "content": reply}},
            ]
        }
    )


# ------------------------------------------------------------ the G-048 probe


def test_the_read_probe_leaves_calc_py_unchanged(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_one_step("read src/calc.py", "src/calc.py", PROSE))
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes()

    result = _ract(
        ws, "run", "--config", "ract.yaml", "--", "what does src/calc.py do?"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (ws / "src" / "calc.py").read_bytes() == before
    assert _git(ws, "status", "--porcelain") == ""
    assert _git(ws, "branch", "--list", "rootact/step/*") == ""
    assert "src/calc.py, which is not written" in result.stdout


def test_the_read_probe_shows_the_reply_as_the_answer(
    tmp_path: Path, fake_model_server: Any
) -> None:
    # G-051: the reply is what the user asked for; show it, write nothing.
    server = fake_model_server(_one_step("read src/calc.py", "src/calc.py", PROSE))
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes()

    result = _ract(
        ws, "-p", "what does src/calc.py do?", "--output-format", "stream-json"
    )

    assert result.returncode == 0, result.stderr
    assert (ws / "src" / "calc.py").read_bytes() == before
    events = [json.loads(line) for line in result.stdout.splitlines()]
    answer = "".join(
        e["data"]["text"]
        for e in events
        if e["kind"] == "agent.text.delta" and e["data"].get("channel") == "answer"
    )
    assert PROSE in answer
    notices = [e["data"]["text"] for e in events if e["kind"] == "notice"]
    assert any("src/calc.py, which is not written" in n for n in notices)
    # The step prompt asked for an answer, not a file.
    assert "no file is written" in json.dumps(server.chat_requests[1].body)


def test_prose_for_a_python_file_is_refused_whatever_the_verb(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_one_step("Fix add", "src/calc.py", PROSE))
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes()

    result = _ract(ws, "-p", "fix add", "--output-format", "json")

    assert result.returncode == 3, result.stderr  # refused
    assert (ws / "src" / "calc.py").read_bytes() == before
    assert json.loads(result.stdout)["outcome"] == "failed"
    assert "not a valid python file" in result.stderr
    # The hint names /ask, not the model server (the old hint table read
    # any "refused" as a refused connection).
    assert "/ask" in result.stderr
    assert "start your model server" not in result.stderr


def test_a_valid_rewrite_applies_and_keeps_the_previous_version(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_one_step("Fix add", "src/calc.py", FIXED))
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes()

    result = _ract(ws, "-p", "fix add", "--output-format", "stream-json")

    assert result.returncode == 0, result.stderr
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")
    saved = list(undo_backup.turns_dir(ws).glob("*/src/calc.py"))
    assert len(saved) == 1
    assert saved[0].read_bytes() == before  # restores byte for byte
    finished = [
        json.loads(line)
        for line in result.stdout.splitlines()
        if '"turn.finished"' in line
    ][-1]
    assert "/undo restores them" in finished["data"]["workspace"]
    assert not (ws / ".ract" / "undo").exists()  # S-028: never in the workspace
    assert _git(ws, "status", "--porcelain") == "M src/calc.py"


def test_ract_run_names_the_backup_folder(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_one_step("Fix add", "src/calc.py", FIXED))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "run", "--config", "ract.yaml", "--", "fix add")

    assert result.returncode == 0, result.stderr
    assert (
        "note: previous version of 1 file saved; /undo restores them" in result.stdout
    )


# ------------------------------------------------------------- the gate rules


@pytest.mark.parametrize(
    ("path", "old", "new"),
    [
        ("data.json", '{"a": 1}', "Here is the file you asked about."),
        ("conf.yaml", "a: 1\nb: [1, 2]\n", "a: [unclosed\n"),
        ("pyproject.toml", '[project]\nname = "x"\n', "The project is named x."),
        ("setup.cfg", "[metadata]\nname = x\n", "name x without a section"),
        ("src/m.py", "def f():\n    return 1\n", "f returns 1."),
    ],
)
def test_a_parseable_file_must_still_parse(path: str, old: str, new: str) -> None:
    with pytest.raises(ReplacementRefused, match="not a valid"):
        check_replacement(path, old.encode(), new, "update the file")


def test_a_file_that_did_not_parse_may_be_replaced() -> None:
    check_replacement("broken.json", b"{not json", '{"fixed": true}', "fix it")
    check_replacement("broken.json", b"{not json", "still not json", "fix it")


def test_markdown_is_replaced_freely_unless_it_shrinks_to_a_tenth() -> None:
    small_old = b"# Notes\n\nOne line.\n"
    check_replacement("NOTES.md", small_old, "Entirely different text.", "rewrite")
    long_old = ("line of the notes file\n" * 80).encode()
    check_replacement("NOTES.md", long_old, "x" * 1000, "rewrite the notes")
    with pytest.raises(ReplacementRefused, match="does not say it deletes"):
        check_replacement("NOTES.md", long_old, "Summary: notes.", "rewrite the notes")
    check_replacement("NOTES.md", long_old, "", "truncate the notes")
    check_replacement("NOTES.md", long_old, "kept", "remove the old entries")


def test_question_verbs_never_replace_an_existing_file() -> None:
    for verb in sorted(QUESTION_VERBS):
        assert reads_like_a_question(f"{verb.capitalize()}: src/calc.py")
        with pytest.raises(ReplacementRefused, match="asks for information"):
            check_replacement(
                "src/calc.py", b"x = 1\n", "x = 2\n", f"{verb} src/calc.py"
            )
    assert not reads_like_a_question("fix add in src/calc.py")
    assert not reads_like_a_question("")


@pytest.mark.parametrize(
    "action",
    [
        "check the loader and fix the typo",
        "Review greeter.py and update the docstring",
        "read the file and rewrite it with one helper",
    ],
)
def test_a_write_verb_makes_a_question_verb_a_change(action: str) -> None:
    # D-019: "check X and fix Y" writes; the parse and size gates still apply.
    assert not reads_like_a_question(action)
    check_replacement("src/calc.py", b"x = 1\n", "x = 2\n", action)
    with pytest.raises(ReplacementRefused) as refused:
        check_replacement("src/calc.py", b"x = 1\n", "x is now two.", action)
    assert refused.value.rule == "parse"


def test_answer_instead_converts_only_question_steps_on_existing_files(
    tmp_path: Path,
) -> None:
    from ract.manager import Plan, Step
    from ract.write_gate import answer_instead

    (tmp_path / "calc.py").write_text("x = 1\n", encoding="utf-8")
    plan = Plan(
        assumption="a",
        confidence=0.9,
        steps=[
            Step(
                action="read calc.py",
                provider_hint="local",
                expected_artifact="calc.py",
            ),
            Step(
                action="list the todos",
                provider_hint="local",
                expected_artifact="TODO.md",
            ),
            Step(
                action="fix calc.py", provider_hint="local", expected_artifact="calc.py"
            ),
        ],
    )

    converted, notes = answer_instead(plan, tmp_path)

    assert [s.expected_artifact for s in converted.steps] == ["", "TODO.md", "calc.py"]
    assert len(notes) == 1 and "step 1" in notes[0]
    assert answer_instead(plan, None) == (plan, [])


def test_binary_old_content_is_not_judged() -> None:
    check_replacement("logo.png", b"\x89PNG\xff\xfe", "text", "replace the logo")


# ------------------------------------------------------------------- backups


def test_backup_saves_once_per_turn_and_skips_new_and_internal_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_bytes(b"first\r\n")
    (tmp_path / ".ract").mkdir()
    (tmp_path / ".ract" / "state.json").write_text("{}", encoding="utf-8")

    with undo_backup.turn(tmp_path) as backup:
        undo_backup.save_before_replace(tmp_path, ["a.txt"])
        (tmp_path / "a.txt").write_bytes(b"second\n")
        undo_backup.save_before_replace(
            tmp_path, ["a.txt", "new.txt", ".ract/state.json"]
        )

    assert backup.saved == ["a.txt"]
    assert (backup.folder / "a.txt").read_bytes() == b"first\r\n"
    assert backup.describe().startswith(
        "previous version of 1 file saved; /undo restores them"
    )


def test_nothing_is_saved_outside_a_turn(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")

    undo_backup.save_before_replace(tmp_path, ["a.txt"])

    assert not (tmp_path / ".ract").exists()


def test_old_turn_folders_are_pruned(tmp_path: Path) -> None:
    undo = undo_backup.turns_dir(tmp_path)
    for i in range(undo_backup.KEEP_TURNS + 3):
        (undo / f"20261022T0000{i:02d}Z-aaaaaa").mkdir(parents=True)

    undo_backup.prune(tmp_path)

    left = sorted(p.name for p in undo.iterdir())
    assert len(left) == undo_backup.KEEP_TURNS
    assert left[0] == "20261022T000003Z-aaaaaa"


def test_the_answer_instead_notice_is_in_the_headless_result(
    tmp_path: Path, fake_model_server: Any
) -> None:
    # G-053: a CI log that reads only stdout still sees why nothing was written.
    server = fake_model_server(_one_step("read src/calc.py", "src/calc.py", PROSE))
    ws = _repo(tmp_path, server.base_url)

    result = _ract(ws, "-p", "what does src/calc.py do?", "--output-format", "json")

    assert result.returncode == 0, result.stderr
    obj = json.loads(result.stdout)
    assert any(
        "its reply is shown as the answer" in n
        and "src/calc.py, which is not written" in n
        for n in obj["notices"]
    )
    assert PROSE in obj["final_text"]
