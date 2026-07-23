from __future__ import annotations


import logging

from collections.abc import Callable

from ract.execution_report_diff_extension import DiffExtension
from ract.executor import ExecutionReport
from ract.harness import Harness
from ract.manager import Plan, Step
from ract.memory_arena import MemoryArena
from ract.rooted import Rooted, root_map


logger = logging.getLogger(__name__)


def enrich_harness_run(
    harness: Harness,
    intent: str,
    *,
    mode: str | None = None,
    pre_execute_callback: Callable[[Plan], None] | None = None,
    approval_callback: Callable[[Step], bool] | None = None,
    memory_arena: MemoryArena | None = None,
    stream: bool = False,
    stream_callback: Callable[[str], None] | None = None,
) -> Rooted[ExecutionReport]:
    """
    Run the harness with the given intent and attach a diff summary.

    This function delegates to ``Harness.run`` and, on success, enriches the
    resulting ``ExecutionReport`` with change information via ``DiffExtension``.
    On failure the original error is returned unchanged.

    *pre_execute_callback*, *approval_callback*, *memory_arena*, *stream*,
    and *stream_callback* are forwarded to ``Harness.run``.
    """
    try:
        rooted_result = harness.run(
            intent,
            mode=mode,
            pre_execute_callback=pre_execute_callback,
            approval_callback=approval_callback,
            memory_arena=memory_arena,
            stream=stream,
            stream_callback=stream_callback,
        )
    except Exception as exc:
        logger.exception("Harness execution failed: %s", exc)
        return Rooted(error=str(exc))

    if not rooted_result.is_ok():
        return rooted_result

    return root_map(
        rooted_result,
        lambda report: DiffExtension().attach_diff_summary(report),
        step="harness_report_enricher.attach_diff_summary",
    )


# RACT 0.1.1 - Trust and tooling
