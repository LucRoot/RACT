"""J4: a request that names a failing test ends with that test run (B-112, B-023).

LR:: After a turn that changed files for a request naming a test (a test
file or node id, or "the test fails"), the session runs the named tests
through ``run_tests``: under the project's grant, asked at the terminal,
with the grant's test rule and the node ids the request names (the whole
rule when it names none). The runs become the turn's verification. When
nothing can run (no grant that holds, nobody to answer, a no), the reason
is kept for the summary's "not verified" line. A run by the scripted
runner never verifies a turn.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

_NODE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*test[\w.-]*\.py(?:::[\w\[\]-]+)*)")


def named_selectors(intent: str) -> list[str]:
    """The test paths and node ids *intent* names, in order, once each."""
    return list(dict.fromkeys(m.group(1) for m in _NODE.finditer(intent or "")))


def run_named_tests(
    project: Path | str,
    intent: str,
    approve: Callable[[dict[str, Any]], bool] | None,
    runner: Any = None,
) -> tuple[list[Any], str]:
    """Run the tests *intent* names; the results, and why nothing ran when nothing did."""
    from ract.policy import tier3
    from ract.tools import run_tool

    project = Path(project)
    ctx = tier3.for_project(project, approve, runner)
    if not ctx.grant.holds:
        return [], f"tier 3 is off: {ctx.grant.reason}"
    if approve is None:
        return [], "nobody can answer the tier-3 question here"
    with tier3.bound(ctx):
        rooted = run_tool(
            project,
            "run_tests",
            {
                "selectors": named_selectors(intent),
                "reason": "the request names this test; RACT runs it to check the turn",
            },
        )
    if not rooted.is_ok():
        return list(ctx.runs), (rooted.error or "the test did not run").removeprefix(
            "run_tests refused: "
        )
    return list(ctx.runs), ""


__all__ = ["named_selectors", "run_named_tests"]
