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

import shlex
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.markup import escape

from ract.providers import reasoning
from ract.session_events import safe_text

# Verbs that accept ``--config`` and should follow the session's config path
# when the operator did not pass one.
_CONFIG_AWARE_VERBS = frozenset({"doctor", "report"})

HELP_ROWS: tuple[tuple[str, str], ...] = (
    ("<text>", "Run the text as an intent (same as /run <text>)."),
    ("/run <intent>", "Plan and execute an intent."),
    ("/plan <intent>", "Plan only. Shows the plan, writes nothing."),
    ("/ask <question>", "Answer a question. No plan, and no file is written."),
    ("/loop <intent>", "Run the quality-anchored loop until done or regressed."),
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
    ("/cost", "Requests, tokens and bytes sent off this machine in this session."),
    (
        "/mode [plan|default|auto-accept]",
        "plan: propose only; default: ask before each change; auto-accept: apply changes.",
    ),
    (
        "/undo [--force]",
        "Reverse the last turn's file changes (skips files you edited since).",
    ),
    ("/redo [--force]", "Reverse the last /undo."),
    ("/doctor [--check-providers]", "Run setup diagnostics against the active config."),
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
_EXIT_CLEANUP_SECONDS = 15.0


class ReplSession:
    """Read-eval-print loop over the RACT command dispatcher."""

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
        self._read_line = read_line or input
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
            "undo": self._cmd_undo,
            "redo": self._cmd_redo,
            "clear": self._cmd_clear,
        }
        self._events: Any = None
        self._renderer: Any = None
        self._worker_done: threading.Event | None = None
        # One per session, shared by every turn's worker (G-029).
        self._write_lock = threading.RLock()
        # Done events of interrupted turns' workers, waited for at exit only.
        self._interrupted: list[threading.Event] = []

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
        if self._event_mode:
            self._start_events()
        started = time.monotonic()
        reason = "error"
        try:
            while True:
                try:
                    line = self._read_line(self.prompt())
                except EOFError:
                    self._console.print("")
                    reason = "eof"
                    break
                except KeyboardInterrupt:
                    # Ctrl-C at the prompt abandons the line, like a shell.
                    self._console.print("")
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
        if text in {"exit", "quit"}:
            return False
        self._run_intent(text)
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

    def _cmd_undo(self, args: list[str]) -> bool:
        from ract import undo_backup

        result = undo_backup.undo(
            self.state.config.resolve().parent, force="--force" in args
        )
        for line in result.lines("undo"):
            self._console.print(line)
        return True

    def _cmd_redo(self, args: list[str]) -> bool:
        from ract import undo_backup

        result = undo_backup.redo(
            self.state.config.resolve().parent, force="--force" in args
        )
        for line in result.lines("redo"):
            self._console.print(line)
        return True

    # B-034: the session's permission mode, made of the two switches it
    # already had (dry-run, auto) and shown in the status line.
    _MODE_TEXT = {
        "plan": "plan: the planner proposes; nothing runs and nothing is written",
        "default": "default: RACT asks before each step that changes a file",
        "auto-accept": "auto-accept: changes are applied without asking (/undo reverses a turn)",
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

    def _cmd_mode(self, args: list[str]) -> bool:
        if not args:
            self._console.print(self._MODE_TEXT[self.permission_mode()])
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
                "mode.changed", {"mode": wanted, "tier3": "off", "by": "operator"}
            )
        self._console.print(self._MODE_TEXT[wanted])
        return True

    def _cmd_cost(self, args: list[str]) -> bool:
        from ract import egress_ledger

        records = egress_ledger.since(
            egress_ledger.read(), self.state.started_at, this_process=True
        )
        for line in egress_ledger.describe(records):
            self._console.print(line)
        self._console.print(
            f"ledger: {egress_ledger.ledger_path()} (ract doctor --egress for history)"
        )
        return True

    def _cmd_config(self, args: list[str]) -> bool:
        self._run_verb(
            "config", args or ["validate", "--config", str(self.state.config)]
        )
        return True

    def _cmd_model(self, args: list[str]) -> bool:
        import shutil

        import yaml

        from ract import trust
        from ract.config_check import resolve_manager_provider
        from ract.model_view import model_blocks

        try:
            config = yaml.safe_load(self.state.config.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            self._console.error(f"could not read {self.state.config}: {exc}")
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
            and trust.repository_named_host(slot.get("url") or slot.get("base_url"))
        }
        width = max(60, min(shutil.get_terminal_size((80, 24)).columns, 100))
        for line in model_blocks(providers, manager or "", named, width):
            self._console.print(escape(line))
        return True

    def _cmd_providers(self, args: list[str]) -> bool:
        import yaml

        from ract.config_check import resolve_manager_provider

        try:
            config = yaml.safe_load(self.state.config.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            self._console.error(f"could not read {self.state.config}: {exc}")
            return True
        providers = config.get("providers") if isinstance(config, dict) else None
        if not isinstance(providers, dict) or not providers:
            self._console.error(
                f"no providers in {self.state.config}. Leave and run ract setup to create a working one."
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
                "usage: /set <dry-run|stream|auto|mode|iterations|reasoning> <value>"
            )
            return True
        name, value = args[0].lower().replace("_", "-"), args[1].lower()
        s = self.state
        if name in {"dry-run", "stream", "auto"}:
            if value not in _BOOL_TRUE | _BOOL_FALSE:
                self._console.error(f"{name} takes on or off, not '{escape(value)}'")
                return True
            on = value in _BOOL_TRUE
            if name == "auto" and on and not sys.stdin.isatty():
                self._console.error("auto needs a terminal to ask for approval")
                return True
            setattr(s, name.replace("-", "_"), on)
        elif name == "mode":
            if value not in {"default", "documentation", "git"}:
                self._console.error("mode is default, documentation or git")
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
        self._console.success(f"session = {s.session_id}")
        return True

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
        for line in context_lines(records, None, width=self._context_width()):
            self._console.print(line)
        return True

    def _context_width(self) -> int:
        import shutil

        return max(40, min(80, shutil.get_terminal_size((80, 24)).columns))

    def _cmd_sessions(self, args: list[str]) -> bool:
        from ract.session_listing import LIST_LIMIT, list_rows, sessions_dir

        rows, total = list_rows(sessions_dir(self.state.config))
        if not rows:
            self._console.info("no sessions yet")
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
            self._console.error("usage: /resume <id|latest>")
            return True
        directory = sessions_dir(self.state.config)
        if args[0] == "latest":
            row = latest_row(directory)
            if row is None:
                _, total = list_rows(directory, limit=0)
                self._console.info(
                    "no sessions yet" if total == 0 else "no readable session to resume"
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
        s.session_id = row.session_id
        s.session_started = True
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
        self._renderer = PlainRenderer(write, labels=plain_mode())
        self._events.subscribe(self._renderer)
        self._events.emit("session.started", self._session_facts())
        # Ask about the repository's own commands now, on the main thread,
        # before any turn; the answer holds for the session (S-025).
        from ract import trust

        trust.decide(self.state.config.resolve().parent, interactive=True)

    def _session_facts(self) -> dict[str, Any]:
        from ract.executor.worktree import current_branch

        model, provider = "?", "?"
        try:
            import yaml

            config = yaml.safe_load(self.state.config.read_text(encoding="utf-8")) or {}
            providers = config.get("providers") or {}
            from ract.config_check import resolve_manager_provider

            resolved, _ = resolve_manager_provider(config)
            provider = resolved or "?"
            model = str((providers.get(provider) or {}).get("model", "?"))
        except Exception:  # noqa: BLE001 -- the banner already reports config problems
            pass
        return {
            "workspace": self.state.config.resolve().parent.name,
            "model": model,
            "provider": provider,
            "branch": current_branch(self.state.config.resolve().parent),
            "mode": self.permission_mode(),
            "tier3": "off",
            "context_limit": None,
            # Not probed at session start yet (the first turn finds out);
            # the schema allows null and "unknown" for exactly this.
            "provider_reachable": None,
            "tool_calling": "unknown",
            "extensions": {"loaded": [], "skipped": []},
        }

    def _event_turn(self, intent: str, *, dry: bool, ask: bool = False) -> int:
        from ract.session_turn import TurnRequest, run_turn

        from ract.turn_context import CancelSignal

        s = self.state
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
            try:
                box["code"] = run_turn(
                    self._events, request, turn=turn_no, cancel=cancel
                )
            finally:
                done.set()

        worker = threading.Thread(target=work, name="ract-turn", daemon=True)
        self._worker_done = done
        started = time.monotonic()
        worker.start()
        try:
            # Ctrl-C is delivered between waits (a timed wait is not
            # interruptible on Windows), so the interval bounds the time to
            # the acknowledgement; the target is 200 ms (B-033 item 1).
            while not done.wait(0.05):
                pass
        except KeyboardInterrupt:
            self._interrupted.append(done)
            return self._interrupt(done, cancel, turn_no, started)
        return box.get("code", 1)

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
            pass  # a further Ctrl-C at exit: stop waiting
        return {
            "waited_ms": int((time.monotonic() - started) * 1000),
            "finished": all(done.is_set() for done in pending),
        }

    def _interrupt(
        self,
        done: threading.Event,
        cancel: threading.Event,
        turn_no: int,
        started: float,
    ) -> int:
        """Ctrl-C during a turn: acknowledge now, stop writes, prompt within 2 s."""
        received = time.monotonic()
        cancel.set()
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
        self._console.info(
            f"RACT {version}  config: {escape(str(self.state.config))}  "
            "type an intent, or /help for commands"
        )
        if not self.state.config.is_file():
            self._console.warning(
                f"{escape(str(self.state.config))} not found. "
                "Leave and run ract setup to create one (it checks this machine and asks a few questions)."
            )

    # --------------------------------------------------------------- history

    def _setup_readline(self) -> None:
        try:
            import readline
        except ImportError:  # Windows without pyreadline: plain input() still works.
            return
        words = sorted(
            {f"/{name}" for name in self._builtins} | {f"/{v}" for v in self._verbs}
        )

        def complete(text: str, index: int) -> str | None:
            if not text.startswith("/"):
                return None
            matches = [w for w in words if w.startswith(text)]
            return matches[index] if index < len(matches) else None

        readline.set_completer(complete)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")
        if self._history_path is not None:
            try:
                self._history_path.parent.mkdir(parents=True, exist_ok=True)
                readline.read_history_file(str(self._history_path))
            except (OSError, ValueError):
                pass
            readline.set_history_length(1000)

    def _save_history(self) -> None:
        if self._history_path is None:
            return
        try:
            import readline

            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(str(self._history_path))
        except (ImportError, OSError):
            pass


def _flag(value: bool) -> str:
    return "on" if value else "off"


def run_repl(config: Path | None = None) -> int:
    """Open the interactive session in the current directory."""
    history = Path(".ract") / "repl_history"
    return ReplSession(config, history_path=history).run()
