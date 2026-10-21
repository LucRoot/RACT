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
platform has it. Nothing here adds a dependency.
"""

from __future__ import annotations

import shlex
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.markup import escape

# Verbs that accept ``--config`` and should follow the session's config path
# when the operator did not pass one.
_CONFIG_AWARE_VERBS = frozenset({"doctor", "report"})

HELP_ROWS: tuple[tuple[str, str], ...] = (
    ("<text>", "Run the text as an intent (same as /run <text>)."),
    ("/run <intent>", "Plan and execute an intent."),
    ("/plan <intent>", "Plan only. Shows the plan, writes nothing."),
    ("/loop <intent>", "Run the quality-anchored loop until done or regressed."),
    ("/set <name> <value>", "Change a setting: dry-run, stream, auto, mode, iterations."),
    ("/settings", "Show the current settings."),
    ("/session [new|<id>]", "Show, restart or switch the session that carries context between turns."),
    ("/config", "Validate the active config (same as ract config validate)."),
    ("/providers", "List configured providers and the manager provider."),
    ("/doctor [--check-providers]", "Run setup diagnostics against the active config."),
    ("/report [--last]", "Show what the last run changed and why."),
    ("/<verb> ...", "Any other RACT verb, for example /whisper, /fence, /auction, /status."),
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
    session_id: str = field(
        default_factory=lambda: time.strftime("repl-%Y%m%d-%H%M%S")
    )
    # True once a turn has completed and saved the session, so the next turn
    # resumes it. A failed first turn leaves this False and the next turn
    # starts the session again instead of resuming one that does not exist.
    session_started: bool = False
    turns: int = 0


Dispatch = Callable[[list[str]], int]


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
        if dispatch is None or verbs is None:
            from ract import cli

            dispatch = dispatch or cli.main
            verbs = verbs if verbs is not None else cli.CLI_VERBS
        if console is None:
            from ract.tui import console as default_console

            console = default_console
        self.state = ReplState(config=config or Path("ract.yaml"))
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
            "loop": self._cmd_loop,
            "set": self._cmd_set,
            "settings": self._cmd_settings,
            "session": self._cmd_session,
            "config": self._cmd_config,
            "providers": self._cmd_providers,
            "doctor": self._cmd_doctor,
            "report": self._cmd_report,
            "clear": self._cmd_clear,
        }

    # ------------------------------------------------------------------ loop

    def prompt(self) -> str:
        marker = "plan" if self.state.dry_run else "ract"
        return f"{marker}> "

    def run(self) -> int:
        """Run until the operator exits. Returns a process exit code."""
        self._setup_readline()
        self._banner()
        try:
            while True:
                try:
                    line = self._read_line(self.prompt())
                except EOFError:
                    self._console.print("")
                    break
                except KeyboardInterrupt:
                    # Ctrl-C at the prompt abandons the line, like a shell.
                    self._console.print("")
                    continue
                if not self.handle(line):
                    break
        finally:
            self._save_history()
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
        self._console.error(f"unknown command /{escape(name)}. Type /help for the list.")
        return True

    def _cmd_help(self, args: list[str]) -> bool:
        self._console.table("RACT session", ["Command", "What it does"], [[escape(cell) for cell in row] for row in HELP_ROWS])
        return True

    def _cmd_exit(self, args: list[str]) -> bool:
        return False

    def _cmd_clear(self, args: list[str]) -> bool:
        self._console.print("\033[2J\033[H", end="")
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

    def _cmd_config(self, args: list[str]) -> bool:
        self._run_verb("config", args or ["validate", "--config", str(self.state.config)])
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
                f"no providers in {self.state.config}. Run ract --init-provider local to scaffold one."
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
        self._console.table("Providers", ["name", "role", "adapter", "model", "url"], rows)
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
            ["session", f"{s.session_id}{' (resumes next turn)' if s.session_started else ''}"],
            ["turns this session", str(s.turns)],
        ]
        self._console.table("Settings", ["setting", "value"], rows)
        return True

    def _cmd_set(self, args: list[str]) -> bool:
        if len(args) != 2:
            self._console.error(
                "usage: /set <dry-run|stream|auto|mode|iterations> <value>"
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

    # ------------------------------------------------------------- execution

    def build_run_argv(
        self, intent: str, *, dry_run: bool | None = None, loop: bool = False
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
        # Carry context between turns. A dry run never saves a session, so it
        # neither starts nor resumes one.
        if not dry and not loop:
            argv += ["--session", s.session_id]
            if s.session_started:
                argv.append("--resume")
        argv += ["--", intent]
        return argv

    def _run_intent(
        self, intent: str, *, dry_run: bool | None = None, loop: bool = False
    ) -> int:
        dry = self.state.dry_run if dry_run is None else dry_run
        argv = self.build_run_argv(intent, dry_run=dry_run, loop=loop)
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
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
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
                "Run /config for details or leave and run ract --init-provider local."
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
