"""Interactive RACT session.

``ract`` with no arguments on a terminal, or ``ract repl``, opens a prompt.
Plain text is an intent and runs as a plan. Lines that start with ``/`` are
commands. Every verb in ``CLI_VERBS`` is available as a slash command, so
``/doctor``, ``/report --last`` and ``/whisper --intent '...'`` work inside the
session the same way they do on the shell line.

The session is a thin layer over :func:`ract.cli.main`. It keeps a few
settings (config path, dry-run, streaming, approval mode, session id) and turns
each line into an argv for the same dispatcher the one-shot CLI uses, so there
is one code path for running an intent and no second set of behavior to drift.

Line editing and history come from the standard library ``readline`` where the
platform has it: Linux and macOS. Python on Windows has no ``readline``, so there the
session has no history or completion. Nothing here adds a dependency.
"""

from __future__ import annotations

import _thread
import os
import shlex
import sys
import threading
import difflib
from datetime import datetime
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from rich.markup import escape

from ract import config_errors
from ract.providers import reasoning
from ract.session_events import safe_text
from ract.cell_wrap import wrap_cells
from ract.console_interrupt import read_line as console_read_line
from ract.tui import terminal_width
from ract.workspace_state import StateDirRefused, check_state_path

# Verbs that accept ``--config`` and should follow the session's config path
# when the operator did not pass one.
_CONFIG_AWARE_VERBS = frozenset({"doctor", "report"})
_STRAY_ANSWERS = frozenset({"y", "n", "yes", "no"})

HELP_ROWS: tuple[tuple[str, str], ...] = (
    ("<text>", "Run the text as an intent (same as /run <text>)."),
    ("/run <intent>", "Plan and execute an intent."),
    ("/plan <intent>", "Plan only. Shows the plan, writes nothing."),
    ("/ask <question>", "Answer a question. No plan, and no file is written."),
    ("/loop <intent>", "Run the quality-anchored loop until done or regressed."),
    (
        "/test [selectors]",
        "Run the granted test command and show the result; the next turn can act on it.",
    ),
    (
        "/set <name> <value>",
        "Change a setting: dry-run, stream, auto, mode, iterations.",
    ),
    ("/settings", "Show the current settings."),
    (
        "/model [name]",
        "Show the configured models, or switch the manager for this session.",
    ),
    (
        "/session [new|<id>]",
        "Show, restart or switch the session that carries context between turns.",
    ),
    ("/sessions", "List recent sessions: id, time, turns, cost and last request."),
    ("/context", "What the last request sent, and the room the model has."),
    ("/resume <id|latest>", "Switch to a saved session and show its last request."),
    ("/config", "Validate the active config (same as ract config validate)."),
    ("/providers", "List configured providers and the manager provider."),
    ("/permissions", "What RACT may change or send, in one screen."),
    (
        "/cost [--by KEY]",
        "Requests, tokens and bytes sent off this machine in this session; "
        "--by purpose, step or role groups the model requests.",
    ),
    (
        "/mode [MODE]",
        "plan: propose only; default: ask before each change; auto-accept: apply changes.",
    ),
    ("/diff", "Show the last turn's changes, from the copies it saved."),
    ("/todo", "The to-do list the model wrote and the harness tracks (B-177)."),
    ("/queue [drop <n>]", "Lines typed during a turn; drop one before it sends."),
    ("!<command>", "Run a command you type, as you, in this project."),
    ("/spec", "A guided walk from an idea to an approved SPEC.md (B-178)."),
    (
        "/review",
        "Go through the last turn's changes hunk by hunk: accept, reject, edit or skip.",
    ),
    (
        "/undo [--force|list]",
        "Reverse the last turn's file changes (skips files you edited since); "
        "list shows each checkpoint.",
    ),
    ("/redo [--force]", "Reverse the last /undo."),
    ("/checkpoint", "List the checkpoints, numbered, newest first."),
    (
        "/rewind",
        "Pick an earlier turn by its request and go back to it (Esc Esc where "
        "the prompt has readline).",
    ),
    (
        "/restore N [--force]",
        "Go back to checkpoint N: reverse every later turn, newest first.",
    ),
    (
        "/doctor [OPTIONS]",
        "Run setup diagnostics against the active config; --check-providers also "
        "asks each provider.",
    ),
    ("/report [--last]", "Show what the last run changed and why."),
    (
        "/<verb> ...",
        "Any other RACT verb, for example /whisper, /fence, /auction, /status.",
    ),
    ("/clear", "Clear the screen."),
    ("/help", "Show this list."),
    ("/exit", "Leave the session (Ctrl-D also works)."),
)

_BOOL_TRUE = {"on", "true", "yes", "1"}
_BOOL_FALSE = {"off", "false", "no", "0"}


@dataclass
class ReplState:
    """Settings that persist across turns in one session."""

    config: Path = Path("ract.yaml")
    dry_run: bool = False
    stream: bool = False
    auto: bool = False
    mode: str = "default"
    max_iterations: int = 10
    session_id: str = field(default_factory=lambda: time.strftime("repl-%Y%m%d-%H%M%S"))
    # True once a turn has completed and saved the session, so the next turn
    # resumes it. A failed first turn leaves this False and the next turn
    # starts the session again instead of resuming one that does not exist.
    session_started: bool = False
    turns: int = 0
    # When the session began, in the egress ledger's time format (/cost).
    started_at: str = field(default_factory=lambda: _ledger_now())


def _ledger_now() -> str:
    from ract import egress_ledger

    return egress_ledger.now()


Dispatch = Callable[[list[str]], int]


# How long Ctrl-C waits for the turn's worker before the prompt returns.
_INTERRUPT_GRACE_SECONDS = 0.3
# How long leaving the session waits for interrupted workers to clean up.
_EXIT_CLEANUP_SECONDS = 10.0  # B-146: the bound at /exit


def _review_line(config: dict) -> str:
    """The reviewer line of /model (ADR-0049 D14, B-061c)."""
    from ract.review.stage import ReviewConfigError, mode

    try:
        review = mode(config)
    except ReviewConfigError:
        return "review: off (setting not valid)"
    if review == "off":
        return "review: off"
    return f"review: {review} (same model)"


def _context_limit(project: Path, provider_config: dict[str, Any] | None) -> int | None:
    from ract.context_window import context_limit

    return context_limit(project, provider_config)


class ReplSession:
    """Read-eval-print loop over the RACT command dispatcher."""

    # The input broker of the running turn, when type-ahead is on (package 6).
    _broker: Any = None
    # Set by an interrupted turn: its queued lines wait until the operator types (package 6).
    _queue_held: bool = False

    def __init__(
        self,
        config: Path | None = None,
        *,
        dispatch: Dispatch | None = None,
        read_line: Callable[[str], str] | None = None,
        console: Any | None = None,
        verbs: tuple[str, ...] | None = None,
        history_path: Path | None = None,
    ) -> None:
        # LR:: With the real dispatcher (no test double), intents run as
        # event-driven turns (ract.session_turn): streamed, with a heartbeat,
        # interruptible with Ctrl-C. An injected dispatcher keeps the older
        # path so argv-level tests stay meaningful.
        self._event_mode = dispatch is None
        if dispatch is None or verbs is None:
            from ract import cli

            dispatch = dispatch or cli.main
            verbs = verbs if verbs is not None else cli.CLI_VERBS
        if console is None:
            from ract.tui import console as default_console

            console = default_console
        self.state = ReplState(config=config or Path("ract.yaml"))
        # B-034, OPERATOR decision 2026-10-22: a real session starts in
        # `default` (ask before changing a file). Auto-accept becomes the
        # start only after per-hunk review (B-014) exists. The status line
        # reads permission_mode(), derived from the same switch the
        # executor's approval reads, so label and behavior cannot differ.
        if self._event_mode and sys.stdin.isatty():
            self.state.auto = True
        reasoning.reset_session_effort(
            reasoning.configured_default(config or Path("ract.yaml"))
        )
        from ract.config_check import set_session_manager  # noqa: PLC0415

        set_session_manager(None)
        self._dispatch = dispatch
        # S-027: a Ctrl-C just before the read starts is raised, not held until Enter.
        self._read_line = read_line or console_read_line
        self._console = console
        self._verbs = tuple(verbs)
        self._history_path = history_path
        self._builtins: dict[str, Callable[[list[str]], bool]] = {
            "help": self._cmd_help,
            "exit": self._cmd_exit,
            "quit": self._cmd_exit,
            "run": self._cmd_run,
            "plan": self._cmd_plan,
            "ask": self._cmd_ask,
            "loop": self._cmd_loop,
            "set": self._cmd_set,
            "settings": self._cmd_settings,
            "session": self._cmd_session,
            "context": self._cmd_context,
            "sessions": self._cmd_sessions,
            "resume": self._cmd_resume,
            "config": self._cmd_config,
            "providers": self._cmd_providers,
            "model": self._cmd_model,
            "doctor": self._cmd_doctor,
            "report": self._cmd_report,
            "cost": self._cmd_cost,
            "mode": self._cmd_mode,
            "permissions": self._cmd_permissions,
            "queue": self._cmd_queue,
            "undo": self._cmd_undo,
            "diff": self._cmd_diff,
            "review": self._cmd_review,
            "redo": self._cmd_redo,
            "checkpoint": self._cmd_checkpoint,
            "restore": self._cmd_restore,
            "rewind": self._cmd_rewind,
            "clear": self._cmd_clear,
            # B-177 wiring: the to-do list the model writes and the harness tracks.
            "todo": self._cmd_todo,
            # B-178 wiring: the guided spec, from an idea to an approved SPEC.md.
            "spec": self._cmd_spec,
            # Operator order 2026-11-03 A3: the granted test command, no shortcut.
            "test": self._cmd_test,
        }
        self._events: Any = None
        self._renderer: Any = None
        self._worker_done: threading.Event | None = None
        # One per session, shared by every turn's worker (G-029).
        self._write_lock = threading.RLock()
        # Done events of interrupted turns' workers, waited for at exit only.
        self._interrupted: list[threading.Event] = []
        # Notices about the tier-3 grant for session start (B-111).
        self._tier3_notes: list[str] = []
        # The grant as the session found it, and tier 3's state (ADR-0048 D3).
        self._grant_pin: str | None = None
        self._grant_state: Any = None
        self._tier3 = "off"
        # B-113: the tier-3 mode the operator asked for (capped by the grant's
        # max_mode) and the "for this session" approvals, in memory only.
        from ract.policy.allowlist import SessionApprovals

        self._tier3_mode = "ask"
        self._tier3_session = SessionApprovals()

    # ------------------------------------------------------------------ loop

    def prompt(self) -> str:
        from ract.tui import plain_mode

        if self.state.dry_run:
            return "plan: " if plain_mode() else "plan> "
        if plain_mode():
            # Plain mode labels the operator's lines (B-041b).
            return "you: "
        return "ract> "

    def run(self) -> int:
        """Run until the operator exits. Returns a process exit code."""
        self._setup_readline()
        self._banner()
        self._resume_offer()
        if self._event_mode:
            self._start_events()
        self._sweep_step_worktrees()
        started = time.monotonic()
        reason = "error"
        try:
            while True:
                try:
                    # A line queued during the last turn runs next (package 6), before any typed line.
                    queued = self._take_queued()
                    # B-195 (e): the turn this line starts says it was queued.
                    self._from_queue = queued is not None
                    line = (
                        queued if queued is not None else self._read_line(self.prompt())
                    )
                    self._queue_held = False
                except EOFError:
                    self._console.print("")
                    reason = "eof"
                    break
                except KeyboardInterrupt:
                    # Ctrl-C at the prompt abandons the line, like a shell. A second Ctrl-C
                    # while the line is cleared is still a stop, not a traceback (package P).
                    try:
                        self._console.print("")
                    except KeyboardInterrupt:
                        pass
                    continue
                if not self.handle(line):
                    reason = "exit"
                    break
        finally:
            self._save_history()
            cleanup = self._finish_interrupted_workers()
            if self._events is not None:
                # The last event of every session (docs/EVENTS_SESSION.md).
                ended: dict[str, Any] = {
                    "reason": reason,
                    "turns": self.state.turns,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                }
                if cleanup is not None:
                    ended["cleanup"] = cleanup
                self._events.emit("session.ended", ended)
            if self._renderer is not None:
                self._renderer.close()
        return 0

    def handle(self, line: str) -> bool:
        """Handle one input line. Returns False when the session should end."""
        text = line.strip()
        if not text:
            return True
        if text.startswith("/"):
            return self._handle_command(text)
        if text.startswith("!"):
            return self._cmd_shell(text[1:].strip())
        if text in {"exit", "quit"}:
            return False
        if text.lower() in _STRAY_ANSWERS:
            # D4: an approval answer reaches this line only when no question is open.
            self._console.print(
                "no question is waiting; to send that text as a request, add a word to it"
            )
            return True
        self._run_intent(text)
        return True

    def _cmd_shell(self, command: str) -> bool:
        """``!<command>``: run a command the operator typed, as the operator.

        CLI_EXPECTATIONS.md row 2 (operator ruling 2026-11-03): a daily CLI
        user expects a shell escape. Only a line typed at the prompt reaches
        this path — the model never does — so no plan, no approval question
        and no grant stand between the keystrokes and the run; the
        keystrokes are the consent. Where this machine cannot confine
        commands the line says so, as it does for every command RACT runs.
        """
        if not command:
            self._console.print("usage: !<command>  (runs it in this project, as you)")
            return True
        import subprocess

        project = self.state.config.resolve().parent
        self._console.print(
            f"running as you, in {project}: {command}"
        )
        print("[ract] best effort here: this machine cannot confine the command")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(project),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            self._console.print(f"not run: {exc}")
            return True
        if proc.stdout:
            for out_line in proc.stdout.splitlines()[:60]:
                print(out_line)
        if proc.stderr:
            for err_line in proc.stderr.splitlines()[:20]:
                print(err_line, file=sys.stderr)
        if proc.returncode:
            self._console.print(f"exit {proc.returncode}")
        else:
            self._console.print("exit 0")
        return True

    # -------------------------------------------------------------- commands

    def _handle_command(self, text: str) -> bool:
        try:
            parts = shlex.split(text[1:])
        except ValueError as exc:
            self._console.error(f"could not parse that command: {exc}")
            return True
        if not parts:
            return True
        name, args = parts[0].lower(), parts[1:]
        handler = self._builtins.get(name)
        if handler is not None:
            return handler(args)
        if name in self._verbs:
            self._run_verb(name, args)
            return True
        # Standard 8: a near miss gets the nearest command, not only a pointer to /help.
        known = sorted({*self._builtins, *self._verbs})
        near = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
        if near:
            self._console.error(
                f"unknown command /{escape(name)}. Did you mean /{escape(near[0])}?"
            )
        else:
            self._console.error(
                f"unknown command /{escape(name)}. Type /help for the list."
            )
        return True

    def _cmd_help(self, args: list[str]) -> bool:
        self._console.table(
            "RACT session",
            ["Command", "What it does"],
            [[escape(cell) for cell in row] for row in HELP_ROWS],
        )
        return True

    def _cmd_exit(self, args: list[str]) -> bool:
        return False

    def _cmd_clear(self, args: list[str]) -> bool:
        self._console.clear_screen()
        return True

    def _cmd_run(self, args: list[str]) -> bool:
        intent = " ".join(args).strip()
        if not intent:
            self._console.error("usage: /run <intent>")
            return True
        self._run_intent(intent)
        return True

    def _cmd_plan(self, args: list[str]) -> bool:
        intent = " ".join(args).strip()
        if not intent:
            self._console.error("usage: /plan <intent>")
            return True
        self._run_intent(intent, dry_run=True)
        return True

    def _cmd_ask(self, args: list[str]) -> bool:
        question = " ".join(args).strip()
        if not question:
            self._console.error("usage: /ask <question>")
            return True
        self._run_intent(question, ask=True)
        return True

    def _cmd_loop(self, args: list[str]) -> bool:
        intent = " ".join(args).strip()
        if not intent:
            self._console.error("usage: /loop <intent>")
            return True
        self._run_intent(intent, loop=True)
        return True

    def _cmd_doctor(self, args: list[str]) -> bool:
        self._run_verb("doctor", args)
        return True

    def _cmd_report(self, args: list[str]) -> bool:
        self._run_verb("report", args or ["--last"])
        return True

    # B-085: the summary's caps (standard 13).
    _DIFF_FILES = 20
    _DIFF_LINES = 2000

    def _cmd_todo(self, args: list[str]) -> bool:
        """``/todo``: the to-do list the model wrote and the harness tracks (B-177)."""
        from ract.todo_list import load as load_todo
        from ract.todo_list import todo_lines

        folder = self.state.config.resolve().parent / ".ract"
        todo = load_todo(folder)
        for line in todo_lines(todo, self._render_width()):
            print(line)
        return True

    def _cmd_test(self, args: list[str]) -> bool:
        """``/test``: run the granted test command; the result feeds the next turn.

        The run goes through the same tier-3 path as a model-requested
        command (operator order 2026-11-03 A3): the same grant and pin
        checks, the same test rule, the same sandbox and the same command
        record. The operator typing ``/test`` is the approval, and
        ``run_tests`` can only run the grant's test rule. With no grant,
        nothing runs and the on-ramp prints instead.
        """
        from ract.policy import tier3
        from ract.tools import ToolRefused
        from ract.tools.tests_tool import RunTestsArgs, run_tests

        project = self.state.config.resolve().parent
        grant = getattr(self, "_grant_state", None)
        if grant is None or not getattr(grant, "holds", False):
            self._print_wrapped(
                "no grant yet, so /test has nothing to run. Turn it on once: "
                "`ract policy init --guided` asks, then RACT can run your "
                "tests when you ask."
            )
            return True

        def approve(facts: dict) -> bool:  # noqa: ARG001 - the keystroke answered
            # The operator asked with /test; run_tests still only allows the
            # grant's test rule, so this approves that and nothing else.
            return True

        try:
            ctx = tier3.for_project(
                project,
                approve=approve,
                expected_pin=self._grant_pin,
                mode=self._tier3_mode,
                session_approvals=self._tier3_session,
            )
            with tier3.bound(ctx):
                result = run_tests(
                    project,
                    RunTestsArgs(
                        selectors=args,
                        reason="the operator asked with /test",
                    ),
                )
        except ToolRefused as exc:
            self._print_wrapped(f"not run: {exc}")
            if getattr(exc, "hint", ""):
                self._print_wrapped(f"hint: {exc.hint}")
            return True
        except ValueError as exc:
            self._print_wrapped(f"not run: {exc}")
            return True
        except Exception as exc:  # noqa: BLE001 - /test never ends the session
            self._print_wrapped(f"/test failed: {type(exc).__name__}: {exc}")
            return True
        facts = result.facts
        for line in result.text.splitlines()[:40]:
            print(line)
        if result.truncated:
            print("... (output trimmed; the full record is in the command record)")
        passed = facts.get("passed")
        exit_code = facts.get("exit_code")
        if passed is True:
            word = "passed"
        elif passed is False:
            word = "FAILED"
        else:
            word = "finished"
        print(f"tests: {word} (exit {exit_code})")
        self._pending_test_fact = f"[tests from /test: {word} (exit {exit_code})]"
        return True

    def _cmd_spec(self, args: list[str]) -> bool:
        """``/spec``: the guided walk from an idea to an approved SPEC.md (B-178)."""
        from ract.spec_guide import walk as spec_walk

        project = self.state.config.resolve().parent
        spec_walk(project, ask=self._read_line, width=self._render_width())
        return True

    def _cmd_diff(self, args: list[str]) -> bool:
        """The last turn's diff, read from its saved copies (B-085)."""
        from ract import undo_backup
        from ract.diff_render import draw_turn_diff

        turn, changes, notes = undo_backup.last_turn_changes(
            self.state.config.resolve().parent
        )
        if turn is None:
            self._print_wrapped("no turn has changed a file yet")
            return True
        for note in notes:
            self._print_wrapped(safe_text(note))
        lines = draw_turn_diff(
            changes[: self._DIFF_FILES],
            width=self._render_width(),
            max_lines=self._DIFF_LINES,
        )
        for line in lines:
            self._console.print(escape(line))
        if len(changes) > self._DIFF_FILES:
            self._print_wrapped(
                f"{len(changes) - self._DIFF_FILES} more changed files are not shown"
            )
        return True

    def _cmd_review(self, args: list[str]) -> bool:
        """The last turn's change, hunk by hunk: accept, reject, edit or skip (B-014c)."""
        from ract import review_hunks

        width = self._render_width()

        def ask(question: str) -> str | None:
            # The question folds to the width; the answer goes on its last line.
            lines = wrap_cells(question, max(width - 3, 20)) or [""]
            for line in lines[:-1]:
                self._console.print(escape(line))
            try:
                return self._read_line(lines[-1] + " ")
            except EOFError:
                return None

        def show(line: str) -> None:
            self._console.print(escape(line))

        try:
            review = review_hunks.review_last_turn(
                self.state.config.resolve().parent, ask, show, width=width
            )
        except KeyboardInterrupt:
            self._console.print("")
            self._print_wrapped(
                "review interrupted: the file asked about is left as it is; "
                "files answered before it keep their answers"
            )
            return True
        if review.turn is None:
            self._print_wrapped("no turn has changed a file yet")
            return True
        for line in review_hunks.report_lines(review) or ["nothing to review"]:
            self._print_wrapped(line)
        return True

    def _undo_list(self) -> bool:
        """Each checkpoint: time, kind, turn and the files it holds (B-085)."""
        from ract import undo_backup

        rows = undo_backup.checkpoints(self.state.config.resolve().parent)
        if not rows:
            self._print_wrapped(
                "no checkpoints yet: a turn that changes a file makes one"
            )
            return True
        for row in rows:
            files = [*row["saved"], *row["created"]]
            shown = ", ".join(safe_text(f) for f in files[:5])
            more = f" and {len(files) - 5} more" if len(files) > 5 else ""
            state = " (undone)" if row["done"] else ""
            self._print_wrapped(
                f"{row['time']} {row['kind']} {safe_text(row['turn'])}{state}: "
                f"{len(files)} file{'s' if len(files) != 1 else ''}: {shown}{more}"
            )
        return True

    def _cmd_undo(self, args: list[str]) -> bool:
        from ract import undo_backup

        if args[:1] == ["list"]:
            return self._undo_list()
        result = undo_backup.undo(
            self.state.config.resolve().parent, force="--force" in args
        )
        self._print_reversal(result, "undo")
        return True

    def _cmd_redo(self, args: list[str]) -> bool:
        from ract import undo_backup

        result = undo_backup.redo(
            self.state.config.resolve().parent, force="--force" in args
        )
        self._print_reversal(result, "redo")
        return True

    def _print_reversal(self, result: Any, verb: str) -> None:
        """Print an undo or redo result. B-105: each verb says what it did to a file.

        ``undo`` puts a file back to the version before the turn; ``redo`` applies
        the turn's change again. Both words come from the verb here, not from the
        shared result text, which says "restored" for both.
        """
        for line in result.lines(verb):
            if verb == "redo" and line.startswith("restored "):
                path = line[len("restored ") :]
                self._print_wrapped(f"re-applied {safe_text(path)}")
            elif verb == "undo" and line.startswith("restored "):
                path = line[len("restored ") :]
                self._print_wrapped(
                    f"restored {safe_text(path)} to the version before the turn"
                )
            else:
                self._print_wrapped(line)

    def _turn_checkpoints(self) -> list[dict[str, Any]]:
        """The checkpoints /restore can go back to: turns and redos, newest first."""
        from ract import undo_backup

        rows = undo_backup.checkpoints(self.state.config.resolve().parent)
        return [row for row in rows if row["kind"] in {"turn", "redo"}]

    def _cmd_checkpoint(self, args: list[str]) -> bool:
        """``/checkpoint``: each checkpoint numbered, newest first (B-110 D6)."""
        from ract.ui.workspace_screens import Checkpoint, checkpoint_lines

        rows = self._turn_checkpoints()
        # MASON's view (B-110 D6); 1 is the newest, as /restore N counts.
        for line in checkpoint_lines(
            [
                Checkpoint(
                    number=n,
                    when=row["time"],
                    turn=row["turn"],
                    files=len([*row["saved"], *row["created"]]),
                    undone=bool(row["done"]),
                    names=tuple(str(f) for f in [*row["saved"], *row["created"]]),
                )
                for n, row in enumerate(rows, start=1)
            ],
            self._render_width(),
        ):
            self._print_wrapped(line)
        if not rows:
            return True
        self._print_wrapped(
            "/restore N goes back to checkpoint N; /undo reverses the newest"
        )
        return True

    def _cmd_rewind(self, args: list[str]) -> bool:
        """``/rewind``: the turns by their requests; the one picked is restored (J7)."""
        rows = self._turn_checkpoints()
        live = [row for row in rows if not row["done"]]
        if len(live) < 2:
            self._print_wrapped(
                "nothing to rewind to: it takes two turns that changed files"
            )
            return True
        for n, row in enumerate(rows, start=1):
            if row["done"]:
                continue
            asked = safe_text(row.get("request") or "") or "(request not recorded)"
            self._print_wrapped(f"{n}. {row['time']}: {asked}")
        width = self._render_width()
        question = "rewind to which turn? (a number; Enter keeps everything)"
        lines = wrap_cells(question, max(width - 3, 20)) or [""]
        for line in lines[:-1]:
            self._console.print(escape(line))
        try:
            answer = self._read_line(lines[-1] + " ").strip()
        except EOFError:
            answer = ""
        if not answer:
            self._print_wrapped("nothing rewound")
            return True
        return self._cmd_restore([answer])

    def _cmd_restore(self, args: list[str]) -> bool:
        """``/restore N``: reverse every turn after checkpoint N (B-110 D6)."""
        from ract import undo_backup

        numbers = [a for a in args if a != "--force"]
        rows = self._turn_checkpoints()
        if (
            len(numbers) != 1
            or not numbers[0].isdigit()
            or not (1 <= int(numbers[0]) <= len(rows))
        ):
            self._print_wrapped(
                f"usage: /restore N, where N is a checkpoint from /checkpoint (1 to {len(rows)})"
                if rows
                else "no checkpoints yet: a turn that changes a file makes one"
            )
            return True
        n = int(numbers[0])
        if n == 1:
            self._print_wrapped(
                "checkpoint 1 is the newest: the files are already as it left them"
            )
            return True
        from ract.ui.workspace_screens import restore_preview_lines

        root = self.state.config.resolve().parent
        try:
            # MASON's view (B-110 D6): what goes back and what is left alone, first.
            back, left_alone = undo_backup.restore_preview(
                root, rows[n - 1]["turn"], force="--force" in args
            )
            for line in restore_preview_lines(
                n, back, left_alone, self._render_width()
            ):
                self._print_wrapped(line)
            results = undo_backup.restore(
                root,
                rows[n - 1]["turn"],
                force="--force" in args,
            )
        except ValueError as exc:
            self._print_wrapped(f"restore refused: {exc}")
            return True
        for result in results:
            for line in result.lines("restore"):
                self._print_wrapped(line)
        if self._events is not None:
            # B-195 (f): documented, never emitted until now.
            self._events.emit(
                "session.rewound",
                {
                    "to_turn": n,
                    "scope": "code",
                    "restored": sum(len(r.restored) + len(r.removed) for r in results),
                    "skipped": [
                        {"path": path, "reason": "changed since"}
                        for r in results
                        for path in r.skipped
                    ]
                    + [
                        {"path": path, "reason": why}
                        for r in results
                        for path, why in r.refused
                    ],
                },
            )
        stopped = results and (results[-1].skipped or results[-1].refused)
        self._print_wrapped(
            f"stopped before checkpoint {n}: a later turn kept a file you changed"
            if stopped
            else f"back at checkpoint {n}; /redo brings back the last turn reversed"
        )
        return True

    # B-034: the session's permission mode, made of the two switches it
    # already had (dry-run, auto) and shown in the status line.
    # B-191: the file-change mode (/mode) and the tier-3 mode (/permissions
    # ask|allowlist) are two settings; each text names which one it is.
    _MODE_TEXT = {
        "plan": "File changes: plan: the planner proposes; nothing runs and nothing is written",
        "default": "File changes: default: RACT asks before each step that changes a file",
        "auto-accept": (
            "File changes: auto-accept: changes are applied without asking "
            "(/undo reverses a turn)"
        ),
    }
    _MODE_ALIASES = {
        "ask": "default",
        "accept-edits": "auto-accept",
        "edits": "auto-accept",
    }

    def permission_mode(self) -> str:
        if self.state.dry_run:
            return "plan"
        return "default" if self.state.auto else "auto-accept"

    def _cmd_queue(self, args: list[str]) -> bool:
        """``/queue`` lists the lines typed during a turn; ``/queue drop <n>`` withdraws one (package 6)."""
        from ract.ui import queue_view as qv

        width = terminal_width()
        model = (
            self._broker.queue.model if self._broker is not None else qv.QueueModel()
        )
        if not args:
            for line in qv.list_lines(model, width):
                self._console.print(escape(line))
            return True
        if args[0] != "drop":
            self._print_wrapped("usage: /queue, or /queue drop <n>")
            return True
        argument = " ".join(args[1:])
        text = argument.strip()
        if (
            self._broker is None
            or not text.isdigit()
            or not 1 <= int(text) <= len(model.items)
        ):
            _, lines = qv.drop_message(model, argument, width)
            for line in lines:
                self._console.print(escape(line))
            return True
        position = int(text)
        removed = model.items[position - 1]
        self._broker.queue.cancel(position)
        self._print_wrapped(f"dropped {removed.id}: {removed.text}")
        return True

    def _cmd_permissions(self, args: list[str]) -> bool:
        """What RACT may change or send, in one screen (standard 13).

        ``/permissions lock`` closes the unlock window (ADR-0048 D2).
        """
        from ract.policy.cli import permission_lines
        from ract.policy.unlock import SESSION_WINDOW

        if args[:1] == ["resume"]:
            # The operator confirms at the terminal (D3, G-216 W6): what changed
            # is shown, and only a y pins the grant as it is now.
            from ract.policy.cli import grant_changes
            from ract.policy.grant import load_grant

            project = self.state.config.resolve().parent
            try:
                grant = load_grant(project)
            except Exception as exc:  # noqa: BLE001 - a grant that cannot be read opens nothing
                print(f"[repl] the tier-3 grant was not read: {exc}", flush=True)
                self._print_wrapped("The grant cannot be read; nothing changed.")
                return True
            self._print_wrapped("Since this session pinned the grant:")
            for line in grant_changes(self._grant_state, grant):
                self._print_wrapped(f"  {line}")
            try:
                answer = self._read_line("Pin this grant for the session? [y/N]: ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in {"y", "yes"}:
                self._print_wrapped(
                    "Nothing changed: tier 3 stays as it was until you confirm."
                )
                return True
            facts = self._tier3_facts(grant)
            for line in self._tier3_notes:
                self._print_wrapped(line)
            self._print_wrapped(f"Tier 3 now: {facts['tier3_status']}")
            if self._events is not None:
                self._events.emit(
                    "mode.changed",
                    {
                        "mode": self.permission_mode(),
                        "tier3": facts["tier3"],
                        "by": "operator",
                    },
                )
            return True
        if args[:1] in (["allowlist"], ["ask"]):
            return self._set_tier3_mode(args[0])
        if args[:1] == ["lock"]:
            SESSION_WINDOW.lock()
            self._print_wrapped(
                "Signing key locked: the next signature asks for the passphrase."
            )
            return True
        self._print_wrapped(self._MODE_TEXT[self.permission_mode()])
        self._print_wrapped(
            "Network: requests go only to the providers named in ract.yaml; "
            "/cost lists what was sent."
        )
        for line in permission_lines(self.state.config.resolve().parent):
            self._print_wrapped(line)
        from ract.ui.allow_screens import SessionApproval, session_approvals_lines

        self._print_wrapped(f"Tier-3 mode this session: {self._tier3_mode}")
        for line in session_approvals_lines(
            [SessionApproval(prefix) for prefix in self._tier3_session.listed()],
            self._render_width(),
        ):
            self._print_wrapped(line)
        self._print_wrapped(
            "Repository commands (hooks, test gates) run only after you trust this "
            "repository: ract trust."
        )
        return True

    def _tier3_now(self) -> str:
        """The tier-3 state events and the status line show (B-195 d).

        ``off`` or ``suspended`` from the grant; otherwise the session's mode
        (``ask`` or ``allowlist``). ``/mode`` sent ``off`` whatever it was.
        """
        base = getattr(self, "_tier3", "off")
        if base in ("off", "suspended"):
            return base
        return self._tier3_mode

    def _set_tier3_mode(self, wanted: str) -> bool:
        """``/permissions allowlist`` or ``ask`` (B-113, D6): only up to the grant's max_mode."""
        grant = self._grant_state
        policy = getattr(grant, "policy", None)
        if wanted == "allowlist" and (
            policy is None or not grant.holds or policy.max_mode != "allowlist"
        ):
            self._print_wrapped(
                "allowlist mode needs a grant that holds with max_mode: allowlist; "
                "tier 3 stays in ask mode"
            )
            return True
        self._tier3_mode = wanted
        if self._events is not None:
            # B-195 (d): the change is an event, with the status line's words.
            from datetime import date

            from ract.policy.cli import tier_state_of
            from ract.ui.tier_status_view import status_line

            state, _why = tier_state_of(grant, wanted)
            self._events.emit(
                "mode.changed",
                {
                    "mode": self.permission_mode(),
                    "tier3": self._tier3_now(),
                    "tier3_status": status_line(state, date.today()),
                    "by": "operator",
                },
            )
        self._print_wrapped(
            "Tier-3 commands: allowlist: a command that matches an allow rule runs "
            "without asking; tier 2, the always-ask list and a changed test or "
            "runner file still ask"
            if wanted == "allowlist"
            else "Tier-3 commands: ask: every command asks before it runs"
        )
        return True

    def _cmd_mode(self, args: list[str]) -> bool:
        if not args:
            self._print_wrapped(self._MODE_TEXT[self.permission_mode()])
            return True
        wanted = self._MODE_ALIASES.get(args[0].lower(), args[0].lower())
        if wanted == "unrestricted":
            self._console.error(
                "unrestricted needs the tier-3 policy (B-020), which this release "
                "does not have; the modes are plan, default and auto-accept"
            )
            return True
        if wanted not in self._MODE_TEXT:
            self._console.error("mode is plan, default or auto-accept")
            return True
        if wanted == "default" and not sys.stdin.isatty():
            self._console.error("default mode asks before changes and needs a terminal")
            return True
        self.state.dry_run = wanted == "plan"
        self.state.auto = wanted == "default"
        if self._events is not None:
            self._events.emit(
                "mode.changed",
                {"mode": wanted, "tier3": self._tier3_now(), "by": "operator"},
            )
        self._print_wrapped(self._MODE_TEXT[wanted])
        return True

    def _cmd_cost(self, args: list[str]) -> bool:
        from ract import egress_ledger

        by = "purpose"
        if args:
            # V7-08: /cost --by purpose|step|role (also --by=step).
            flag, _, value = args[0].partition("=")
            value = value or (args[1] if len(args) > 1 else "")
            if flag != "--by" or value not in egress_ledger.GROUP_KEYS:
                self._print_wrapped("usage: /cost [--by purpose|step|role]")
                return True
            by = value
        records = egress_ledger.since(
            egress_ledger.read(), self.state.started_at, this_process=True
        )
        for line in egress_ledger.describe(records, by=by):
            self._print_wrapped(line)
        self._print_wrapped(
            f"ledger: {egress_ledger.ledger_path()} (ract doctor --egress for history)"
        )
        return True

    def _cmd_config(self, args: list[str]) -> bool:
        self._run_verb(
            "config", args or ["validate", "--config", str(self.state.config)]
        )
        return True

    def _cmd_model(self, args: list[str]) -> bool:

        import yaml

        from ract import trust
        from ract.config_check import resolve_manager_provider
        from ract.model_view import model_blocks

        try:
            config = yaml.safe_load(self.state.config.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            self._console.error(
                f"could not read {self.state.config}: {config_errors.yaml_problem(exc)}"
            )
            return True
        providers = config.get("providers") if isinstance(config, dict) else None
        if not isinstance(providers, dict) or not providers:
            self._console.error(f"no providers in {self.state.config}.")
            return True
        if args:
            if args[0] not in providers:
                names = ", ".join(safe_text(str(n)) for n in providers)
                self._console.error(
                    f"no provider named '{escape(safe_text(args[0]))}'. valid names: {names}"
                )
                return True
            from ract import config_check, trust  # noqa: PLC0415

            slot = providers[args[0]]
            url = (
                slot.get("url") or slot.get("base_url")
                if isinstance(slot, dict)
                else None
            )
            name = escape(safe_text(args[0]))
            root = self.state.config.resolve().parent
            if (
                isinstance(url, str)
                and url
                and trust.repository_named_host(url) is not None
                and not trust.is_trusted(root)
            ):
                self._console.error(
                    f"provider '{name}' uses a host that this repository's ract.yaml named. "
                    "Run `ract trust` to allow it, then switch again."
                )
                return True
            config_check.set_session_manager(args[0])
            self._console.success(
                f"manager provider is now '{name}' for this session; "
                f"{escape(safe_text(self.state.config.name))} is unchanged"
            )
            return True
        manager, _ = resolve_manager_provider(config)
        named = {
            name
            for name, slot in providers.items()
            if isinstance(slot, dict)
            and isinstance(slot.get("url") or slot.get("base_url"), str)
            and trust.repository_named_host(
                cast(str, slot.get("url") or slot.get("base_url"))
            )
        }
        width = terminal_width()
        for line in model_blocks(providers, manager or "", named, width):
            self._console.print(escape(line))
        self._console.print(escape(_review_line(config)))
        return True

    def _cmd_providers(self, args: list[str]) -> bool:
        import yaml

        from ract.config_check import resolve_manager_provider

        try:
            config = yaml.safe_load(self.state.config.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            self._console.error(
                f"could not read {self.state.config}: {config_errors.yaml_problem(exc)}"
            )
            return True
        providers = config.get("providers") if isinstance(config, dict) else None
        if not isinstance(providers, dict) or not providers:
            self._console.error(
                f"no providers in {self.state.config}. Run ract setup in another terminal to fix that."
            )
            return True
        manager, error = resolve_manager_provider(config)
        rows = []
        for name, slot in providers.items():
            slot = slot if isinstance(slot, dict) else {}
            role = "manager" if name == manager else ""
            rows.append(
                [
                    name,
                    role,
                    slot.get("adapter", ""),
                    slot.get("model", ""),
                    slot.get("url", ""),
                ]
            )
        self._console.table(
            "Providers", ["name", "role", "adapter", "model", "url"], rows
        )
        if error:
            self._console.warning(error)
        return True

    def _cmd_settings(self, args: list[str]) -> bool:
        s = self.state
        rows = [
            ["config", str(s.config)],
            ["dry-run", _flag(s.dry_run)],
            ["stream", _flag(s.stream)],
            ["auto (approve each step)", _flag(s.auto)],
            ["mode", s.mode],
            ["iterations (for /loop)", str(s.max_iterations)],
            [
                "session",
                f"{s.session_id}{' (resumes next turn)' if s.session_started else ''}",
            ],
            ["turns this session", str(s.turns)],
            ["reasoning effort", reasoning.session_effort()],
        ]
        self._console.table("Settings", ["setting", "value"], rows)
        return True

    def _cmd_set(self, args: list[str]) -> bool:
        if len(args) != 2:
            self._console.error(
                "usage: /set <dry-run|stream|task|iterations|reasoning> <value>"
            )
            return True
        name, value = args[0].lower().replace("_", "-"), args[1].lower()
        s = self.state
        if name == "auto":
            # B-191: "/set auto on" selected the mode that asks, the opposite of
            # /mode auto-accept. It is retired; the line names what to type.
            self._console.error(
                "/set auto is retired: /mode default asks before each change, "
                "/mode auto-accept applies changes without asking"
            )
            return True
        if name == "mode":
            # B-191: renamed so it is not read as /mode; the old name still
            # works for now and says the new one.
            self._console.info("/set mode is now /set task")
            name = "task"
        if name in {"dry-run", "stream"}:
            if value not in _BOOL_TRUE | _BOOL_FALSE:
                self._console.error(f"{name} takes on or off, not '{escape(value)}'")
                return True
            setattr(s, name.replace("-", "_"), value in _BOOL_TRUE)
        elif name == "task":
            if value not in {"default", "documentation", "git"}:
                self._console.error("task is default, documentation or git")
                return True
            s.mode = value
        elif name == "reasoning":
            try:
                reasoning.set_session_effort(value)
            except ValueError as exc:
                self._console.error(escape(str(exc)))
                return True
        elif name == "iterations":
            try:
                count = int(value)
            except ValueError:
                count = 0
            if count < 1:
                self._console.error("iterations must be a whole number of 1 or more")
                return True
            s.max_iterations = count
        else:
            self._console.error(f"unknown setting '{escape(name)}'")
            return True
        self._console.success(f"{name} = {value}")
        return True

    def _cmd_session(self, args: list[str]) -> bool:
        s = self.state
        if not args:
            self._console.info(
                f"session {s.session_id}"
                + (" (resumes next turn)" if s.session_started else " (not started)")
            )
            return True
        target = args[0]
        s.session_id = (
            time.strftime("repl-%Y%m%d-%H%M%S") if target == "new" else target
        )
        # Switching to a named session assumes it already exists; "new" does not.
        s.session_started = target != "new"
        self._follow_session()
        self._console.success(f"session = {s.session_id}")
        return True

    def _follow_session(self) -> None:
        """B-195 (f): events carry the active session's id, not the first one's."""
        if self._events is not None:
            self._events.session = self.state.session_id

    @staticmethod
    def _saved_turns(directory: Path, session_id: str) -> int:
        """How many turns a saved session holds, or 0 when that cannot be read."""
        import json

        try:
            data = json.loads((directory / f"{session_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[repl] the session's turns were not counted: {exc}", flush=True)
            return 0
        if not isinstance(data, dict):
            return 0
        turns = data.get("turns", data.get("outcomes"))  # the run layer keeps outcomes
        return len(turns) if isinstance(turns, list) else 0

    def _cmd_context(self, args: list[str]) -> bool:
        """What the last request sent and the room left, from records already on disk.

        Reads the egress ledger only: no request, no event (B-032b).
        """
        from ract import egress_ledger
        from ract.context_view import context_lines

        try:
            records = egress_ledger.read()
        except OSError:
            records = []
        # No probe result is stored, so the window is unknown here.
        for line in context_lines(records, None, width=self._render_width()):
            self._console.print(line)
        return True

    def _print_wrapped(self, text: str) -> None:
        """Print a line folded to the terminal width, continuation lines indented (package A)."""
        # By terminal columns (package I): a wide character is two columns. A path has no
        # spaces to break at, so it folds rather than overflows.
        for line in wrap_cells(text, terminal_width(), subsequent_indent="  ") or [""]:
            self._console.print(escape(line))

    def _render_width(self) -> int:
        """The width the renderer fits its lines to: the terminal, between 40 and 80 (B-041c)."""
        import shutil

        return max(40, min(80, shutil.get_terminal_size((80, 24)).columns))

    def _cmd_sessions(self, args: list[str]) -> bool:
        from ract.session_listing import LIST_LIMIT, list_rows, sessions_dir

        rows, total = list_rows(sessions_dir(self.state.config))
        if not rows:
            self._print_wrapped("no sessions yet: a request you type starts one")
            return True
        table = [
            [
                escape(row.session_id),
                time.strftime("%Y-%m-%d %H:%M", time.localtime(row.updated)),
                "-",
                "-",
                escape(row.request or f"unreadable session ({row.unreadable})"),
            ]
            for row in rows
        ]
        self._console.table(
            "Sessions", ["Id", "Updated", "Turns", "Cost", "Last request"], table
        )
        if total > LIST_LIMIT:
            self._console.info(f"{len(rows)} of {total} sessions")
        return True

    def _cmd_resume(self, args: list[str]) -> bool:
        from ract.session_listing import (
            closest_id,
            find_row,
            latest_row,
            list_rows,
            sessions_dir,
        )
        from ract.undo_backup import require_name

        if len(args) != 1:
            self._console.error(
                "usage: /resume <id|latest>. /sessions lists the saved ids."
            )
            return True
        directory = sessions_dir(self.state.config)
        if args[0] == "latest":
            row = latest_row(directory)
            if row is None:
                _, total = list_rows(directory, limit=0)
                self._console.info(
                    "no sessions yet: a request you type starts one"
                    if total == 0
                    else "no readable session to resume"
                )
                return True
        else:
            try:
                session_id = require_name(args[0], "session id")
            except ValueError:
                self._console.error(
                    f"'{escape(args[0][:50])}' is not a session id; not resumed"
                )
                return True
            row = find_row(directory, session_id)
            if row is None:
                hint = closest_id(directory, session_id)
                suffix = f"; did you mean {escape(hint)}?" if hint else ""
                self._console.error(f"no session {escape(session_id)}{suffix}")
                return True
        if row.unreadable:
            self._console.error(
                f"unreadable session: {escape(row.session_id)} ({row.unreadable}); "
                "not resumed"
            )
            return True
        s = self.state
        resumed_from = s.session_id
        s.session_id = row.session_id
        s.session_started = True
        # Session approvals are never restored by /resume (ADR-0047 D6).
        from ract import tier2_approvals

        tier2_approvals.forget(row.session_id)
        self._follow_session()
        if self._events is not None:
            # B-195 (f): documented, never emitted until now.
            self._events.emit(
                "session.resumed",
                {
                    **self._session_facts(),
                    "resumed_from": resumed_from,
                    "turns": self._saved_turns(directory, row.session_id),
                },
            )
        self._console.success(
            f"resumed {escape(row.session_id)}, last request: {escape(row.request)}"
        )
        return True

    # ------------------------------------------------------------- execution

    def build_run_argv(
        self,
        intent: str,
        *,
        dry_run: bool | None = None,
        loop: bool = False,
        ask: bool = False,
    ) -> list[str]:
        """Turn an intent and the current settings into a dispatcher argv."""
        s = self.state
        dry = s.dry_run if dry_run is None else dry_run
        # ``run`` first and the intent last, after ``--``: an intent that equals a
        # verb name ("docs") or starts with a dash must stay an intent.
        argv = ["run", "--config", str(s.config)]
        if s.mode != "default":
            argv += ["--mode", s.mode]
        if s.auto:
            argv.append("--auto")
        if s.stream:
            argv.append("--stream")
        if loop:
            # --loop and --dry-run are mutually exclusive in the CLI.
            argv += ["--loop", "--max-iterations", str(s.max_iterations)]
        elif dry:
            argv.append("--dry-run")
        elif ask:
            argv.append("--ask")
        # Carry context between turns. A dry run never saves a session, so it
        # neither starts nor resumes one.
        if not dry and not loop:
            argv += ["--session", s.session_id]
            if s.session_started or self._session_saved():
                argv.append("--resume")
        argv += ["--", intent]
        return argv

    def _session_saved(self) -> bool:
        """True when the run layer has already saved this session to disk.

        LR:: A turn that fails after planning starts still saves its session.
        Tracking only successful turns left the next turn without ``--resume``,
        and every later intent failed with "Session ... already exists" until
        the operator found ``/session new``. The file on disk is the fact.
        """
        sessions = self.state.config.parent / ".ract" / "sessions"
        return (sessions / f"{self.state.session_id}.json").is_file()

    # ----------------------------------------------------------- event turns

    def _start_events(self) -> None:
        from ract.session_events import EventStream
        from ract.session_render import PlainRenderer
        from ract.tui import plain_mode

        def write(text: str) -> None:
            sys.stdout.write(text)
            sys.stdout.flush()

        self._events = EventStream(session=self.state.session_id)
        self._renderer = PlainRenderer(
            write,
            labels=plain_mode(),
            project=self.state.config.resolve().parent,
            width=self._render_width(),
            wrap=True,
        )
        self._events.subscribe(self._renderer)
        facts = self._session_facts()
        self._events.emit("session.started", facts)
        for line in self._tier3_notes:
            self._events.emit("notice", {"level": "info", "text": line})
        # Ask about the repository's own commands now, on the main thread,
        # before any turn; the answer holds for the session (S-025).
        from ract import trust

        trust.decide(self.state.config.resolve().parent, interactive=True)

    def _tier3_facts(self, preloaded: Any = None) -> dict[str, str]:
        """``tier3`` and its status-line words from the project's grant (B-111, ADR-0048 D3).

        Read once at session start. Why tier 3 is off when a grant exists
        but does not hold, and an expiry within seven days, become notices.
        """
        from datetime import date

        from ract.policy.cli import tier_state_of
        from ract.ui.tier_status_view import expiry_notice, status_line

        from ract.policy.grant import load_grant

        self._tier3_notes = []
        project = self.state.config.resolve().parent
        try:
            # G-213 G3: the pin is of the bytes this decision verified.
            grant = load_grant(project) if preloaded is None else preloaded
            self._grant_pin = grant.pin
            self._grant_state = grant
            state, why = tier_state_of(grant)
        except Exception as exc:  # noqa: BLE001 - a grant that cannot be read opens nothing
            print(f"[repl] the tier-3 grant was not read: {exc}", flush=True)
            return {"tier3": "off", "tier3_status": "T3 off (no grant)"}
        if why and why != "no grant":
            self._tier3_notes.append(f"tier 3 is off: {why}")
        # Operator order 2026-11-03 A2: name the one command that turns it on
        # when a test runner exists; with a grant, say what may run.
        from ract.policy.guided import detect_runner

        if not grant.holds and detect_runner(project) is not None:
            self._tier3_notes.append(
                "tests found: run `ract policy init --guided` once and RACT "
                "can run them when you ask (for example /test)."
            )
        if grant.holds and grant.policy is not None:
            rules = [
                rule.id
                for rule in getattr(grant.policy.commands, "allow", []) or []
            ]
            if rules:
                self._tier3_notes.append(
                    "this grant lets RACT run: " + ", ".join(sorted(rules))
                )
        notice = expiry_notice(state, date.today())
        if notice:
            self._tier3_notes.append(notice)
        self._tier3 = state.mode
        return {"tier3": state.mode, "tier3_status": status_line(state, date.today())}

    def _check_grant_pin(self) -> None:
        """Suspend tier 3 when the grant's files changed since session start (ADR-0048 D3)."""
        from ract.policy.grant import pin_digest

        if self._grant_pin is None or self._tier3 == "suspended":
            return
        try:
            now = pin_digest(self.state.config.resolve().parent)
        except OSError as exc:
            print(f"[repl] the grant was not re-read: {exc}", flush=True)
            now = ""
        if now == self._grant_pin:
            return
        self._tier3 = "suspended"
        text = (
            "T3 suspended: policy changed. .ract/policy.yaml or its signature changed "
            "during this session; tier 3 stays off until you confirm with "
            "/permissions resume"
        )
        if self._events is not None:
            self._events.emit("notice", {"level": "warning", "text": text})
            self._events.emit(
                "mode.changed",
                {"mode": self.permission_mode(), "tier3": "suspended", "by": "policy"},
            )
        else:
            self._print_wrapped(text)

    def _session_facts(self) -> dict[str, Any]:
        from ract.executor.worktree import current_branch

        # Package 5 (handoff 9): None, not "?", when no config names a value.
        model, provider = None, None
        provider_config: dict[str, Any] | None = None
        try:
            import yaml

            config = yaml.safe_load(self.state.config.read_text(encoding="utf-8")) or {}
            providers = config.get("providers") or {}
            from ract.config_check import resolve_manager_provider

            resolved, _ = resolve_manager_provider(config)
            provider = resolved or None
            provider_config = (providers.get(provider) or {}) if provider else None
            model = (provider_config or {}).get("model") if provider else None
            model = None if model is None else str(model)
        except Exception:  # noqa: BLE001 -- the banner already reports config problems
            pass
        return {
            "workspace": self.state.config.resolve().parent.name,
            "model": model,
            "provider": provider,
            "branch": current_branch(self.state.config.resolve().parent),
            "mode": self.permission_mode(),
            **self._tier3_facts(),
            # B-084: measured by the probe or declared in ract.yaml, else null.
            "context_limit": _context_limit(
                self.state.config.resolve().parent, provider_config
            ),
            "session_id": self.state.session_id,
            # Not probed at session start yet (the first turn finds out);
            # the schema allows null and "unknown" for exactly this.
            "provider_reachable": None,
            "tool_calling": "unknown",
            "extensions": {"loaded": [], "skipped": []},
        }

    def _event_turn(self, intent: str, *, dry: bool, ask: bool = False) -> int:
        from ract.session_turn import TurnRequest, run_turn, tier3_facts_block

        from ract.turn_context import CancelSignal

        s = self.state
        self._check_grant_pin()
        # LR:: The next turn used to wait here for an interrupted turn's
        # worker, up to the provider's 60 s read timeout (G-029). It no longer
        # has to: Ctrl-C closes the worker's HTTP request (CancelSignal), and
        # every write runs under the session's write lock with the cancel
        # checked inside it (turn_context.persisting), so a late worker can
        # neither write nor interleave with this turn's writes.
        request = TurnRequest(
            config=s.config,
            intent=intent,
            session_id=None if dry else s.session_id,
            resume=(not dry) and (s.session_started or self._session_saved()),
            dry_run=dry,
            mode=s.mode,
            auto=s.auto,
            ask=ask and not dry,
            write_lock=self._write_lock,
            queued=self._drain_queued,
            # G-216 W1: the pin goes to every step and to the J4 run.
            grant_pin=self._grant_pin,
            terminal=sys.stdin.isatty(),
            tier3_mode=self._tier3_mode,
            tier3_session_approvals=self._tier3_session,
            # J11: the manager plans against the grant the session verified.
            tier3_facts=tier3_facts_block(self._grant_state),
        )
        turn_no = s.turns + 1
        cancel = CancelSignal()
        # LR:: Completion is signalled with an Event the worker sets, not by
        # Thread.join or is_alive: a KeyboardInterrupt that lands inside
        # Thread.join can leave the thread object reporting not-alive while
        # it still runs (CPython bug), which made the session claim an
        # interrupted turn had finished.
        done = threading.Event()
        box: dict[str, int] = {}

        def work() -> None:
            # Package T: an error the turn raises (a locked or unsnapshottable
            # file, for one) is one sentence on the console, not a thread
            # traceback that the interpreter prints after the prompt returns.
            try:
                box["code"] = run_turn(
                    self._events,
                    request,
                    turn=turn_no,
                    cancel=cancel,
                    queued=getattr(self, "_from_queue", False),
                )
            except Exception as exc:
                box["code"] = 1
                try:
                    self._console.error(f"the turn stopped: {exc}")
                except Exception as shown:  # noqa: BLE001 - B-185: the handler must not raise
                    print(
                        f"the turn stopped: {exc} (and could not be shown: {shown})",
                        file=sys.stderr,
                        flush=True,
                    )
            finally:
                done.set()

        worker = threading.Thread(target=work, name="ract-turn", daemon=True)
        self._worker_done = done
        started = time.monotonic()
        ahead = self._start_type_ahead(turn_no)
        worker.start()
        try:
            # Ctrl-C is delivered between waits (a timed wait is not
            # interruptible on Windows), so the interval bounds the time to
            # the acknowledgement; the target is 200 ms (B-033 item 1).
            while not done.wait(0.05):
                pass
        except KeyboardInterrupt:
            self._interrupted.append(done)
            self._queue_held = True
            return self._interrupt(done, cancel, turn_no, started)
        finally:
            if ahead is not None:
                ahead.stop()
                self._broker.end_turn()
        return box.get("code", 1)

    def _drain_queued(self) -> list[str]:
        """Package 3 (B-033s): every queued line, taken for the next model request (once each)."""
        if self._broker is None or self._queue_held:
            return []
        lines: list[str] = []
        while (text := self._broker.queue.take_first()) is not None:
            lines.append(text)
        return lines

    def _take_queued(self) -> str | None:
        """The next line queued during a turn, or None (package 6, B-033s)."""
        if self._broker is None or self._queue_held:
            return None
        return self._broker.queue.take_first()

    def _start_type_ahead(self, turn_no: int) -> Any:
        """Package 6 (B-033s): read typed lines during a turn into the input broker.

        Off unless RACT_TYPE_AHEAD=1, on Windows, with a console on stdin. The lines are
        queued and shown (input.queued); a queued line is not yet sent to the model (see
        docs/review/B-033s.md).
        """
        if (
            os.environ.get("RACT_TYPE_AHEAD") != "1"
            or os.name != "nt"
            or not sys.stdin.isatty()
        ):
            return None
        import msvcrt

        from ract.input_broker import ConsoleLineSource, InputBroker, TypeAhead

        def emit(kind: str, data: dict[str, Any]) -> None:
            if self._events is not None:
                self._events.emit(kind, data, turn=turn_no)

        broker = InputBroker(emit=emit)
        broker.start_turn()
        self._broker = broker
        from ract import question_gate

        # The reader reads every key, so Ctrl-C is handed to the main thread as an interrupt.
        # While an approval question is open its input() owns the console: no key is read here.
        source = ConsoleLineSource(
            msvcrt.kbhit,
            msvcrt.getwch,
            on_ctrl_c=_thread.interrupt_main,
            paused=question_gate.question_open,
        )
        ahead = TypeAhead(broker, source)
        ahead.start()
        return ahead

    def _sweep_step_worktrees(self) -> None:
        """B-146: step worktrees an ended RACT process left are removed, and said."""
        from ract.executor.worktree import sweep_orphan_worktrees

        try:
            removed = sweep_orphan_worktrees(self.state.config.resolve().parent)
        except Exception as exc:  # noqa: BLE001 - a sweep never stops a session
            print(f"[repl] step worktrees were not checked: {exc}", flush=True)
            return
        if removed:
            self._print_wrapped(
                f"removed {len(removed)} step worktree(s) an earlier RACT run left: "
                + ", ".join(removed)
            )

    def _remove_own_worktrees(self) -> None:
        from ract.executor.worktree import remove_own_worktrees

        try:
            remove_own_worktrees(self.state.config.resolve().parent)
        except Exception as exc:  # noqa: BLE001 - the session still ends
            print(f"[repl] step worktrees were not removed: {exc}", flush=True)

    def _leftover_worktrees(self) -> list[str]:
        from ract.executor.worktree import WorktreeManager

        try:
            manager = WorktreeManager(self.state.config.resolve().parent)
            return [str(p) for p in manager.leftovers()]
        except Exception as exc:  # noqa: BLE001 - only a message depends on it
            print(f"[repl] step worktrees were not listed: {exc}", flush=True)
            return []

    def _finish_interrupted_workers(self) -> dict[str, Any] | None:
        """Give interrupted turns' workers a bounded time to clean up.

        LR:: After a mid-stream Ctrl-C the worker removes its step worktree
        and branch, which takes a second or two. Quitting at once used to end
        the process first and leave a worktree under .git/ract-worktrees and
        a rootact/step/* branch behind (G-033). This is the one place the
        session waits for a worker, and only for a bounded time. Returns the
        ``cleanup`` fact for ``session.ended``, or None when nothing was
        pending.
        """
        pending = [done for done in self._interrupted if not done.is_set()]
        if not pending:
            return None
        if self._events is not None:
            self._events.emit(
                "notice",
                {"level": "info", "text": "finishing cleanup of the interrupted turn"},
            )
        started = time.monotonic()
        deadline = started + _EXIT_CLEANUP_SECONDS
        try:
            for done in pending:
                done.wait(max(0.0, deadline - time.monotonic()))
        except KeyboardInterrupt:
            print("[repl] a second Ctrl-C at exit: stopped waiting", flush=True)
        finished = all(done.is_set() for done in pending)
        if finished:
            # B-146: no worker runs now, so this process's step worktrees are
            # not in use; one an interrupted step could not remove goes now.
            self._remove_own_worktrees()
        left = self._leftover_worktrees()
        if left and self._events is not None:
            # B-146: past the bound, say what stays and how to remove it.
            self._events.emit(
                "notice",
                {
                    "level": "warning",
                    "text": "the interrupted step's worktree is still there: "
                    + "; ".join(f"git worktree remove --force {p}" for p in left)
                    + " (the next session removes it too)",
                },
            )
        out: dict[str, Any] = {
            "waited_ms": int((time.monotonic() - started) * 1000),
            "finished": finished,
        }
        if left:
            out["left"] = left
        return out

    def _interrupt(
        self,
        done: threading.Event,
        cancel: threading.Event,
        turn_no: int,
        started: float,
    ) -> int:
        """Ctrl-C during a turn: acknowledge now, stop writes, prompt within 2 s."""
        received = time.monotonic()
        self._events.emit(
            "turn.interrupting",
            {
                "elapsed_ms": int((time.monotonic() - received) * 1000),
                # A model call in flight cannot be stopped from Python; it
                # finishes in the background and writes nothing.
                "cancellable": False,
                "detail": "stopping; nothing more will be written",
            },
            turn=turn_no,
        )
        # Announce first: a step that ends because of the cancel must follow "stopping...".
        cancel.set()
        try:
            # LR:: This used to wait 1.5 s of the 2 s budget for the worker.
            # A worker blocked in a model call cannot finish in that time
            # anyway (Python cannot cancel the HTTP read), so the wait only
            # spent the budget; under CPU load the prompt came back after
            # 2.5 s. A worker that is between steps notices the cancel at
            # once, so a short grace covers it; otherwise the next turn waits
            # for it, with a notice.
            finished = done.wait(_INTERRUPT_GRACE_SECONDS)
        except KeyboardInterrupt:
            finished = done.is_set()
        if finished:
            verdict = "Stopped. Nothing more was written after the interrupt."
        else:
            verdict = (
                "Stopped. The model call is still finishing in the background; "
                "nothing it returns will be written."
            )
        self._events.emit(
            "turn.finished",
            {
                "outcome": "interrupted",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "verdict": verdict,
                "workspace": "nothing was written after the interrupt",
                "changed": None,
                "checkpoint": None,
                "verification": {"status": "not-run", "runs": []},
                "provenance": {"signed": False, "unsigned_files": []},
            },
            turn=turn_no,
        )
        return 5

    def _run_intent(
        self,
        intent: str,
        *,
        dry_run: bool | None = None,
        loop: bool = False,
        ask: bool = False,
    ) -> int:
        # An asked question has no plan to show, so dry-run does not apply.
        dry = False if ask else (self.state.dry_run if dry_run is None else dry_run)
        pending = getattr(self, "_pending_test_fact", None)
        if pending and not loop and not ask:
            # Operator order 2026-11-03 A3: the /test result rides the next
            # turn so the model can act on a failure.
            intent = pending + "\n" + intent
            self._pending_test_fact = None
        if self._event_mode and not loop and self._events is not None:
            code = self._event_turn(intent, dry=dry, ask=ask)
            self.state.turns += 1
            if code == 0 and not dry:
                self.state.session_started = True
            return code
        argv = self.build_run_argv(intent, dry_run=dry, loop=loop, ask=ask)
        code = self._invoke(argv)
        self.state.turns += 1
        if code == 0 and not dry and not loop:
            self.state.session_started = True
        return code

    def _run_verb(self, verb: str, args: list[str]) -> int:
        argv = [verb, *args]
        if verb in _CONFIG_AWARE_VERBS and "--config" not in args:
            argv += ["--config", str(self.state.config)]
        return self._invoke(argv)

    def _invoke(self, argv: list[str]) -> int:
        """Run the dispatcher. A failing command never ends the session."""
        try:
            code = self._dispatch(argv)
        except SystemExit as exc:
            # argparse exits on usage errors and ``parser.error``.
            code = (
                exc.code
                if isinstance(exc.code, int)
                else (0 if exc.code is None else 1)
            )
        except KeyboardInterrupt:
            self._console.print("")
            self._console.warning("interrupted. Nothing further was run for that line.")
            return 130
        except Exception as exc:  # noqa: BLE001 -- the session must survive a bad command
            self._console.error(f"{type(exc).__name__}: {escape(str(exc))}")
            return 1
        code = int(code or 0)
        if code != 0:
            self._console.warning(f"that command ended with exit code {code}")
        return code

    # ---------------------------------------------------------------- chrome

    def _banner(self) -> None:
        try:
            import ract

            version = ract.__version__
        except Exception:  # noqa: BLE001
            version = "?"
        # Wrap the raw text, then escape each line: an escape split across two
        # lines would print wrong. The [ract] prefix takes seven columns (B-041c).
        raw = (
            f"RACT {version}  config: {self.state.config}  "
            "type an intent, or /help for commands"
        )
        pieces = textwrap.wrap(raw, width=self._render_width() - 7)
        self._console.info(escape(pieces[0]))
        for piece in pieces[1:]:
            self._console.print("       " + escape(piece))
        if not self.state.config.is_file():
            raw_warning = (
                f"{self.state.config} not found. "
                "Run ract setup in another terminal to create one (it checks this machine and asks a few questions)."
            )
            warning_pieces = textwrap.wrap(raw_warning, width=self._render_width() - 2)
            self._console.warning(escape(warning_pieces[0]))
            for piece in warning_pieces[1:]:
                self._console.print("  " + escape(piece))

    def _resume_offer(self) -> None:
        """Name the newest saved session and the command that resumes it (J2)."""
        from ract.session_listing import latest_row, sessions_dir

        try:
            row = latest_row(sessions_dir(self.state.config))
        except OSError:
            return
        if row is None:
            return
        when = datetime.fromtimestamp(row.updated).strftime("%Y-%m-%d %H:%M")
        request = safe_text(row.request) or "no request saved"
        # A request cut for the listing already ends in "...": no second full stop.
        stop = "" if request.endswith("...") else "."
        self._print_wrapped(
            f"last session {row.session_id} ({when}): {request}{stop} /resume to continue it."
        )

    # --------------------------------------------------------------- history

    def _setup_readline(self) -> None:
        start = _readline_start_inputrc()
        try:
            import readline
        except ImportError:  # Windows without pyreadline: plain input() still works.
            return
        finally:
            start()
        words = sorted(
            {f"/{name}" for name in self._builtins} | {f"/{v}" for v in self._verbs}
        )

        def complete(text: str, index: int) -> str | None:
            if not text.startswith("/"):
                return None
            matches = [w for w in words if w.startswith(text)]
            return matches[index] if index < len(matches) else None

        rl: Any = readline
        rl.set_completer(complete)
        rl.set_completer_delims(" \t\n")
        # J7: Esc Esc at the prompt runs /rewind. Only where the prompt is
        # readline's; the Windows console's own line editor clears the line
        # on Esc and passes no key to RACT.
        try:
            rl.parse_and_bind(r'"\e\e": "\C-a\C-k/rewind\C-m"')
        except Exception as exc:  # noqa: BLE001
            print(f"[repl] Esc Esc not bound: {exc}", flush=True)
        rl.parse_and_bind("tab: complete")
        self._history_path = _history_path_or_disabled(self._history_path)
        if self._history_path is not None:
            try:
                self._history_path.parent.mkdir(parents=True, exist_ok=True)
                rl.read_history_file(str(self._history_path))
            except (OSError, ValueError):
                pass
            rl.set_history_length(1000)

    def _save_history(self) -> None:
        history_path = _history_path_or_disabled(self._history_path)
        if history_path is None:
            return
        try:
            import readline

            history_path.parent.mkdir(parents=True, exist_ok=True)
            rl_save: Any = readline
            rl_save.write_history_file(str(history_path))
        except (ImportError, OSError):
            pass


def inputrc_without_esc_esc(system_text: str, home_inputrc: str | None) -> str:
    """The inputrc RACT starts readline from, so Esc Esc is a whole key (J7).

    LR:: Ubuntu's /etc/inputrc binds "\\e\\e[C" and "\\e\\e[D" (Alt-arrow word
    moves), which makes Esc Esc the start of longer keys; CPython reads
    through readline's callback interface, where the wait for the rest never
    times out, so Esc Esc did nothing until the next key. With a ~/.inputrc
    readline would read it instead of the system file, and so does this.
    """
    if home_inputrc is not None:
        return f"$include {home_inputrc}\n"
    kept = [
        line
        for line in system_text.splitlines()
        if not line.lstrip().startswith('"\\e\\e')
    ]
    return "\n".join(kept) + "\n"


def _readline_start_inputrc():  # type: ignore[no-untyped-def]
    """Point INPUTRC at RACT's copy while readline is first imported; a callable undoes it.

    Only on POSIX, only when the operator set no INPUTRC, and only before the
    first import (readline reads its init file then).
    """
    import tempfile

    if os.name == "nt" or "INPUTRC" in os.environ or "readline" in sys.modules:
        return lambda: None
    home = os.path.expanduser("~/.inputrc")
    try:
        system = Path("/etc/inputrc").read_text(encoding="utf-8", errors="replace")
    except OSError:
        system = ""
    text = inputrc_without_esc_esc(system, home if os.path.isfile(home) else None)
    try:
        handle, path = tempfile.mkstemp(prefix="ract-inputrc-")
        os.write(handle, text.encode("utf-8"))
        os.close(handle)
    except OSError as exc:
        print(f"[repl] Esc Esc may wait for a next key: {exc}", flush=True)
        return lambda: None
    os.environ["INPUTRC"] = path

    def undo() -> None:
        os.environ.pop("INPUTRC", None)
        try:
            os.unlink(path)
        except OSError as exc:
            print(f"[repl] the inputrc copy stays: {exc}", flush=True)

    return undo


def _history_path_or_disabled(history_path: Path | None) -> Path | None:
    """The history path when RACT's state is no link (B-213); else None.

    LR:: ``.ract`` lives in the workspace, so a cloned repository can ship
    it, or ``repl_history`` inside it, as a link or junction. The session
    would then load a planted fake history and, worse, append what the
    operator types (which routinely holds keys and paths) to a file outside
    the project on exit. Every other writer of RACT's state refuses a link
    with ``check_state_path``; history does the same and degrades to
    disabled with a one-line stderr note instead of touching the link.
    """
    if history_path is None:
        return None
    try:
        check_state_path(history_path)
    except StateDirRefused as exc:
        print(f"[repl] history disabled: {exc}", file=sys.stderr, flush=True)
        return None
    return history_path


def _flag(value: bool) -> str:
    return "on" if value else "off"


def run_repl(config: Path | None = None) -> int:
    """Open the interactive session in the current directory."""
    history = Path(".ract") / "repl_history"
    return ReplSession(config, history_path=history).run()
