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
stdout. Nothing in headless mode waits for input, except piped stdin, which
is read until it closes: a stdin that sends nothing for the idle timeout ends
the run with exit 2 (B-093), and ``--no-stdin`` skips it.

Exit codes: 0 done, 1 the task failed, 2 usage or configuration error,
3 refused, 4 budget (reserved), 5 interrupted (SIGINT), 6 provider
unavailable, 143 terminated (SIGTERM, or Ctrl-Break on Windows).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import stat
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TextIO

from ract import egress_ledger
from ract.plan_state import plan_items
from ract.session_events import EventStream, JsonlSink, SessionEvent, safe_text
from ract.session_render import PlainRenderer

RESULT_SCHEMA = "ract.result/1"
EXIT_REFUSED = 3
EXIT_INTERRUPTED = 5
EXIT_TERMINATED = 143
_INTERRUPT_GRACE_SECONDS = 0.3

# B-083b: the `error` object of a failed run. `kind` is one of these; the exit
# code says which, except for the three exit-2 errors found before the turn.
ERROR_KINDS = (
    "usage",
    "config",
    "provider",
    "refused",
    "cancelled",
    "budget",
    "stdin_stall",
    "internal",
)
_KIND_BY_EXIT = {
    2: "config",
    3: "refused",
    4: "budget",
    EXIT_INTERRUPTED: "cancelled",
    6: "provider",
    EXIT_TERMINATED: "cancelled",
}
_ERROR_TEXT_LIMIT = 300


def _headless_context_limit(config: Any, provider: str | None) -> int | None:
    """The context window for the headless session.started (B-084)."""
    import yaml

    from ract.context_window import context_limit

    path = Path(config).resolve()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(
            f"[headless] ract.yaml was not read for the context window: {exc}",
            file=sys.stderr,
        )
        data = {}
    providers = data.get("providers") if isinstance(data, dict) else None
    entry = (
        providers.get(provider) if isinstance(providers, dict) and provider else None
    )
    return context_limit(path.parent, entry if isinstance(entry, dict) else None)


def _cut(text: str) -> str:
    """*text* made inert and cut to the error object's limit."""
    clean = safe_text(text)
    if len(clean) <= _ERROR_TEXT_LIMIT:
        return clean
    return clean[: _ERROR_TEXT_LIMIT - 3] + "..."


def error_object(
    exit_code: int, *, kind: str | None = None, message: str = "", hint: str = ""
) -> dict[str, Any] | None:
    """The result's `error`: None for exit 0, otherwise kind, message, hint, exit code.

    An exit code with no kind of its own (1, the task failed for a reason RACT
    does not classify) is `internal`.
    """
    if exit_code == 0:
        return None
    chosen = kind or _KIND_BY_EXIT.get(exit_code, "internal")
    assert chosen in ERROR_KINDS, chosen
    return {
        "kind": chosen,
        "message": _cut(message),
        "hint": _cut(hint),
        "exit_code": exit_code,
    }


def denials(events: list[SessionEvent]) -> list[dict[str, str]]:
    """The approvals this run resolved as denied because nobody could answer (B-193)."""
    asked = {
        e.data.get("id"): e.data for e in events if e.kind == "approval.requested"
    }
    out: list[dict[str, str]] = []
    for event in events:
        data = event.data
        if event.kind != "approval.resolved" or data.get("choice") != "denied":
            continue
        request = asked.get(data.get("id"), {})
        out.append(
            {
                "rule": str(request.get("rule", "")),
                "action": str(request.get("action", "")),
                "tier": str(request.get("tier", "")),
            }
        )
    return out


def _error_from_events(
    events: list[SessionEvent], exit_code: int
) -> dict[str, Any] | None:
    """The error object of a run, from its last `error.surfaced` or its verdict."""
    surfaced = next(
        (e.data for e in reversed(events) if e.kind == "error.surfaced"), None
    )
    finished = next((e.data for e in reversed(events) if e.kind == "turn.finished"), {})
    if surfaced is not None:
        message = str(surfaced.get("message", ""))
        hint = str(surfaced.get("hint", ""))
    else:
        message = str(finished.get("verdict", ""))
        hint = ""
    return error_object(exit_code, message=message, hint=hint)


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
    # V7-06: handled in ract.cli.main() before this parser runs; listed for --help.
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="refuse every request to a host that is not this machine; a model server on localhost still works. A refused request names its purpose and host and is recorded in the egress ledger. RACT_NO_NETWORK=1 does the same; ract.yaml cannot turn either off.",
    )
    parser.add_argument(
        "--no-stdin",
        dest="no_stdin",
        action="store_true",
        help="Do not read stdin (for a parent that leaves it open).",
    )
    parser.add_argument(
        "--token-budget",
        dest="token_budget",
        type=int,
        default=None,
        metavar="N",
        help="Stop before a request that would start at or over N tokens for this run.",
    )
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
        "--accept-edits",
        action="store_true",
        help="let this run change files; without it a step that changes a file "
        "is refused (exit 3), since a headless run cannot ask first",
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
        help="exit 3 at the first action nobody could approve (tier 2 or tier 3)",
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
    from ract.trust import repository_named_host

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
            continue
        url = (
            spec.get("url") or spec.get("base_url") if isinstance(spec, dict) else None
        )
        if isinstance(url, str) and repository_named_host(url):
            found.append({"kind": "network", "name": f"provider {slot}"})
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


# B-093 (D-102): a stdin that sends nothing is announced after NOTICE_AFTER
# seconds and ends the run after the idle timeout; every byte restarts the
# timer and there is no total cap.
NOTICE_AFTER = 5.0
IDLE_TIMEOUT = 30.0
IDLE_TIMEOUT_ENV = "RACT_STDIN_IDLE_TIMEOUT"
_POLL = 0.1


class StdinStalled(Exception):
    """Nothing arrived on piped stdin for the idle timeout."""

    def __init__(self, seconds: float) -> None:
        super().__init__(seconds)
        self.seconds = seconds


def _idle_timeout() -> float:
    raw = os.environ.get(IDLE_TIMEOUT_ENV)
    if raw is None:
        return IDLE_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return IDLE_TIMEOUT
    return value if value > 0 else IDLE_TIMEOUT


def _bytes_ready(fd: int) -> int | None:
    """Bytes readable now on *fd* without blocking (0 when none yet), or None at EOF.

    LR:: Polling, not a reader thread, so a stall is noticed on time and no
    thread is left blocked in a read. Windows pipes have no select(), so the
    pipe is asked with PeekNamedPipe; a closed pipe reads as EOF.
    """
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(fd)
        avail = wintypes.DWORD(0)
        ok = ctypes.windll.kernel32.PeekNamedPipe(
            wintypes.HANDLE(handle), None, 0, None, ctypes.byref(avail), None
        )
        if not ok:
            return None  # the writer closed the pipe (ERROR_BROKEN_PIPE)
        return int(avail.value)
    import select

    readable, _, _ = select.select([fd], [], [], 0)
    return 65536 if readable else 0


def _read_stdin(
    stdin: TextIO,
    *,
    notice: Any = None,
    idle_timeout: float | None = None,
) -> str:
    """Piped stdin until it closes; StdinStalled when nothing arrives in time."""
    if stdin.isatty():
        return ""
    try:
        fd = stdin.fileno()
        mode = os.fstat(fd).st_mode
    except (OSError, ValueError, AttributeError):
        # A stand-in without a descriptor (tests, an embedding caller): read it whole.
        try:
            return stdin.read()
        except (OSError, ValueError):
            return ""
    if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode) or stat.S_ISCHR(mode)):
        try:
            return stdin.read()  # a regular file ends by itself
        except (OSError, ValueError):
            return ""
    limit = _idle_timeout() if idle_timeout is None else idle_timeout
    chunks: list[bytes] = []
    last = time.monotonic()
    noticed = False
    while True:
        try:
            ready = _bytes_ready(fd)
        except (OSError, ValueError) as exc:
            print(
                f"[headless] cannot poll stdin ({exc}); reading it whole",
                file=sys.stderr,
            )
            data = os.read(fd, 1 << 20)
            while data:
                chunks.append(data)
                data = os.read(fd, 1 << 20)
            break
        if ready is None:
            break
        if ready:
            data = os.read(fd, max(ready, 1))
            if not data:
                break
            chunks.append(data)
            last = time.monotonic()
            continue
        idle = time.monotonic() - last
        if not noticed and idle >= NOTICE_AFTER and notice is not None:
            notice(
                "ract: waiting for stdin to close; pass --no-stdin when nothing "
                "is piped"
            )
            noticed = True
        if idle >= limit:
            raise StdinStalled(limit)
        time.sleep(_POLL)
    encoding = getattr(stdin, "encoding", None) or "utf-8"
    return b"".join(chunks).decode(encoding, errors="replace")


def _asks_for_json(argv: list[str]) -> bool:
    """True when *argv* asks for `--output-format json`, read before argparse can fail."""
    for i, arg in enumerate(argv):
        if arg == "--output-format" and i + 1 < len(argv) and argv[i + 1] == "json":
            return True
        if arg == "--output-format=json":
            return True
    return False


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
    events: list[SessionEvent],
    *,
    session: str,
    exit_code: int,
    cost: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The `ract.result/1` object, assembled from the session's events.

    *error* overrides the error object read from the events (B-083b): the
    errors found before a turn starts have no events to read it from.
    """
    finished = next((e.data for e in reversed(events) if e.kind == "turn.finished"), {})
    answer = "".join(
        str(e.data.get("text", ""))
        for e in events
        if e.kind == "agent.text.delta" and e.data.get("channel") == "answer"
    )
    turns = sum(1 for e in events if e.kind == "turn.started")
    plans = [e.data for e in events if e.kind == "plan.proposed"]
    return {
        "schema": RESULT_SCHEMA,
        "outcome": finished.get("outcome", "failed"),
        "exit_code": exit_code,
        # B-083b: null on success; otherwise kind, message, hint, exit_code.
        "error": error if error is not None else _error_from_events(events, exit_code),
        "session": session,
        "turns": turns,
        "verdict": finished.get("verdict", ""),
        # B-137: false when the model went straight to tools and the request
        # ran as one step; null when no plan was proposed.
        "planned": bool(plans[-1].get("planned", True)) if plans else None,
        "final_text": answer,
        "changed": finished.get("changed") or [],
        "verification": finished.get("verification")
        or {"status": "not-run", "runs": []},
        "provenance": finished.get("provenance")
        or {"signed": False, "unsigned_files": []},
        # From the egress ledger (B-044); token counts are null when the
        # provider reported none.
        "cost": cost
        or {"tokens_in": None, "tokens_out": None, "by_purpose": {}, "total_usd": None},
        # B-193: every approval nobody could answer, as {rule, action, tier}.
        "denials": denials(events),
        # Notices are progress on stderr; a CI log reading only stdout sees
        # them here (for example a question answered instead of written).
        "notices": [str(e.data.get("text", "")) for e in events if e.kind == "notice"],
        "events_path": None,
        # The plan steps, from the same events as the live checklist (B-053b).
        "plan": plan_items(events),
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
    as_json = _asks_for_json(argv)

    def early(
        code: int, kind: str, message: str, hint: str, *, printed: bool = False
    ) -> int:
        """The error line on stderr; with --output-format json also the result (B-083b)."""
        if not printed:
            print(f"error: {message}. hint: {hint}", file=err)
        if as_json:
            error = error_object(code, kind=kind, message=message, hint=hint)
            obj = result_object([], session="", exit_code=code, error=error)
            out.write(json.dumps(obj, ensure_ascii=False) + "\n")
            out.flush()
        return code

    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse already printed the usage error
        code = int(exc.code or 0) if exc.code not in (None, 0) else 0
        if code == 0:
            return 0
        return early(
            code,
            "usage",
            "the arguments could not be read (the line above on stderr says which)",
            "ract -p --help",
            printed=True,
        )
    problem = _unsupported(args)
    if problem:
        return early(2, "usage", problem, "run without it")
    words = " ".join(part for part in (args.prompt, *args.rest) if part)
    try:
        piped = (
            ""
            if args.no_stdin
            else _read_stdin(
                stdin or sys.stdin, notice=lambda text: print(text, file=err)
            )
        )
    except StdinStalled as stalled:
        return early(
            2,
            "stdin_stall",
            f"nothing arrived on stdin for {stalled.seconds:g} s and it is still open",
            "pass --no-stdin when nothing is piped, or close stdin "
            f"(the wait is {IDLE_TIMEOUT_ENV} seconds)",
        )
    prompt = build_prompt(words or None, piped)
    if not prompt:
        return early(
            2,
            "usage",
            "no prompt",
            'ract -p "what to do", or pipe it: echo "what to do" | ract -p',
        )
    if not Path(args.config).is_file():
        return early(
            2,
            "config",
            f"configuration file not found: {args.config}",
            "run `ract setup --answers FILE` here (template: ract setup --print-defaults)",
        )

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
    ledger_start = egress_ledger.now()
    terminated = threading.Event()
    done = threading.Event()
    box: dict[str, int] = {}
    # B-193: --fail-on-denial ends the run at the first approval nobody
    # could answer, and the run exits 3.
    first_denial: list[SessionEvent] = []

    def on_denial(event: SessionEvent) -> None:
        if (
            event.kind == "approval.resolved"
            and event.data.get("choice") == "denied"
            and not first_denial
        ):
            first_denial.append(event)
            cancel.set()

    if args.fail_on_denial:
        stream.subscribe(on_denial)
    request = TurnRequest(
        config=Path(args.config),
        intent=prompt,
        session_id=None,
        resume=False,
        ask=args.ask,
        write_lock=threading.RLock(),
        refuse_changes=not args.accept_edits,
        token_budget=args.token_budget,
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
            "mode": "auto-accept" if args.accept_edits else "default",
            "tier3": "off",
            # B-084: measured by the probe or declared in ract.yaml, else null.
            "context_limit": _headless_context_limit(args.config, provider),
            "session_id": getattr(args, "session_id", None),
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
            stream,
            events,
            args,
            session,
            out,
            EXIT_INTERRUPTED,
            "interrupted",
            started,
            ledger_start=ledger_start,
        )
    finally:
        _restore_handlers(previous)
    if terminated.is_set():
        done.wait(_INTERRUPT_GRACE_SECONDS)
        return _finish(
            stream,
            events,
            args,
            session,
            out,
            EXIT_TERMINATED,
            "terminated",
            started,
            ledger_start=ledger_start,
        )
    if first_denial:
        action = next(
            (
                d["action"]
                for d in denials(events)
                if d["action"]
            ),
            "an action",
        )
        stream.error(
            f"stopped at the first denied action (--fail-on-denial): {action}",
            hint="run it in a session at a terminal to answer the approval, "
            "or leave out --fail-on-denial",
            workspace="nothing more was written after the denial",
        )
        return _finish(
            stream,
            events,
            args,
            session,
            out,
            EXIT_REFUSED,
            "exit",
            started,
            ledger_start=ledger_start,
        )
    return _finish(
        stream,
        events,
        args,
        session,
        out,
        box.get("code", 1),
        "exit",
        started,
        ledger_start=ledger_start,
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
    *,
    ledger_start: str,
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
    turn_cost = egress_ledger.cost(
        egress_ledger.since(egress_ledger.read(), ledger_start, this_process=True)
    )
    if args.output_format == "json":
        out.write(
            json.dumps(
                result_object(events, session=session, exit_code=code, cost=turn_cost),
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
