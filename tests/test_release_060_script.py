"""B-167: the 0.6.0 release script gates every machine-leaving step (B-167).

The script under test, ``scripts/release_060.py``, holds the ordered copy of
RELEASE_COMMANDS.md sections A to C. It must refuse to start without its
backups and pre-checks, and before every step that leaves the machine (a
push) it must print the command, its target and the undo, then wait for the
typed word ``yes``. Nothing here runs a real command: subprocess is mocked
throughout.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "release_060", _ROOT / "scripts" / "release_060.py"
)
release_060 = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("release_060", release_060)
assert _spec.loader is not None
_spec.loader.exec_module(release_060)

STEP_IDS = [
    "A1",
    "A2",
    "A3",
    "B1",
    "B2",
    "B3",
    "B4",
    "C1",
    "C2",
    "C3",
    "C4",
]


# ---------------------------------------------------------------------------
# The parser: sections A-C of RELEASE_COMMANDS, in order
# ---------------------------------------------------------------------------


def test_parser_has_sections_a_to_c_in_order() -> None:
    steps = release_060.parse_steps()
    assert [s.id for s in steps] == STEP_IDS
    assert [s.section for s in steps] == ["A"] * 3 + ["B"] * 4 + ["C"] * 4
    assert [s.id for s in steps] == sorted([s.id for s in steps], key=STEP_IDS.index)


def test_parser_quotes_the_release_commands_verbatim() -> None:
    steps = {s.id: s for s in release_060.parse_steps()}
    a1 = steps["A1"].commands[0]
    assert a1 == "git clone --mirror --no-local {repo} {backup}"
    c2 = steps["C2"].commands[0]
    assert c2 == "git -C {release} push --force origin main"
    assert "--tags" not in steps["C3"].commands[0]
    assert "--mirror" not in steps["C3"].commands[0]


def test_parser_collects_the_undo_from_the_board() -> None:
    steps = {s.id: s for s in release_060.parse_steps()}
    assert steps["A1"].undo == ["rm -rf {backup}"]
    assert any("tag -d v0.5.3" in u for u in steps["B4"].undo)
    assert any("push --force" in u for u in steps["C2"].undo)


def test_b2_carries_both_variants_and_b3_reuses_a3() -> None:
    steps = {s.id: s for s in release_060.parse_steps()}
    assert set(steps["B2"].variants) == {"b1", "b2"}
    assert "{patches}/*.patch" in steps["B2"].variants["b1"][0]
    assert "{patches}/with_scrub/*.patch" in steps["B2"].variants["b2"][0]
    assert steps["B3"].commands == steps["A3"].commands


# ---------------------------------------------------------------------------
# The classifier: a push leaves the machine, a local rehearsal does not
# ---------------------------------------------------------------------------


def test_classifier_push_leaves_local_steps_do_not() -> None:
    leaves = {s.id: s.leaves for s in release_060.parse_steps()}
    assert [i for i, v in leaves.items() if v] == ["C2", "C3", "C4"]
    assert release_060.command_leaves_machine(
        "git -C {release} push --force origin main"
    )
    assert release_060.command_leaves_machine(
        "git -C {release} push origin release/v0.5.3-security v0.5.3"
    )
    assert not release_060.command_leaves_machine(
        "bash {kit}/run_r001.sh {repo} {release}"
    )
    assert not release_060.command_leaves_machine(
        'git -C {release} tag -a v0.5.3 -m "RACT v0.5.3 - Security Patch"'
    )
    assert not release_060.command_leaves_machine(
        "git clone --mirror --no-local {repo} {backup}"
    )


# ---------------------------------------------------------------------------
# The typed-yes gate
# ---------------------------------------------------------------------------


def _step(step_id: str) -> release_060.Step:
    return {s.id: s for s in release_060.parse_steps()}[step_id]


def _confirm(
    step_id: str,
    *,
    typed: str | None = "yes",
    interactive: bool = True,
    understand: set[str] | None = None,
) -> tuple[bool, str]:
    printed: list[str] = []
    calls: list[str] = []

    def input_fn(prompt: str) -> str:
        calls.append(prompt)
        if typed is None:
            raise AssertionError("input must never be called")
        return typed

    ok = release_060.confirm_step(
        _step(step_id),
        params={
            "repo": "R",
            "backup": "B",
            "release": "L",
            "kit": "K",
            "patches": "P",
            "python": "Y",
        },
        variant="b1",
        understand=understand or set(),
        interactive=interactive,
        input_fn=input_fn,
        out=printed.append,
    )
    text = "\n".join(printed)
    assert printed, "the gate must print what it asks"
    if interactive:
        assert calls, "a TTY gate must ask"
    return ok, text


def test_gate_typed_yes_proceeds() -> None:
    ok, text = _confirm("C2", typed="yes")
    assert ok
    assert "git -C L push --force origin main" in text
    assert "https://github.com/LucRoot/RACT.git" in text
    assert "push --force https://github.com/LucRoot/RACT.git main" in text


def test_gate_anything_else_refuses() -> None:
    for typed in ("no", "y", "YES", "yes please", ""):
        ok, _ = _confirm("C2", typed=typed)
        assert not ok, f"typing {typed!r} must stop the release"


def test_gate_non_tty_refuses_even_when_yes_is_waiting() -> None:
    ok, text = _confirm("C2", typed="yes", interactive=False)
    assert not ok
    assert "refusing" in text.lower() or "not a tty" in text.lower()


def test_gate_non_tty_never_calls_input() -> None:
    ok, _ = _confirm("C2", typed=None, interactive=False)
    assert not ok


def test_gate_i_understand_names_the_step_and_still_prints_the_ask() -> None:
    ok, text = _confirm("C2", typed=None, interactive=False, understand={"C2"})
    assert ok
    assert "git -C L push --force origin main" in text
    assert "--i-understand" in text
    # Naming a different step does not unlock this one.
    ok, _ = _confirm("C2", typed=None, interactive=False, understand={"C3"})
    assert not ok


# ---------------------------------------------------------------------------
# The pre-flight: failures exit non-zero before any step runs
# ---------------------------------------------------------------------------


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _fake_runner(
    *,
    status: str = "",
    authors: str = "Dr. Lucas Root, Ph.D. <info@lucasroot.com>\n",
    gate_rc: int = 0,
    branch: str = "main",
    calls: list[list[str]] | None = None,
) -> object:
    """A subprocess.run stand-in: answers the pre-flight's git questions."""

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if calls is not None:
            calls.append(list(cmd))
        joined = " ".join(str(c) for c in cmd)
        if "symbolic-ref --short HEAD" in joined:
            return _completed(branch + "\n")
        if "status --porcelain" in joined:
            return _completed(status)
        if "rev-parse --is-inside-work-tree" in joined:
            return _completed("true\n")
        if "rev-parse --is-bare-repository" in joined:
            return _completed("true\n")
        if "-m pytest" in joined:
            return _completed("", gate_rc)
        if "log main..HEAD" in joined:
            return _completed(authors)
        if "branch --show-current" in joined:
            return _completed("release/v0.5.3-security\n")
        if "ls-remote" in joined:
            return _completed("0f2346b\trefs/heads/main\n")
        if "rev-parse" in joined:
            return _completed("0f2346b\n")
        if "log --oneline" in joined:
            return _completed("9398d93 release(v0.5.3): version 0.5.3\n")
        if "tag -n1" in joined:
            return _completed("v0.5.3          RACT v0.5.3 - Security Patch\n")
        if "remote -v" in joined:
            return _completed(
                "origin\thttps://github.com/LucRoot/RACT.git (fetch)\n"
                "origin\thttps://github.com/LucRoot/RACT.git (push)\n"
            )
        if "cat " in joined:
            return _completed("RACT v0.5.3 - Security Patch\n")
        if cmd[:2] == ["bash", "-c"] and "wc -l" in joined:
            return _completed("205\n")
        return _completed("")

    return run


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    repo = tmp_path / "repo"
    backup = tmp_path / "backup.git"
    release = tmp_path / "release"
    kit = tmp_path / "kit"
    patches = tmp_path / "patches"
    for d in (repo, backup, release, kit, patches / "with_scrub"):
        d.mkdir(parents=True, exist_ok=True)
    (kit / "run_r001.sh").write_text("#!/bin/bash\n")
    (kit / "terms.txt").write_text("term-one\n")
    (patches / "0001-x.patch").write_text("patch\n")
    (patches / "with_scrub" / "0001-y.patch").write_text("patch\n")
    return [
        "--repo",
        str(repo),
        "--backup",
        str(backup),
        "--release",
        str(release),
        "--kit",
        str(kit),
        "--patches",
        str(patches),
        "--variant",
        "b1",
        *extra,
    ]


def test_preflight_missing_backup_exits_non_zero_before_any_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(release_060.subprocess, "run", _fake_runner(calls=calls))
    argv = _argv(tmp_path)
    backup = tmp_path / "backup.git"
    for child in backup.iterdir():
        child.unlink()
    backup.rmdir()
    rc = release_060.main(argv)
    assert rc != 0
    out = capsys.readouterr().out
    assert "backup" in out.lower()
    ran_steps = [c for c in calls if c[:2] == ["bash", "-c"]]
    assert ran_steps == [], "no step command may run when the pre-flight fails"


def test_preflight_dirty_tree_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        release_060.subprocess,
        "run",
        _fake_runner(status=" M CHANGELOG.md\n"),
    )
    assert release_060.main(_argv(tmp_path)) != 0


def test_preflight_closed_term_gate_failure_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release_060.subprocess, "run", _fake_runner(gate_rc=1))
    assert release_060.main(_argv(tmp_path)) != 0


def test_preflight_foreign_author_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        release_060.subprocess,
        "run",
        _fake_runner(authors="Someone Else <other@example.com>\n"),
    )
    assert release_060.main(_argv(tmp_path)) != 0


def test_refuses_to_run_without_the_variant_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release_060.subprocess, "run", _fake_runner())
    argv = _argv(tmp_path)
    argv.remove("b1")
    with pytest.raises(SystemExit) as exc:
        release_060.main(argv)
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# The dry run and a full mocked run
# ---------------------------------------------------------------------------


def test_dry_run_prints_the_plan_and_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(release_060.subprocess, "run", _fake_runner(calls=calls))
    rc = release_060.main(_argv(tmp_path, "--dry-run"))
    assert rc == 0
    out = capsys.readouterr().out
    for step_id in STEP_IDS:
        assert step_id in out
    assert out.count("LEAVES THE MACHINE") == 3
    # Only the pre-flight's ref-count reads may have run; no step command did.
    step_runs = [c for c in calls if c[:2] == ["bash", "-c"] and "wc -l" not in c[2]]
    assert step_runs == []


def test_full_run_stops_at_the_first_ungated_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Non-TTY run with only C2 unlocked runs C2's push and stops at C3."""
    calls: list[list[str]] = []
    monkeypatch.setattr(release_060.subprocess, "run", _fake_runner(calls=calls))
    monkeypatch.setattr(release_060.sys.stdin, "isatty", lambda: False)
    rc = release_060.main(_argv(tmp_path, "--i-understand", "C2"))
    assert rc != 0
    pushes = [c for c in calls if c[:2] == ["bash", "-c"] and "push" in c[2]]
    assert [c[2] for c in pushes] == [
        "git -C " + str(tmp_path / "release") + " push --force origin main"
    ]
    out = capsys.readouterr().out
    assert "C3" in out


def test_full_run_with_every_leave_step_named_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(release_060.subprocess, "run", _fake_runner(calls=calls))
    monkeypatch.setattr(release_060.sys.stdin, "isatty", lambda: False)
    rc = release_060.main(
        _argv(
            tmp_path,
            "--i-understand",
            "C2,C3,C4",
        )
    )
    assert rc == 0
    pushes = [c for c in calls if c[:2] == ["bash", "-c"] and "push" in c[2]]
    assert [c[2] for c in pushes] == [
        "git -C " + str(tmp_path / "release") + " push --force origin main",
        "git -C "
        + str(tmp_path / "release")
        + " push --force origin $(git -C "
        + str(tmp_path / "release")
        + " tag -l 'v*')",
        "git -C "
        + str(tmp_path / "release")
        + " push origin release/v0.5.3-security v0.5.3",
    ]
