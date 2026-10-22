"""Headless mode: `ract -p "prompt"` for scripts and CI (B-035).

LR:: `ract -p` was an argparse error and piped stdin was ignored (UX
baseline UX-09), so RACT could not run in CI at all. A headless run is one
interactive turn without a terminal: the same session events, the same
cancel and abort paths, and a result a script can read. The contract is
docs/EVENTS_SESSION.md: `--output-format text` prints the answer text,
`json` one `ract.result/1` object, `stream-json` every event as a JSON line.
stdout carries only that; progress, notices and errors go to stderr. The run
itself prints to stdout from deep inside (snapshot notes, the adapter), so it
runs with stdout redirected to stderr, and only this module writes the real
stdout. Nothing in headless mode waits for input.

Exit codes: 0 done, 1 the task failed, 2 usage or configuration error,
3 refused, 4 budget (reserved), 5 interrupted (SIGINT), 6 provider
unavailable, 143 terminated (SIGTERM, or Ctrl-Break on Windows).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TextIO

from ract.session_events import EventStream, JsonlSink, SessionEvent
from ract.session_render import PlainRenderer

RESULT_SCHEMA = "ract.result/1"
EXIT_INTERRUPTED = 5
EXIT_TERMINATED = 143
_INTERRUPT_GRACE_SECONDS = 0.3


def wants_headless(argv: list[str]) -> bool:
    """True when ``argv`` asks for a headless run (-p or --print)."""
    return any(arg in {"-p", "--print"} or arg.startswith("--print=") for arg in argv)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ract -p",
        description=(
            "Run one turn without a terminal and print the result. The prompt "
            "is the argument, or stdin, or both (stdin is then added as context)."
        ),
    )
    parser.add_argument(
        "-p", "--print", dest="prompt", nargs="?", const="", metavar="PROMPT"
    )
    # The prompt may also follow the flags (`ract -p --ask "why?"`), and
    # unquoted words are joined (`ract -p fix the bug`).
    parser.add_argument("rest", nargs="*", metavar="PROMPT", help=argparse.SUPPRESS)
    parser.add_argument(
        "--output-format",
        choices=("text", "json", "stream-json"),
        default="text",
        help="text: the answer; json: one ract.result/1 object; "
        "stream-json: every session event as a JSON line",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument(
        "--bare",
        action="store_true",
        help="load no repository-supplied extension (hooks, MCP servers, skills); "
        "a headless run already loads none in this release",
    )
    parser.add_argument(
        "--ask",
        action="store_true",
        help="answer the prompt as a question: no plan, and no file is written",
    )
    parser.add_argument(
        "--trust-project",
        action="store_true",
        help="run this repository's own commands (hooks, MCP servers, gates) "
        "for this run, as if trusted; a setting in the repository cannot do this",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=1,
        help="turns allowed; a headless run is one turn in this release",
    )
    parser.add_argument(
        "--fail-on-denial",
        action="store_true",
        help="exit 3 at the first denied action (nothing asks for approval yet)",
    )
    parser.add_argument("--allowed-tools", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--json-schema", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--max-budget-usd", default=None, help=argparse.SUPPRESS)
    return parser


def _unsupported(args: argparse.Namespace) -> str | None:
    """A usage error for a flag this release cannot honor, or None.

    A flag that is accepted and silently ignored would make a CI job believe
    a limit or a check is in place. These say so and exit 2 instead.
    """
    if args.max_turns < 1:
        return "--max-turns must be 1 or more"
    if args.allowed_tools is not None:
        return (
            "--allowed-tools: RACT has no tools in this release (the tool layer "
            "waits for ADR-0047), so no tool name can be allowed"
        )
    if args.json_schema is not None:
        return (
            "--json-schema: structured output is not supported in this release "
            "(a run that writes files has no answer text to validate)"
        )
    if args.max_budget_usd is not None:
        return (
            "--max-budget-usd: cost is not measured in this release, so a "
            "budget cannot be enforced"
        )
    return None


def repository_extensions(config: Path) -> list[dict[str, str]]:
    """Extensions the repository supplies, as session.started lists them."""
    found: list[dict[str, str]] = []
    hooks = config.parent / ".ract" / "hooks"
    if hooks.is_dir():
        for path in sorted(hooks.glob("*.json")):
            found.append({"kind": "hook", "name": path.stem})
    try:
        import yaml

        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 -- the run reports config problems itself
        print(f"[headless] could not read {config}: {exc}", file=sys.stderr)
        return found
    for name in sorted((data.get("mcp_servers") or {}).keys()):
        found.append({"kind": "mcp", "name": str(name)})
    if data.get("skill"):
        found.append({"kind": "skill", "name": str(data["skill"])})
    for slot, spec in sorted((data.get("providers") or {}).items()):
        if isinstance(spec, dict) and spec.get("adapter") == "internal":
            found.append({"kind": "command", "name": f"provider {slot}"})
    for gate in ("coverage_gate", "mutation_gate"):
        if (data.get(gate) or {}).get("enabled"):
            found.append({"kind": "command", "name": gate})
    if (data.get("retrieval") or {}).get("adapter") == "web":
        found.append({"kind": "network", "name": "web retrieval"})
    return found


class _StderrRenderer(PlainRenderer):
    """Progress for a person watching stderr: everything except the text."""

    def _on_agent_text_delta(self, d: dict[str, Any]) -> None:
        return  # the text is the result, written to stdout


def _read_stdin(stdin: TextIO) -> str:
    if stdin.isatty():
        return ""
    try:
        return stdin.read()
    except (OSError, ValueError):
        return ""


def build_prompt(argument: str | None, piped: str) -> str:
    """The turn's prompt from the argument and piped stdin.

    With both, stdin is context, labeled so the model does not read it as
    instructions from the operator.
    """
    argument = (argument or "").strip()
    piped = piped.strip("\n")
    if argument and piped:
        return f"{argument}\n\n<stdin>\n{piped}\n</stdin>"
    return argument or piped


def result_object(
    events: list[SessionEvent], *, session: str, exit_code: int
) -> dict[str, Any]:
    """The `ract.result/1` object, assembled from the session's events."""
    finished = next((e.data for e in reversed(events) if e.kind == "turn.finished"), {})
    answer = "".join(
        str(e.data.get("text", ""))
        for e in events
        if e.kind == "agent.text.delta" and e.data.get("channel") == "answer"
    )
    turns = sum(1 for e in events if e.kind == "turn.started")
    return {
        "schema": RESULT_SCHEMA,
        "outcome": finished.get("outcome", "failed"),
        "exit_code": exit_code,
        "session": session,
        "turns": turns,
        "verdict": finished.get("verdict", ""),
        "final_text": answer,
        "changed": finished.get("changed") or [],
        "verification": finished.get("verification")
        or {"status": "not-run", "runs": []},
        "provenance": finished.get("provenance")
        or {"signed": False, "unsigned_files": []},
        # Token counts are not collected yet; null means unknown.
        "cost": {
            "tokens_in": None,
            "tokens_out": None,
            "by_purpose": {},
            "total_usd": None,
        },
        "denials": [],
        "events_path": None,
    }


def run_headless(
    argv: list[str],
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Handle `ract -p ...`. Returns the process exit code."""
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed the usage error
        return int(exc.code or 0) if exc.code not in (None, 0) else 0
    problem = _unsupported(args)
    if problem:
        print(f"error: {problem}. hint: run without it", file=err)
        return 2
    words = " ".join(part for part in (args.prompt, *args.rest) if part)
    prompt = build_prompt(words or None, _read_stdin(stdin or sys.stdin))
    if not prompt:
        print(
            'error: no prompt. hint: ract -p "what to do", or pipe it: '
            'echo "what to do" | ract -p',
            file=err,
        )
        return 2
    if not Path(args.config).is_file():
        print(
            f"error: configuration file not found: {args.config}. hint: run "
            "`ract --init-provider local` here, then `ract doctor --check-providers`",
            file=err,
        )
        return 2

    session = f"h-{uuid.uuid4().hex[:12]}"
    stream = EventStream(session=session)
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    if args.output_format == "stream-json":
        stream.subscribe(JsonlSink(lambda line: (out.write(line), out.flush())))
    renderer = _StderrRenderer(lambda text: (err.write(text), err.flush()))
    stream.subscribe(renderer)
    return _run(stream, events, args, prompt, session, out, err)


def _run(
    stream: EventStream,
    events: list[SessionEvent],
    args: argparse.Namespace,
    prompt: str,
    session: str,
    out: TextIO,
    err: TextIO,
) -> int:
    from ract.session_turn import TurnRequest, run_turn
    from ract.trust import allow_for_this_process, is_trusted
    from ract.turn_context import CancelSignal, repository_extensions_off

    cancel = CancelSignal()
    terminated = threading.Event()
    done = threading.Event()
    box: dict[str, int] = {}
    request = TurnRequest(
        config=Path(args.config),
        intent=prompt,
        session_id=None,
        resume=False,
        ask=args.ask,
        write_lock=threading.RLock(),
    )

    # A trusted repository's extensions run (`ract trust` was the operator's
    # decision); `--bare` loads none even then. An untrusted one: none, and
    # nobody is asked (S-025).
    root = Path(args.config).resolve().parent
    trusted = not args.bare and (args.trust_project or is_trusted(root))
    if trusted and args.trust_project:
        allow_for_this_process(root)

    def work() -> None:
        try:
            # The run prints notes to stdout from deep inside; stdout belongs
            # to the result here.
            with (
                contextlib.redirect_stdout(err),
                contextlib.nullcontext() if trusted else repository_extensions_off(),
            ):
                box["code"] = run_turn(stream, request, turn=1, cancel=cancel)
        finally:
            done.set()

    def on_terminate(signum: int, frame: Any) -> None:  # noqa: ARG001
        terminated.set()
        cancel.set()

    previous = _install_terminate_handlers(on_terminate)
    started = time.monotonic()
    provider, model = _provider_and_model(Path(args.config))
    reason = "--bare" if args.bare else "the project is not trusted"
    skipped = (
        []
        if trusted
        else [
            {**ext, "reason": reason}
            for ext in repository_extensions(Path(args.config))
        ]
    )
    if skipped:
        names = ", ".join(f"{e['kind']} {e['name']}" for e in skipped)
        print(
            f"note: not loaded in this headless run ({reason}): {names}. "
            "To allow them: ract trust",
            file=err,
        )
    stream.emit(
        "session.started",
        {
            "workspace": Path(args.config).resolve().parent.name,
            "model": model,
            "provider": provider,
            "branch": None,
            "mode": "default",
            "tier3": "off",
            "context_limit": None,
            "provider_reachable": None,
            "tool_calling": "unknown",
            "extensions": {"loaded": [], "skipped": skipped},
        },
    )
    worker = threading.Thread(target=work, name="ract-headless-turn", daemon=True)
    worker.start()
    try:
        while not done.wait(0.05):
            if terminated.is_set():
                break
    except KeyboardInterrupt:
        cancel.set()
        done.wait(_INTERRUPT_GRACE_SECONDS)
        return _finish(
            stream, events, args, session, out, EXIT_INTERRUPTED, "interrupted", started
        )
    finally:
        _restore_handlers(previous)
    if terminated.is_set():
        done.wait(_INTERRUPT_GRACE_SECONDS)
        return _finish(
            stream, events, args, session, out, EXIT_TERMINATED, "terminated", started
        )
    return _finish(
        stream, events, args, session, out, box.get("code", 1), "exit", started
    )


def _finish(
    stream: EventStream,
    events: list[SessionEvent],
    args: argparse.Namespace,
    session: str,
    out: TextIO,
    code: int,
    reason: str,
    started: float,
) -> int:
    if code in (EXIT_INTERRUPTED, EXIT_TERMINATED) and not any(
        e.kind == "turn.finished" for e in events
    ):
        stream.emit(
            "turn.finished",
            {
                "outcome": "interrupted",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "verdict": "Stopped. Nothing more was written after the interrupt.",
                "workspace": "nothing was written after the interrupt",
                "changed": None,
                "checkpoint": None,
                "verification": {"status": "not-run", "runs": []},
                "provenance": {"signed": False, "unsigned_files": []},
            },
            turn=1,
        )
    stream.emit(
        "session.ended",
        {
            "reason": reason,
            "turns": 1,
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )
    if args.output_format == "json":
        out.write(
            json.dumps(
                result_object(events, session=session, exit_code=code),
                ensure_ascii=False,
            )
            + "\n"
        )
    elif args.output_format == "text":
        # The answer text; when the turn produced none (it wrote files), the
        # verdict, so a finished run never leaves stdout empty.
        result = result_object(events, session=session, exit_code=code)
        text = result["final_text"] or result["verdict"]
        if text:
            out.write(text if text.endswith("\n") else text + "\n")
    out.flush()
    return code


def _provider_and_model(config: Path) -> tuple[str, str]:
    """The manager provider's name and model from ract.yaml, or "?"."""
    try:
        import yaml

        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        providers = data.get("providers") or {}
        name = str(data.get("manager_provider") or next(iter(providers), "?"))
        return name, str((providers.get(name) or {}).get("model", "?"))
    except Exception as exc:  # noqa: BLE001 -- the run reports config problems itself
        print(f"[headless] could not read {config}: {exc}", file=sys.stderr)
        return "?", "?"


def _install_terminate_handlers(handler: Any) -> list[tuple[int, Any]]:
    """SIGTERM, and SIGBREAK (Ctrl-Break) on Windows, end the run with 143."""
    installed: list[tuple[int, Any]] = []
    if threading.current_thread() is not threading.main_thread():
        return installed
    for name in ("SIGTERM", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            installed.append((signum, signal.signal(signum, handler)))
        except (OSError, ValueError) as exc:
            print(f"[headless] cannot handle {name}: {exc}", file=sys.stderr)
    return installed


def _restore_handlers(installed: list[tuple[int, Any]]) -> None:
    for signum, previous in installed:
        try:
            signal.signal(signum, previous)
        except (OSError, ValueError) as exc:
            print(f"[headless] cannot restore signal {signum}: {exc}", file=sys.stderr)
