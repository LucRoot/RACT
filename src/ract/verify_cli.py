"""``ract verify`` — one offline check for a range of commits and a run.

Implements ADR-0050 D4 as amended by D-174: every changed line between
two commits is attributed to a recorded step (its file has a Rootknot
whose ``artifact_digest`` matches the bytes at the later commit, and the
knot verifies), and a run's trace chain verifies from GENESIS when the
run has one. A 0.6.0 run writes no trace (D-166), so a run without one
is reported as a fact, never as a break. The command reads only local
files and opens no socket.

Every report ends with :data:`CLOSE_STATEMENT`. The exit code is 0 only
when everything the command could check holds; the report names what it
could not check. A changed line no step wrote is reported as ``not
written by RACT`` and fails only with ``--strict``. Exit 1 when a check
that ran fails; exit 2 when there is nothing to check.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ract.core.provenance import (
    ProvenanceIndex,
    RootknotUnknownSidecarFormat,
    _knot_from_json,
)
from ract.core.rootknot import _KNOWN_SCHEMA_VERSIONS, _ZERO_DIGEST
from ract.core.types import digest_bytes
from ract.git_run import run_git
from ract.provenance_cli import (
    _partial_extended_fields,
    _resolve_pubkey,
    _sidecar_path,
)

CLOSE_STATEMENT = (
    "command records are not part of the signed Rootknot; in this version "
    "they are in .ract/commands.jsonl, which is not signed"
)
TRACE_NONE = "trace: none recorded for this run"
NOT_WRITTEN = "not written by RACT"


def _json_load(line: str) -> dict:
    import json

    try:
        data = json.loads(line)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}

# Statuses a changed file can get. ``fail`` entries decide the exit code
# (with --strict, ``unattributed`` entries fail too).
_OK = "ok"
_FAIL = "fail"
_UNATTRIBUTED = "unattributed"
_COULD_NOT_CHECK = "could not check"


@dataclass
class FileVerdict:
    status: str  # A | M | D as git named it
    path: str
    verdict: str
    kind: str = _FAIL  # one of _OK, _FAIL, _UNATTRIBUTED, _COULD_NOT_CHECK


@dataclass
class VerifyReport:
    range_expr: str | None = None
    run_id: str | None = None
    files: list[FileVerdict] = field(default_factory=list)
    trace_line: str | None = None
    trace_failed: bool = False
    could_not_check: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines: list[str] = ["ract verify"]
        if self.range_expr:
            lines.append(f"range: {self.range_expr}")
        if self.run_id:
            lines.append(f"run: {self.run_id}")
        if self.files:
            lines.append("files:")
            for fv in self.files:
                lines.append(f"  {fv.status} {fv.path}: {fv.verdict}")
        if self.trace_line:
            lines.append(f"trace: {self.trace_line}")
        if self.could_not_check:
            lines.append("could not check:")
            for item in self.could_not_check:
                lines.append(f"  {item}")
        lines.append(CLOSE_STATEMENT)
        return "\n".join(lines)

    def exit_code(self, *, strict: bool, checked_anything: bool) -> int:
        if not checked_anything:
            return 2
        for fv in self.files:
            if fv.kind == _FAIL:
                return 1
            if fv.kind == _UNATTRIBUTED and strict:
                return 1
        if self.trace_failed:
            return 1
        return 0


def _load_knot(repo: Path, path: str):
    """Load the Rootknot recorded for ``path``: sidecar first, then index.

    Returns ``(knot, error)`` with exactly one side set. ``error`` carries
    a refused or unparseable sidecar's reason; ``(None, None)`` means no
    record exists anywhere, which is the ``not written by RACT`` case.
    """
    artifact = repo / path
    sidecar = _sidecar_path(artifact)
    if sidecar.is_file():
        try:
            return _knot_from_json(sidecar.read_text(encoding="utf-8")), None
        except RootknotUnknownSidecarFormat as exc:
            return None, (
                f"unknown sidecar schema literal: {exc}; known values are "
                "'sidecar/v2', 'sidecar/v3', 'sidecar/v4' (or absent for the "
                "legacy v0.3 v1 shape)"
            )
        except Exception as exc:  # noqa: BLE001 - malformed sidecar is a failure
            return None, f"sidecar unparseable: {exc}"
    try:
        index = ProvenanceIndex(repo)
        knot = index.load(artifact)
    except Exception as exc:  # noqa: BLE001 - surface any index failure
        return None, f"no sidecar and index load failed: {exc}"
    if knot is None:
        return None, None
    return knot, None


def _check_knot_bytes(knot, data: bytes) -> tuple[str, str, str]:
    """Verify ``knot`` against ``data``. Returns ``(verdict, kind, detail)``.

    Mirrors ``provenance_cli._check_knot`` (schema invariants, v4 field
    presence, digest, signature, partial fields) but compares against
    bytes taken from a commit rather than a file on disk.
    """
    if knot.schema_version not in _KNOWN_SCHEMA_VERSIONS:
        return (
            f"refused at read: schema_version={knot.schema_version} is not a "
            "known major",
            _FAIL,
            "",
        )
    if knot.schema_version == 4:
        missing: list[str] = []
        if not knot.workspace_digest or knot.workspace_digest == _ZERO_DIGEST:
            missing.append("workspace_digest")
        if not knot.prompt_digest or knot.prompt_digest == _ZERO_DIGEST:
            missing.append("prompt_digest")
        if not knot.run_id:
            missing.append("run_id")
        if missing:
            return (
                f"refused at read: v4 schema-label but v4 fields empty: "
                f"{missing}",
                _FAIL,
                "",
            )
    if digest_bytes(data) != knot.artifact_digest:
        return (
            "changed since it was signed (the bytes at this commit do not "
            "match the knot's artifact_digest)",
            _FAIL,
            "",
        )
    pubkey = _resolve_pubkey(knot)
    if pubkey is None:
        return (
            "cannot be checked: key "
            f"{knot.generator.public_key_id.hex()[:12]} not found",
            _COULD_NOT_CHECK,
            "",
        )
    if not knot.verify(pubkey):
        return (
            "signature does not verify against the generator public key",
            _FAIL,
            "",
        )
    partial = _partial_extended_fields(knot)
    if partial:
        return (
            "attributed and verified (partial: " + ", ".join(partial) + " unset)",
            _OK,
            "",
        )
    return ("attributed and verified", _OK, "")


def _changed_files(repo: Path, from_c: str, to_c: str) -> list[tuple[str, str]]:
    """``[(status, path)]`` between two commits, renames split, NUL-safe."""
    result = run_git(
        "-C", str(repo), "diff", "--name-status", "-z", "--no-renames",
        from_c, to_c,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"ract verify: git could not diff {from_c}..{to_c}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    fields = [
        f for f in result.stdout.decode("utf-8", "replace").split("\0") if f
    ]
    return list(zip(fields[0::2], fields[1::2]))


def _commit_bytes(repo: Path, commit: str, path: str) -> bytes | None:
    result = run_git("-C", str(repo), "show", f"{commit}:{path}")
    if result.returncode != 0:
        return None
    return result.stdout


def _clean_paths(repo: Path, paths: list[str]) -> set[str] | None:
    """Paths among ``paths`` the working tree holds clean at the tip.

    git applies the clean filter before comparing, so a CRLF working file
    counts as clean against an LF blob. Returns None when git status could
    not run (the caller then never uses the working-tree comparison).
    """
    result = run_git("-C", str(repo), "status", "--porcelain", "-z")
    if result.returncode != 0:
        return None
    fields = [
        f for f in result.stdout.decode("utf-8", "replace").split("\0") if f
    ]
    dirty: set[str] = set()
    for entry in fields:
        marker, _, rest = entry.partition(" ")
        rest = rest.split(" -> ", 1)[-1]
        dirty.add(rest)
    return {p for p in paths if p not in dirty}


def _is_ract_record(path: str) -> bool:
    """A sidecar or a path under .ract/: RACT's own record, not a step's file."""
    from pathlib import PurePosixPath

    posix = PurePosixPath(path)
    return (
        posix.parts[0] == ".ract"
        or (posix.name.startswith(".") and posix.name.endswith(".rootknot.json"))
    )


def verify_range(repo: Path, range_expr: str, report: VerifyReport) -> None:
    if ".." not in range_expr:
        raise SystemExit(
            "ract verify: a range is two commits separated by '..' "
            f"(got {range_expr!r})"
        )
    from_c, _, to_c = range_expr.partition("..")
    report.range_expr = range_expr
    changed = _changed_files(repo, from_c, to_c)
    clean = _clean_paths(repo, [p for _s, p in changed])
    for status, path in changed:
        if _is_ract_record(path):
            report.files.append(
                FileVerdict(
                    status, path, "RACT's own sidecar record (D-143); the file "
                    "it attests is checked on its own line", _OK
                )
            )
            continue
        if status in {"A", "M", "T"}:
            data = _commit_bytes(repo, to_c, path)
            if data is None:
                report.files.append(
                    FileVerdict(status, path, "could not read the bytes at the "
                                "later commit", _COULD_NOT_CHECK)
                )
                report.could_not_check.append(f"{path}: bytes at {to_c[:12]}")
                continue
            knot, error = _load_knot(repo, path)
            if error:
                report.files.append(FileVerdict(status, path, error, _FAIL))
            elif knot is None:
                report.files.append(
                    FileVerdict(status, path, NOT_WRITTEN, _UNATTRIBUTED)
                )
            else:
                verdict, kind, _detail = _check_knot_bytes(knot, data)
                if kind == _FAIL and clean is not None and path in clean:
                    # The blob can differ from the signed bytes by the
                    # repository's declared line-ending normalization
                    # (core.autocrlf). For a clean path the working-tree
                    # bytes are exactly what this checkout holds for that
                    # commit; a knot that matches them attests that content.
                    try:
                        tree_bytes = (repo / path).read_bytes()
                    except OSError:
                        tree_bytes = None
                    if tree_bytes is not None:
                        verdict2, kind2, _d2 = _check_knot_bytes(knot, tree_bytes)
                        if kind2 == _OK:
                            verdict, kind = (
                                verdict2 + " (the repository normalizes line "
                                "endings; the digest matches the bytes as this "
                                "checkout holds them)",
                                kind2,
                            )
                report.files.append(FileVerdict(status, path, verdict, kind))
        elif status == "D":
            # The ADR's rule compares the bytes at the later commit; a
            # deleted file has none there, so the knot is checked against
            # the bytes at the earlier commit and the report says so.
            data = _commit_bytes(repo, from_c, path)
            knot, error = _load_knot(repo, path)
            if data is None:
                report.files.append(
                    FileVerdict(status, path, "deleted; could not read the "
                                "bytes at the earlier commit", _COULD_NOT_CHECK)
                )
                report.could_not_check.append(f"{path}: bytes at {from_c[:12]}")
            elif error:
                report.files.append(FileVerdict(status, path, error, _FAIL))
            elif knot is None:
                report.files.append(
                    FileVerdict(
                        status, path,
                        f"deleted at {to_c[:12]}; {NOT_WRITTEN}",
                        _UNATTRIBUTED,
                    )
                )
            else:
                verdict, kind, _detail = _check_knot_bytes(knot, data)
                report.files.append(
                    FileVerdict(
                        status, path,
                        f"deleted at {to_c[:12]}; content at "
                        f"{from_c[:12]}: {verdict}",
                        kind,
                    )
                )
        else:  # U, X and friends: an unmerged or exotic entry
            report.files.append(
                FileVerdict(status, path, "could not check this entry kind",
                            _COULD_NOT_CHECK)
            )
            report.could_not_check.append(f"{path}: entry kind {status}")


def verify_run(repo: Path, run_id: str, runs_root: Path, report: VerifyReport) -> bool:
    """Check the run's trace when it has one. Returns whether it had one."""
    report.run_id = run_id
    log_path = runs_root / run_id / "events.jsonl"
    if not log_path.is_file():
        report.trace_line = TRACE_NONE.replace("trace: ", "")
        return False
    from ract.trace.verify import verify_trace

    result = verify_trace(log_path, run_id_hex=run_id, force_cold=True)
    if result.status in {"VALID", "TORN_TAIL"}:
        report.trace_line = (
            f"valid ({result.events_verified} events; status {result.status})"
        )
    else:
        report.trace_line = (
            f"broken at event {result.tamper_details.get('offset') if result.tamper_details else '?'} "
            f"(status {result.status}; {result.reason})"
        )
        report.trace_failed = True
    # ADR-0050 D4 step 4: verifier runs named in the trace against the
    # output digests in their command records. The trace stores digests,
    # not outputs, so the digests can only be counted, not recomputed;
    # the report says so.
    checked = 0
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = _json_load(line).get("payload") or {}
            if isinstance(payload, dict) and payload.get("output_digest"):
                checked += 1
    except OSError:
        report.could_not_check.append(
            "the trace's command records could not be read for output digests"
        )
        return True
    if checked:
        report.could_not_check.append(
            f"{checked} command records carry an output digest; the outputs "
            "are not stored, so the digests could not be recomputed"
        )
    return True


def verify_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ract verify",
        description=(
            "Check a range of commits and/or a run: every changed line "
            "attributed to a signed step, each Rootknot verified, and the "
            "run's trace chain verified when the run has one. Offline; "
            "reads only local files."
        ),
    )
    parser.add_argument(
        "range_expr",
        nargs="?",
        default=None,
        metavar="FROM..TO",
        help="Two commits; every line changed between them is checked.",
    )
    parser.add_argument("--run", dest="run_id", default=None, help="A run id.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="A changed line no step wrote fails the run (default: reported).",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Print the report as JSON.",
    )
    parser.add_argument(
        "--repo", default=".", type=Path, help="The repository (default: the "
        "working directory)."
    )
    parser.add_argument(
        "--runs-root", default=Path("evals/runs"), type=Path,
        help="Root directory holding <run_id>/events.jsonl (default: "
        "evals/runs).",
    )
    args = parser.parse_args(argv)
    if not args.range_expr and not args.run_id:
        # At least one of a range and a run (D-174 answer 1); argparse's
        # usage error exits 2, the same code as nothing to check.
        parser.error("a commit range and/or --run is required")

    repo = args.repo.resolve()
    report = VerifyReport()
    checked_anything = False
    if args.range_expr:
        verify_range(repo, args.range_expr, report)
        checked_anything = True
    if args.run_id:
        checked_anything = (
            verify_run(repo, args.run_id, args.runs_root, report)
            or checked_anything
        )

    if args.json_output:
        import json as _json

        print(
            _json.dumps(
                {
                    "range": report.range_expr,
                    "run": report.run_id,
                    "files": [
                        {"status": f.status, "path": f.path, "verdict": f.verdict,
                         "kind": f.kind}
                        for f in report.files
                    ],
                    "trace": report.trace_line,
                    "could_not_check": report.could_not_check,
                    "closing": CLOSE_STATEMENT,
                },
                indent=2,
            )
        )
    else:
        print(report.render())
    return report.exit_code(strict=args.strict, checked_anything=checked_anything)


if __name__ == "__main__":
    sys.exit(verify_command(sys.argv[1:]))
