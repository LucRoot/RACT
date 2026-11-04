"""B-095 (S2 floor leg): a fenced Python step reply is stripped before the parse check.

The 3B replay's recorded reply (J4) wrapped the corrected calc.py in a
``<think>`` block and one ```python fence, with prose before and after the
fence, and the write gate refused the turn: "the reply is not a valid
python file". The operator ruling: before the parse check, RACT removes
think blocks and one outer code fence (first opening fence to last closing
fence, prose before and after dropped) from a reply whose target RACT
parses as Python, writes the body byte for byte, and says in one plain line
how many characters it removed; the diff shows the stripped bytes. Any
other file type is untouched, and a reply whose fences do not form one
outer block is refused as before, message and behavior unchanged.
"""

from __future__ import annotations

import ast
import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from ract.session_events import EventStream, SessionEvent
from ract.session_render import PlainRenderer
from ract.session_turn import TurnRequest, run_turn
from ract.write_gate import (
    ReplacementRefused,
    _strip_formatting,
    check_replacement,
    formatting_notice,
)
from tests.fixtures.fake_model_server import Scenario
from tests.test_headless import _ract
from tests.test_session_turn import FIXED, _repo

# The 3B replay's recorded step reply (small_default/J4.raw.txt), scrubbed:
# it holds no address and no machine path, only the project-relative name
# of the file it rewrites.
J4_REPLY = (
    "<think>\n\n</think>\n"
    "Here is the corrected version of the `calc.py` file:\n"
    "\n"
    "```python\n"
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "\n"
    "def sub(a, b):\n"
    "    return a - b\n"
    "```\n"
    "\n"
    "The `add` function now correctly adds two numbers instead of subtracting them."
)

# J4_REPLY minus the body between the fences: think block, prose and fences.
J4_REMOVED = 165
# What the gate removes in a live run: strip_reasoning takes the think
# block earlier, so the gate reports only prose and fences.
J4_REMOVED_AT_THE_GATE = 148

TWO_BLOCKS = (
    "Here is the first part:\n\n"
    "```python\n"
    "def one():\n"
    "    return 1\n"
    "```\n"
    "\n"
    "And the second part:\n\n"
    "```python\n"
    "def two():\n"
    "    return 2\n"
    "```\n"
    "\n"
    "That is the whole change."
)

UNCLOSED = "Here is the file:\n\n```python\ndef one():\n    return 1\n"

# A Python file whose docstring shows a fenced example. The fence lines are
# indented inside the docstring: content, not an outer fence.
DOCSTRING_FENCE = (
    '"""Module docs.\n\n'
    "    A fenced example lives inside this docstring:\n\n"
    "    ```python\n"
    "    x = 1\n"
    "    ```\n"
    '"""\n'
    "\n"
    "VALUE = 1\n"
)

THINK_HIDES_FENCE = (
    "<think>the fix is one function</think>\n```python\ndef one():\n    return 1\n```\n"
)

FAKE_FENCE_MID_PROSE = (
    "A fence looks like ```python but mid-prose it is text, not a fence.\n"
    "Nothing here is code.\n"
)

LONE_FENCE_LINE = "Some prose before.\n```\nMore prose after, with no closing fence.\n"


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


# ------------------------------------------------------------- the strip unit


@pytest.mark.parametrize("kind", ["json", "yaml", "toml", "ini"])
def test_strip_formatting_leaves_other_kinds_alone(kind: str) -> None:
    assert _strip_formatting(kind, "```json\n{}\n```") is None


def test_the_recorded_j4_reply_strips_to_the_body() -> None:
    assert _strip_formatting("python", J4_REPLY) == (FIXED, J4_REMOVED)


def test_two_separate_fenced_blocks_are_not_stripped() -> None:
    assert _strip_formatting("python", TWO_BLOCKS) is None


def test_an_unclosed_fence_is_not_stripped() -> None:
    assert _strip_formatting("python", UNCLOSED) is None
    assert _strip_formatting("python", LONE_FENCE_LINE) is None


def test_a_fence_inside_a_docstring_is_content() -> None:
    assert _strip_formatting("python", DOCSTRING_FENCE) is None


def test_a_think_block_hiding_a_fence_is_stripped_first() -> None:
    body = "def one():\n    return 1\n"
    assert _strip_formatting("python", THINK_HIDES_FENCE) == (
        body,
        len(THINK_HIDES_FENCE) - len(body),
    )


def test_a_fake_fence_mid_prose_is_not_a_fence() -> None:
    assert _strip_formatting("python", FAKE_FENCE_MID_PROSE) is None


def test_inner_fences_stay_as_content() -> None:
    # The body holds one fenced example at column 0; the pair inside the
    # outer fence stays as content and the body still parses.
    reply = (
        "Prose before.\n\n"
        "```python\n"
        'MD = """\n'
        "```\n"
        "inner\n"
        "```\n"
        '"""\n'
        "```\n"
        "\n"
        "Prose after."
    )
    result = _strip_formatting("python", reply)
    assert result is not None
    body, removed = result
    assert "```" in body
    assert ast.parse(body) is not None
    assert removed == len(reply) - len(body)


# ------------------------------------------------ the gate: strip, then judge


def test_a_markdown_target_strips_nothing() -> None:
    old = b"# Notes\n\nOne line.\n"
    fenced = "Here you go:\n\n```markdown\n# Notes\n```\n"
    written, removed = check_replacement("NOTES.md", old, fenced, "rewrite")
    assert written == fenced
    assert removed == 0


def test_a_non_python_target_strips_nothing() -> None:
    # The fence stays: the reply still does not parse, and the refusal is
    # the unchanged parse refusal.
    with pytest.raises(ReplacementRefused, match="not a valid json") as refused:
        check_replacement("data.json", b'{"a": 1}', "```json\n{}\n```", "update")
    assert refused.value.rule == "parse"


def test_the_docstring_reply_is_written_as_is() -> None:
    written, removed = check_replacement(
        "src/guide.py", b"VALUE = 1\n", DOCSTRING_FENCE, "document the module"
    )
    assert written == DOCSTRING_FENCE
    assert removed == 0


def test_no_path_writes_a_reply_that_does_not_parse() -> None:
    # Hostile replies: the full check_replacement refuses each one, and a
    # clean fenced reply passes with text that parses.
    for reply in (TWO_BLOCKS, UNCLOSED, LONE_FENCE_LINE, FAKE_FENCE_MID_PROSE):
        with pytest.raises(ReplacementRefused, match="not a valid python") as refused:
            check_replacement("src/calc.py", FIXED.encode(), reply, "fix add")
        assert refused.value.rule == "parse"
    written, removed = check_replacement(
        "src/calc.py", FIXED.encode(), J4_REPLY, "fix add"
    )
    assert removed == J4_REMOVED
    assert written == FIXED  # byte for byte, the body between the fences
    assert ast.parse(written) is not None


def test_the_refusal_message_is_unchanged_for_a_bad_fence() -> None:
    with pytest.raises(ReplacementRefused) as refused:
        check_replacement("src/calc.py", FIXED.encode(), UNCLOSED, "fix add")
    assert refused.value.rule == "parse"
    assert "the reply is not a valid python file, and the current one is" in str(
        refused.value
    )


# ------------------------------------------------------ the turn, end to end


def _turn(ws: Path, session: str) -> tuple[int, list[SessionEvent], str]:
    out: list[str] = []
    stream = EventStream(session=session)
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    stream.subscribe(PlainRenderer(out.append))
    request = TurnRequest(
        config=ws / "ract.yaml", intent="fix add", session_id=session, resume=False
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events, "".join(out)


def test_the_recorded_reply_is_written_byte_for_byte_with_the_counts(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_one_step("Fix add", "src/calc.py", J4_REPLY))
    ws = _repo(tmp_path, server.base_url)

    code, events, text = _turn(ws, "s-b095strip")

    assert code == 0, text
    # Byte honesty: the file holds exactly the body between the fences (the
    # write path keeps the platform line ending, as every write here does).
    expected_on_disk = FIXED.replace("\n", os.linesep).encode()
    assert (ws / "src" / "calc.py").read_bytes() == expected_on_disk
    # One plain line on the change screen (the notice) and in the turn
    # summary, with the count the gate actually removed.
    line = formatting_notice(J4_REMOVED_AT_THE_GATE)
    notices = [e for e in events if e.kind == "notice"]
    assert any(line in e.data["text"] for e in notices)
    assert f"  {line}" in text
    # The step event carries the counts.
    finished = [e for e in events if e.kind == "step.finished"]
    assert finished[-1].data["stripped"] is True
    assert finished[-1].data["removed_chars"] == J4_REMOVED_AT_THE_GATE
    # The turn record carries the total.
    turn_finished = [e for e in events if e.kind == "turn.finished"]
    assert turn_finished[-1].data["formatting_removed_chars"] == (
        J4_REMOVED_AT_THE_GATE
    )


def test_two_separate_blocks_refuse_the_turn_and_write_nothing(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_one_step("Fix add", "src/calc.py", TWO_BLOCKS))
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes()

    code, events, text = _turn(ws, "s-b095two")

    assert code == 3  # refused, as before the fix
    assert (ws / "src" / "calc.py").read_bytes() == before
    assert "not a valid python file" in text
    # No strip was recorded anywhere.
    finished = [e for e in events if e.kind == "step.finished"]
    assert "stripped" not in finished[-1].data
    assert "removed_chars" not in finished[-1].data
    turn_finished = [e for e in events if e.kind == "turn.finished"]
    assert turn_finished[-1].data["formatting_removed_chars"] is None


def test_the_refusal_end_to_end_over_the_cli_mentions_no_strip(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(_one_step("Fix add", "src/calc.py", UNCLOSED))
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes()

    result = _ract(ws, "-p", "--accept-edits", "fix add", "--output-format", "json")

    assert result.returncode == 3, result.stderr
    assert (ws / "src" / "calc.py").read_bytes() == before
    obj = json.loads(result.stdout)
    assert obj["outcome"] == "refused"
    assert "not a valid python file" in result.stderr
    assert not any("removed" in n for n in obj["notices"])
