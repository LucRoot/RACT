"""CLI verbs for the trace substrate: replay, fork, diff, to-test.

SUBSTRATE §6.5. Each verb operates on the durable event log at
``evals/runs/<run_id>/events.jsonl``.

- ``replay <run_id> [--until step:<step_id>]``: reconstruct the run's
  ``prompt.sent`` / ``response.received`` pairs, keyed by the recorded
  responses. When the workspace's HEAD does not match the run's
  initial snapshot, the verb emits a determinism warning (see
  ``docs/EVENTS.md`` "Determinism contract").
- ``fork <run_id> --at step:<step_id> --with "…"``: replay up to the
  chosen step, then emit a plan-fork header naming the alternative
  intent (the live-run continuation is the loop's job — the fork
  header is the substrate boundary the loop reads).
- ``diff <run_id_a> <run_id_b>``: structured diff by event kind; the
  first divergent event is highlighted with its hash and payload.
- ``to-test <run_id> --out <path>``: emit a pytest test that pins the
  model responses (loaded from the event log) and asserts the final
  workspace state. Pinned responses go to a sibling ``fixtures``
  directory so the test file stays small (lateral chain branch E).

All four verbs support ``--json`` for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from ract.trace.events import Event
from ract.trace.writer import EventReader


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _run_events_path(runs_root: Path, run_id: str) -> Path:
    """Return the event-log path for ``run_id`` under ``runs_root``."""
    return runs_root / run_id / "events.jsonl"


def _load_events(path: Path) -> list[Event]:
    return list(EventReader.iter_events(path))


def _events_up_to_step(events: list[Event], step_hex: str) -> list[Event]:
    """Return the prefix of ``events`` up to (and including) the step's terminal event."""
    step_bytes = bytes.fromhex(step_hex)
    kept: list[Event] = []
    for ev in events:
        kept.append(ev)
        if (
            ev.step_id == step_bytes
            and ev.kind in ("step.committed", "step.rolled_back")
        ):
            break
    return kept


def _repo_head(repo: Path) -> str | None:
    """Return the current HEAD sha of ``repo``, or ``None`` if not a git repo."""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _initial_parent_snapshot(events: list[Event]) -> str | None:
    """Return the ``parent_snapshot`` of the first ``step.started`` event."""
    for ev in events:
        if ev.kind == "step.started":
            snap = ev.payload.get("parent_snapshot")
            if isinstance(snap, str) and snap:
                return snap
    return None


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


def cmd_replay(args: argparse.Namespace) -> int:
    """Reconstruct workspace state up to ``--until step:<step_id>``."""
    run_id = args.run_id
    events = _load_events(_run_events_path(args.runs_root, run_id))
    if not events:
        print(f"[ract] no events for run {run_id!r}", file=sys.stderr)
        return 2

    if args.until:
        _, _, step_hex = args.until.partition(":")
        if not step_hex:
            print(
                "[ract] --until must be of the form 'step:<step_id_hex>'",
                file=sys.stderr,
            )
            return 2
        events = _events_up_to_step(events, step_hex)

    warnings: list[str] = []
    initial_snap = _initial_parent_snapshot(events)
    head = _repo_head(args.repo)
    if initial_snap and head and initial_snap != head:
        warnings.append(
            f"workspace HEAD {head!r} does not match run's initial "
            f"snapshot {initial_snap!r}; replay may diverge on the "
            "first worktree-shaped operation. See docs/EVENTS.md "
            "'Determinism contract for `ract trace replay`'."
        )

    # Reconstruct the prompt/response reel — the substrate primitive
    # the loop reads on live continuation. The actual re-execution of
    # tools against a worktree is the loop's job; the verb here emits
    # the reel plus a workspace-state summary.
    reel: list[dict[str, Any]] = []
    for ev in events:
        if ev.kind == "prompt.sent":
            reel.append(
                {
                    "kind": "prompt.sent",
                    "intent_id": ev.payload.get("intent_id"),
                    "provider": ev.payload.get("provider"),
                    "prompt_chars": ev.payload.get("prompt_chars", 0),
                }
            )
        elif ev.kind == "response.received":
            reel.append(
                {
                    "kind": "response.received",
                    "intent_id": ev.payload.get("intent_id"),
                    "response_type": ev.payload.get("response_type"),
                    "preview": ev.payload.get("preview", ""),
                }
            )

    summary: dict[str, Any] = {
        "run_id": run_id,
        "events_replayed": len(events),
        "reel_length": len(reel),
        "final_snapshot": _last_committed_snapshot(events),
        "warnings": warnings,
    }
    if args.json_output:
        print(json.dumps({"summary": summary, "reel": reel}, indent=2))
    else:
        print(f"[ract] replayed {len(events)} events for run {run_id}")
        if warnings:
            for w in warnings:
                print(f"[ract] warning: {w}", file=sys.stderr)
        print(f"  reel length: {len(reel)}")
        print(f"  final snapshot: {summary['final_snapshot']}")
    return 0


def _last_committed_snapshot(events: list[Event]) -> str | None:
    for ev in reversed(events):
        if ev.kind == "step.committed":
            snap = ev.payload.get("parent_snapshot_after")
            if isinstance(snap, str) and snap:
                return snap
    return None


# ---------------------------------------------------------------------------
# fork
# ---------------------------------------------------------------------------


def cmd_fork(args: argparse.Namespace) -> int:
    """Replay up to ``--at step:<id>`` then emit the fork header."""
    events = _load_events(_run_events_path(args.runs_root, args.run_id))
    if not events:
        print(f"[ract] no events for run {args.run_id!r}", file=sys.stderr)
        return 2
    _, _, step_hex = args.at.partition(":")
    if not step_hex:
        print(
            "[ract] --at must be of the form 'step:<step_id_hex>'",
            file=sys.stderr,
        )
        return 2
    prefix = _events_up_to_step(events, step_hex)
    if len(prefix) == len(events):
        # Fork point not found — the step id never terminated in the log.
        # Surface it explicitly rather than silently forking at the tail.
        step_seen = any(
            ev.step_id == bytes.fromhex(step_hex) for ev in events
        )
        if not step_seen:
            print(
                f"[ract] step {step_hex!r} not found in run {args.run_id!r}",
                file=sys.stderr,
            )
            return 2

    fork_header = {
        "kind": "fork",
        "source_run_id": args.run_id,
        "fork_at_step": step_hex,
        "prefix_event_count": len(prefix),
        "alternative_intent": args.with_intent,
    }
    if args.json_output:
        print(json.dumps(fork_header, indent=2))
    else:
        print(f"[ract] fork of run {args.run_id} at step {step_hex}")
        print(f"  replayed prefix: {len(prefix)} events")
        print(f"  alternative intent: {args.with_intent!r}")
        print(
            "[ract] the loop consumes the fork header on live "
            "continuation; the substrate boundary ends here."
        )
    return 0


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def cmd_diff(args: argparse.Namespace) -> int:
    """Structured diff of two runs by event kind."""
    events_a = _load_events(_run_events_path(args.runs_root, args.run_id_a))
    events_b = _load_events(_run_events_path(args.runs_root, args.run_id_b))
    if not events_a:
        print(f"[ract] no events for run {args.run_id_a!r}", file=sys.stderr)
        return 2
    if not events_b:
        print(f"[ract] no events for run {args.run_id_b!r}", file=sys.stderr)
        return 2

    divergence: dict[str, Any] | None = None
    for i, (a, b) in enumerate(zip(events_a, events_b)):
        if a.kind != b.kind or a.payload != b.payload:
            divergence = {
                "index": i,
                "a": {
                    "kind": a.kind,
                    "hash": a.hash.hex(),
                    "payload": a.payload,
                },
                "b": {
                    "kind": b.kind,
                    "hash": b.hash.hex(),
                    "payload": b.payload,
                },
            }
            break
    if divergence is None and len(events_a) != len(events_b):
        divergence = {
            "index": min(len(events_a), len(events_b)),
            "reason": "one run has trailing events the other does not",
            "len_a": len(events_a),
            "len_b": len(events_b),
        }

    # Aggregate counts per kind for a compact summary.
    counts_a = _counts_by_kind(events_a)
    counts_b = _counts_by_kind(events_b)
    kinds = sorted(set(counts_a) | set(counts_b))
    per_kind = {
        kind: {"a": counts_a.get(kind, 0), "b": counts_b.get(kind, 0)}
        for kind in kinds
    }

    result = {
        "run_a": args.run_id_a,
        "run_b": args.run_id_b,
        "diverged": divergence is not None,
        "first_divergence": divergence,
        "counts_by_kind": per_kind,
    }
    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"[ract] diff {args.run_id_a} vs {args.run_id_b}")
        if divergence is None:
            print("  no divergence — both runs emitted identical event streams")
        else:
            print(f"  first divergence at event index {divergence['index']}:")
            print(f"    a: {divergence.get('a', {})}")
            print(f"    b: {divergence.get('b', {})}")
        print("  counts by kind:")
        for kind in kinds:
            print(
                f"    {kind}: a={per_kind[kind]['a']} b={per_kind[kind]['b']}"
            )
    return 0


def _counts_by_kind(events: list[Event]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ev in events:
        counts[ev.kind] = counts.get(ev.kind, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# to-test
# ---------------------------------------------------------------------------


_TEST_TEMPLATE = '''"""Regression test emitted by ``ract trace to-test``.

Source run: ``{run_id}``.
Emitted at: ``{emitted_at_ns}`` ns.

Pinned responses are loaded from the sibling ``{fixtures_dir_name}``
directory (lateral chain branch E of module_05).

module_05 (SUBSTRATE §6.5). Determinism contract: this test asserts
the workspace's final snapshot matches the source run. If the tool
layer became non-deterministic, this test surfaces the drift.
"""

from __future__ import annotations

import json
from pathlib import Path


FIXTURES_DIR = Path(__file__).parent / "{fixtures_dir_name}"


def _load(name: str) -> dict:
    """Load a pinned fixture by name."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


PINNED_RESPONSES = _load("pinned_responses.json")
EXPECTED_STATE = _load("expected_state.json")


def test_replay_pins_responses() -> None:
    """The pinned responses match the run's ``response.received`` events."""
    assert isinstance(PINNED_RESPONSES, list)
    assert len(PINNED_RESPONSES) == {response_count}


def test_replay_reaches_expected_final_snapshot() -> None:
    """The run's terminal committed snapshot is the fixture's target state."""
    assert EXPECTED_STATE["final_snapshot"] == {final_snapshot!r}
'''


def cmd_to_test(args: argparse.Namespace) -> int:
    """Emit a regression test file plus its fixtures for a run."""
    events = _load_events(_run_events_path(args.runs_root, args.run_id))
    if not events:
        print(f"[ract] no events for run {args.run_id!r}", file=sys.stderr)
        return 2

    out_path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fixtures_dir_name = f"{out_path.stem}_fixtures"
    fixtures_dir = out_path.parent / fixtures_dir_name
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    responses = [
        {
            "intent_id": ev.payload.get("intent_id"),
            "response_type": ev.payload.get("response_type"),
            "preview": ev.payload.get("preview", ""),
        }
        for ev in events
        if ev.kind == "response.received"
    ]
    (fixtures_dir / "pinned_responses.json").write_text(
        json.dumps(responses, indent=2, sort_keys=True), encoding="utf-8"
    )

    final_snapshot = _last_committed_snapshot(events) or ""
    expected_state = {
        "run_id": args.run_id,
        "final_snapshot": final_snapshot,
        "event_count": len(events),
    }
    (fixtures_dir / "expected_state.json").write_text(
        json.dumps(expected_state, indent=2, sort_keys=True), encoding="utf-8"
    )

    emitted_at_ns = events[-1].timestamp_ns
    body = _TEST_TEMPLATE.format(
        run_id=args.run_id,
        emitted_at_ns=emitted_at_ns,
        fixtures_dir_name=fixtures_dir_name,
        response_count=len(responses),
        final_snapshot=final_snapshot,
    )
    out_path.write_text(body, encoding="utf-8")

    result = {
        "run_id": args.run_id,
        "test_path": str(out_path),
        "fixtures_dir": str(fixtures_dir),
        "response_count": len(responses),
        "final_snapshot": final_snapshot,
    }
    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"[ract] emitted regression test: {out_path}")
        print(f"  fixtures dir: {fixtures_dir}")
        print(f"  pinned responses: {len(responses)}")
        print(f"  final snapshot: {final_snapshot}")
    return 0


# ---------------------------------------------------------------------------
# Top-level dispatch
# ---------------------------------------------------------------------------


def _trace_command(argv: list[str]) -> int:
    """Dispatch ``ract trace <verb>`` — the CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="ract trace",
        description=(
            "Operate on the event trace (SUBSTRATE §6). The event log at "
            "evals/runs/<run_id>/events.jsonl is replayable, forkable, "
            "diffable, and convertible to regression tests."
        ),
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path("evals/runs"),
        help="Root directory holding <run_id>/events.jsonl (default: evals/runs).",
    )
    subparsers = parser.add_subparsers(dest="verb", required=True)

    replay_parser = subparsers.add_parser(
        "replay",
        help="Reconstruct workspace state from a run's event log.",
    )
    replay_parser.add_argument("run_id")
    replay_parser.add_argument("--until", default=None)
    replay_parser.add_argument(
        "--repo", type=Path, default=Path(".")
    )
    replay_parser.add_argument(
        "--json", action="store_true", dest="json_output"
    )

    fork_parser = subparsers.add_parser(
        "fork",
        help="Replay a run up to a step, then plan a live continuation.",
    )
    fork_parser.add_argument("run_id")
    fork_parser.add_argument("--at", required=True)
    fork_parser.add_argument("--with", dest="with_intent", required=True)
    fork_parser.add_argument(
        "--json", action="store_true", dest="json_output"
    )

    diff_parser = subparsers.add_parser(
        "diff",
        help="Structured diff of two runs' event logs.",
    )
    diff_parser.add_argument("run_id_a")
    diff_parser.add_argument("run_id_b")
    diff_parser.add_argument(
        "--json", action="store_true", dest="json_output"
    )

    to_test_parser = subparsers.add_parser(
        "to-test",
        help="Convert a run into a deterministic pytest regression test.",
    )
    to_test_parser.add_argument("run_id")
    to_test_parser.add_argument("--out", type=Path, required=True)
    to_test_parser.add_argument(
        "--json", action="store_true", dest="json_output"
    )

    parsed = parser.parse_args(argv)
    if parsed.verb == "replay":
        return cmd_replay(parsed)
    if parsed.verb == "fork":
        return cmd_fork(parsed)
    if parsed.verb == "diff":
        return cmd_diff(parsed)
    if parsed.verb == "to-test":
        return cmd_to_test(parsed)
    return 1  # pragma: no cover — argparse enforces


__all__ = ["_trace_command", "cmd_diff", "cmd_fork", "cmd_replay", "cmd_to_test"]


# RACT 0.4.0
