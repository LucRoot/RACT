"""B-184 and B-204: an approval screen shows the text it asks about as written, escaped.

B-184: ``wrap_cells`` split on spaces, so ``'+        return  1'`` was shown as
``'+ return 1'``: the operator approved a change whose indentation and double
spaces were not on screen. And a space before a combining mark could start a
continuation line with the mark (Hypothesis, BUILDER L-403).

B-204: four screens each had a copy of ``escape_controls`` that passed U+061C
and the zero-width characters through raw. They share ``screen_text`` now.
"""

from __future__ import annotations

import unicodedata

import pytest
from rich.cells import cell_len

from ract import approval_callback
from ract.cell_wrap import wrap_cells, wrap_exact
from ract.session_events import screen_text, visible_text
from ract.ui import allow_screens, command_screens, grant_screens, tier3_report
from ract.ui import git_screens, network_screens, posture_screens

WIDTHS = (80, 60, 40)


# ------------------------------------------------------------------ B-184: wrap_exact


def test_the_audit_example_keeps_its_spaces() -> None:
    assert wrap_exact("+        return  1", 60) == ["+        return  1"]
    assert wrap_cells("+        return  1", 60) == ["+ return 1"]  # prose wrap, unchanged


@pytest.mark.parametrize("width", WIDTHS)
def test_a_long_line_breaks_only_at_the_width_and_loses_nothing(width: int) -> None:
    line = "    value = compute(alpha,  beta,   gamma) " * 6
    lines = wrap_exact(line, width)
    assert all(cell_len(part) <= width for part in lines), lines
    assert lines[0].startswith("    value")
    rejoined = lines[0] + "".join(part[4:] for part in lines[1:])  # 4: the kept indent
    assert rejoined == line


@pytest.mark.parametrize("width", WIDTHS)
def test_a_tab_is_shown_as_a_marker(width: int) -> None:
    lines = wrap_exact("\tif x:\t\treturn", width)
    assert "\t" not in "".join(lines)
    assert "".join(lines).startswith("\\tif x:\\t\\treturn")


def test_a_mark_never_starts_a_continuation_line() -> None:
    text = ":::::::::::::::::: \u0301\u65e5"
    for wrap in (wrap_cells, wrap_exact):
        for line in wrap(text, 20)[1:]:
            stripped = line.lstrip(" ")
            assert not stripped or unicodedata.category(stripped[0]) not in {
                "Mn",
                "Mc",
                "Me",
            }, (wrap.__name__, line)


@pytest.mark.parametrize("width", WIDTHS)
def test_the_tier_2_change_is_printed_as_written(
    width: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ract.tools.write import WriteFileArgs

    body = "def f():\n        return  1\n\tpass\n" + "x = '" + "y" * 90 + "'\n"
    args = WriteFileArgs(path="AGENTS.md", content=body, create=True)
    monkeypatch.setattr(approval_callback, "_terminal_width", lambda: width + 3)
    monkeypatch.setattr(approval_callback, "read_line", lambda _p: "n")
    assert approval_callback.console_tier_2_choice("write_file", args) == "deny"
    out = capsys.readouterr().out
    assert "  +        return  1" in out  # leading spaces and the double space kept
    assert "  +\\tpass" in out  # the tab shown as a marker
    assert all(cell_len(line) <= width + 3 for line in out.splitlines()), out
    assert "y" * 30 in out.replace("\n", "")


# ------------------------------------------------------------------ B-204: one escape

HIDDEN = [
    *(chr(c) for c in range(0x200B, 0x2010)),
    *(chr(c) for c in range(0x202A, 0x202F)),
    *(chr(c) for c in range(0x2066, 0x206A)),
    "\u061c",
    "\ufeff",
    "\t",
    "\r",
    "\x1b",
]
MODULES = [allow_screens, command_screens, grant_screens, tier3_report]


@pytest.mark.parametrize("ch", HIDDEN, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_screen_escapes_the_character(module, ch: str) -> None:  # type: ignore[no-untyped-def]
    shown = module.escape_controls(f"rm -rf a{ch}b")
    assert ch not in shown
    assert shown == screen_text(f"rm -rf a{ch}b")


@pytest.mark.parametrize("ch", HIDDEN, ids=lambda c: f"U+{ord(c):04X}")
def test_the_screens_show_no_raw_character(ch: str) -> None:
    request = command_screens.CommandRequest(
        argv=("pytest", f"tests/a{ch}b.py"),
        executable=f"C:/bin/py{ch}thon.exe",
        cwd=f"/work/sp{ch}ace",
        network=False,
        sandbox_enforced=False,
    )
    screens = [
        command_screens.approval_prompt_lines(request, 60),
        allow_screens.allowed_by_rule_lines(
            ("git", f"st{ch}atus"), allow_screens.AllowRule(f"r{ch}1", ("git",)), 60
        ),
        allow_screens.entry_point_question_lines(
            allow_screens.EntryPointChange(path=f"scripts/ru{ch}n.sh", reason="written"), 60
        ),
        grant_screens.detected_runner_lines(
            grant_screens.DetectedRunner("pytest", ("pytest", f"-k{ch}x"), f"pyproject{ch}.toml"),
            60,
        ),
    ]
    for lines in screens:
        assert ch not in "".join(lines), lines


# Round-2 audit (seam 5): the batch-7 screens carried a fourth copy of the
# pre-B-204 escaper, drifted from ``visible_text`` (U+061C passed through
# raw, ``\r`` shown as ``\x0d``). They render with the canonical escaper.
DRIFTED = [git_screens, network_screens, posture_screens]
DRIFT_CHARS = ["\u061c", "\r"]


def _drifted_screen(module, ch: str) -> str:  # type: ignore[no-untyped-def]
    if module is git_screens:
        lines = module.commit_prompt_lines(
            module.CommitRequest(message=f"msg{ch}body", files=("f.py",)), 80
        )
    elif module is network_screens:
        lines = module.fetch_prompt_lines(
            module.FetchRequest(
                url=f"https://x.test/{ch}",
                host="x.test",
                allowlist_match=None,
                size_cap_kib=64,
            ),
            80,
        )
    else:
        lines = [
            module.sandbox_line(
                module.SandboxPosture(
                    backend=f"back{ch}end", posture=module.BEST_EFFORT
                )
            )
        ]
    return "".join(lines)


@pytest.mark.parametrize("ch", DRIFT_CHARS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize("module", DRIFTED, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_the_batch_7_screens_render_the_canonical_escape(module, ch: str) -> None:  # type: ignore[no-untyped-def]
    shown = _drifted_screen(module, ch)
    assert ch not in shown
    assert visible_text(ch) in shown  # U+061C as \u061c, \r as \r


def test_a_break_falls_after_a_space_when_one_fits() -> None:
    # The batch gate (L-413): at 40 columns "tests/test_calc.py" was cut in two.
    lines = wrap_exact("argv: python -m pytest tests/test_calc.py", 30)
    assert lines == ["argv: python -m pytest ", "tests/test_calc.py"]
    assert wrap_exact("x" * 50, 20) == ["x" * 20, "x" * 20, "x" * 10]  # no space: cut
