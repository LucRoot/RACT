# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""CLI command for the Grove Forge benchmark auto-eval hook.

``ract grove-forge eval --results-dir <dir> [--learning-feed] [--json]``
scans Grove Forge benchmark result JSON files, summarizes pass rates and
latencies, and optionally appends structured learnings to the learning
feed.
"""

import argparse
import json
import sys
from pathlib import Path

from ract.experimental.grove_forge_eval import (
    append_to_learning_feed as append_eval_to_learning_feed,
    evaluate_results,
    report_to_dict as eval_report_to_dict,
)
from ract.experimental.grove_forge_guardian import (
    append_to_learning_feed as append_guardian_to_learning_feed,
    report_to_dict as guardian_report_to_dict,
    report_to_markdown,
    scan_grove_forge_reports,
)


def _grove_forge_command(args: list[str]) -> int:
    """Handle ``ract grove-forge <subcommand> ...``."""
    if not args or args[0] in ("-h", "--help"):
        print("usage: ract grove-forge {eval|guardian} ...")
        print("\nSubcommands:")
        print("  eval      Evaluate Grove Forge benchmark results")
        print("  guardian  Scan Grove Forge reports for required markers")
        return 0
    if args and args[0] == "eval":
        return _grove_forge_eval_command(args[1:])
    if args and args[0] == "guardian":
        return _grove_forge_guardian_command(args[1:])
    print(
        "[ract] usage: ract grove-forge {eval|guardian} ...",
        file=sys.stderr,
    )
    return 1


def _grove_forge_eval_command(args: list[str]) -> int:
    """Handle ``ract grove-forge eval --results-dir <dir> [--learning-feed] [--json]``."""
    parser = argparse.ArgumentParser(prog="ract grove-forge eval")
    parser.add_argument(
        "--results-dir",
        required=True,
        type=Path,
        help="Directory containing Grove Forge benchmark result JSON files.",
    )
    parser.add_argument(
        "--learning-feed",
        action="store_true",
        help="Append a learning entry to the learning feed.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the top-level results directory.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the eval report to this JSON file.",
    )
    parsed = parser.parse_args(args)

    report = evaluate_results(parsed.results_dir, recursive=not parsed.no_recursive)

    if parsed.learning_feed:
        written = append_eval_to_learning_feed(report, parsed.results_dir)
        if not written:
            print(
                "[ract] warning: learning feed could not be written",
                file=sys.stderr,
            )

    if parsed.output:
        parsed.output.write_text(
            json.dumps(eval_report_to_dict(report), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if parsed.json_output:
        print(json.dumps(eval_report_to_dict(report), indent=2, ensure_ascii=False))
        return 0

    if report.errors:
        print("[ract] errors:")
        for err in report.errors:
            print(f"  - {err}")
        print()

    print(f"Scanned {len(report.result_files)} result file(s)")
    print(
        f"Aggregate pass rate: {report.aggregate_pass_rate:.2%} "
        f"({report.total_passed}/{report.total_problems})"
    )
    if report.batteries:
        print()
        print("Battery summaries")
        for b in report.batteries:
            print(
                f"  {b.battery}/{b.stack}: "
                f"pass={b.n_passed}/{b.n_problems} ({b.pass_rate:.2%}) "
                f"wall={b.wall_clock_s:.1f}s "
                f"p95={b.p95_wall_s:.1f}s"
            )

    if parsed.learning_feed and report.result_files:
        print("\nAppended learning entry to learning feed.")
    if parsed.output:
        print(f"\nWrote report to {parsed.output}")
    return 0


def _grove_forge_guardian_command(args: list[str]) -> int:
    """Handle ``ract grove-forge guardian --reports-dir <dir> [--learning-feed] [--json|--markdown]``."""
    parser = argparse.ArgumentParser(prog="ract grove-forge guardian")
    parser.add_argument(
        "--reports-dir",
        required=True,
        type=Path,
        help="Directory containing Grove Forge report/artifact Python files.",
    )
    parser.add_argument(
        "--learning-feed",
        action="store_true",
        help="Append a learning entry to the learning feed.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    parser.add_argument(
        "--markdown",
        dest="markdown_output",
        action="store_true",
        help="Emit Markdown instead of human text.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the guardian report to this file.",
    )
    parsed = parser.parse_args(args)

    report = scan_grove_forge_reports(parsed.reports_dir)

    if parsed.learning_feed:
        written = append_guardian_to_learning_feed(report)
        if not written:
            print(
                "[ract] warning: learning feed could not be written",
                file=sys.stderr,
            )

    if parsed.output:
        if parsed.markdown_output:
            parsed.output.write_text(report_to_markdown(report), encoding="utf-8")
        else:
            parsed.output.write_text(
                json.dumps(
                    guardian_report_to_dict(report), indent=2, ensure_ascii=False
                ),
                encoding="utf-8",
            )

    if parsed.json_output:
        print(json.dumps(guardian_report_to_dict(report), indent=2, ensure_ascii=False))
        return 0
    if parsed.markdown_output:
        print(report_to_markdown(report))
        return 0

    print(f"Scanned {report.files_scanned} file(s) in {report.scanned_dir}")
    print(f"Status: {'clean' if report.clean else 'violations found'}")
    if report.violations:
        print(f"Violations: {len(report.violations)}")
        for v in report.violations:
            print(f"  {v['file']}")
            for marker in v["missing"]:
                print(f"    missing: {marker}")

    if parsed.learning_feed:
        print("\nAppended learning entry to learning feed.")
    if parsed.output:
        print(f"\nWrote report to {parsed.output}")
    return 0 if report.clean else 2
