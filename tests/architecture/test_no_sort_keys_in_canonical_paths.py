"""Grep-gate: ``json.dumps(sort_keys=True)`` forbidden in canonical paths.

module_03 (v0.5.1 external review response) installed RFC 8785 JCS as the
sacred-spine serialiser. Any hash-input path that still calls
``json.dumps(..., sort_keys=True)`` silently re-opens REVIEW_4_UNKNOWN
§D2 (canonical JSON serialisation flaw): whitespace, float, and
Unicode drift between Python minor versions breaks signature verify.

This gate enforces the invariant post-migration. It scans every
``json.dumps`` call under ``src/ract/`` for the ``sort_keys=True``
argument and fails the build unless the containing file is on the
:data:`_ALLOWLIST` (human-readable report files, YAML output, JSONL
records that are not participants in a hash chain).

Adding a file to :data:`_ALLOWLIST` requires a justification comment.
Removing a file from the allowlist happens only alongside a JCS
migration of every ``sort_keys=True`` call in that file.

Reference: ``_BUILD/ract_v0.5.1_external_review_response/module_03.md``.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

# Files that legitimately use ``json.dumps(sort_keys=True)`` for
# non-canonical purposes (human-readable reports, YAML dumps, JSONL
# records not participating in signatures). Every entry has a
# justification. Paths are relative to ``src/ract/`` in POSIX form.
_ALLOWLIST: dict[str, str] = {
    # Anti-lazy gate reports: written for human inspection with
    # ``indent=2``; not signed, not hashed, not part of the Rootknot
    # canonical bytes.
    "antilazy/coverage.py": "indent=2 human report",
    "antilazy/holdout.py": "indent=2 human report",
    "antilazy/iso_perturb.py": "indent=2 human report",
    "antilazy/mutation.py": "indent=2 human report",
    "antilazy/patchdiff.py": "indent=2 human report",
    "antilazy/symgraph.py": "indent=2 human report (line 785; snapshot_digest_of migrated to dumps_jcs)",
    "antilazy/testintegrity.py": "indent=2 human report",
    # Trace CLI + OTEL export + writer: report artifacts and OTLP export
    # formatter; the on-disk trace line uses dumps_jcs via _write_line
    # (canonical bytes surface).
    "trace/cli_trace.py": "indent=2 test/inspection artifacts",
    "trace/otel.py": "OTLP attribute serialisation with default=str for cross-language export",
    # Provenance + report writers: indent=2 for human review.
    "core/provenance.py": "indent=2 human report",
    # AcceptanceSuite.to_json: indent=2 display form; the signed digest
    # is emitted by AcceptanceSuite.digest which routes through dumps_jcs.
    "core/predicate.py": "to_json indent=2 display; digest() uses dumps_jcs",
    # Providers + CLI: report/conformance artifacts.
    "providers/conformance.py": "indent=2 conformance report",
    "experimental/cli_repro_manifest.py": "indent=2 report artifact",
    "dependency_graph.py": "indent=2 report artifact",
    "run_reporter.py": "predicate invocation display, not signed",
    "plan_replay.py": "result-key comparison string, not signed",
    # Memory session + records + probe scheduler + CLI: JSONL records
    # + YAML output for operator inspection, not part of signature
    # chain.
    "memory/session.py": "indent=2 session dump for operator",
    "memory/failure_records.py": "JSONL failure records for operator inspection",
    "memory/probes/scheduler.py": "human-readable JSON probe schedule",
    "memory/repo_fingerprint.py": "human-readable fingerprint file with ': ' spacing",
}


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


# Matches ``json.dumps(...sort_keys=True...)`` on the same physical line.
# Uses ``.*?`` (any chars, not paren-bounded) so nested calls like
# ``json.dumps(obj.to_canonical(), sort_keys=True)`` still trip the gate.
# Multiline calls (``json.dumps(\n    ...,\n    sort_keys=True,\n    ...)``)
# are caught by the tail-argument variant below.
_INLINE_PATTERN = re.compile(r"json\.dumps\s*\(.*?\bsort_keys\s*=\s*True")

# Matches ``sort_keys=True`` on any line that also carries a running
# ``json.dumps(`` open paren above. To detect this without full Python
# parsing, we run a two-pass: for every ``sort_keys=True`` occurrence,
# check the preceding N lines for an unclosed ``json.dumps(``.
_KWARG_PATTERN = re.compile(r"\bsort_keys\s*=\s*True")
_JSON_DUMPS_OPEN = re.compile(r"json\.dumps\s*\(")


def _strip_comments_and_strings(source: str) -> str:
    """Return ``source`` with comments and string literals blanked out.

    Uses :mod:`tokenize` so scanners see only executable-code tokens
    (identifiers, operators, keywords). Blanking with spaces (rather
    than removing) preserves line numbers so error messages still
    point at the right source line. Falls back to raw source if
    tokenisation fails (e.g., syntax error in a fixture file).
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenizeError, IndentationError, SyntaxError):
        return source
    lines = source.splitlines(keepends=True)
    for tok in tokens:
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            start_row, start_col = tok.start
            end_row, end_col = tok.end
            if start_row == end_row:
                line = lines[start_row - 1]
                lines[start_row - 1] = (
                    line[:start_col]
                    + " " * (end_col - start_col)
                    + line[end_col:]
                )
            else:
                # Multi-line string: blank the interior. Keep leading
                # cols on the first line and trailing cols on the last.
                first = lines[start_row - 1]
                lines[start_row - 1] = (
                    first[:start_col] + " " * (len(first) - start_col)
                )
                for row in range(start_row, end_row - 1):
                    lines[row] = " " * len(lines[row])
                if end_row - 1 < len(lines):
                    last = lines[end_row - 1]
                    lines[end_row - 1] = " " * end_col + last[end_col:]
    return "".join(lines)


def _find_offending_lines(path: Path) -> list[int]:
    """Return 1-based line numbers where ``json.dumps(sort_keys=True)`` is called.

    Only executable code is scanned — docstrings, string literals, and
    comments are blanked out first so a doc example of the anti-pattern
    does not trip the gate.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    stripped = _strip_comments_and_strings(source)
    lines = stripped.splitlines()
    offending: list[int] = []
    for idx, line in enumerate(lines, start=1):
        if _INLINE_PATTERN.search(line):
            offending.append(idx)
            continue
        # Multiline: sort_keys=True on this line, look back up to 8
        # lines for a json.dumps( with no closing paren in between.
        if _KWARG_PATTERN.search(line):
            window_start = max(0, idx - 8)
            window = "\n".join(lines[window_start:idx])
            if _JSON_DUMPS_OPEN.search(window):
                # Count parens between the last json.dumps( and this line.
                anchor = _JSON_DUMPS_OPEN.search(window)
                assert anchor is not None
                after_anchor = window[anchor.end() :]
                depth = 1
                for ch in after_anchor:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            break
                if depth > 0:
                    offending.append(idx)
    return offending


def _iter_python_files() -> list[Path]:
    """Return every ``.py`` file under ``src/ract/`` in deterministic order."""
    root = Path(__file__).resolve().parent.parent.parent / "src" / "ract"
    return sorted(root.rglob("*.py"))


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_no_sort_keys_true_outside_allowlist() -> None:
    """Fail if any non-allowlisted file uses ``json.dumps(sort_keys=True)``."""
    src_root = Path(__file__).resolve().parent.parent.parent / "src" / "ract"
    violations: list[tuple[str, list[int]]] = []
    for py_path in _iter_python_files():
        rel = py_path.relative_to(src_root).as_posix()
        offending = _find_offending_lines(py_path)
        if not offending:
            continue
        if rel in _ALLOWLIST:
            continue
        violations.append((rel, offending))
    if violations:
        report_lines = [
            "The following canonical-path files still use "
            "``json.dumps(..., sort_keys=True)``:",
            "",
        ]
        for rel, lines in violations:
            for lineno in lines:
                report_lines.append(f"  {rel}:{lineno}")
        report_lines.extend(
            [
                "",
                "Migrate each site to ``ract.canonical.dumps_jcs`` (module_03),",
                "or add the file to ``_ALLOWLIST`` with a justification comment.",
                "See ``_BUILD/ract_v0.5.1_external_review_response/module_03.md``.",
            ]
        )
        pytest.fail("\n".join(report_lines))


def test_allowlist_entries_actually_use_sort_keys() -> None:
    """Sanity-check the allowlist: every entry must still contain a hit.

    Prevents stale allowlist entries from lingering after a file has
    been fully migrated. A false entry is a code-hygiene defect worth
    surfacing at the next module close.
    """
    src_root = Path(__file__).resolve().parent.parent.parent / "src" / "ract"
    stale: list[str] = []
    for rel in _ALLOWLIST:
        path = src_root / rel
        if not path.exists():
            stale.append(f"{rel} (allowlisted but file missing)")
            continue
        if not _find_offending_lines(path):
            stale.append(f"{rel} (allowlisted but no sort_keys=True use remains)")
    if stale:
        pytest.fail(
            "Stale allowlist entries — remove from _ALLOWLIST:\n  "
            + "\n  ".join(stale)
        )
