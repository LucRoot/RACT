from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import threading
from typing import Dict, Callable

_ROOT_KNOT = object()

from rootact.manager import Plan, Step


def execute_with_timeout(
    fixture_dict: Dict[str, Callable[[], None]], capsys, timeout_seconds: float
) -> None:
    """
    Execute each fixture in *fixture_dict* with a per-fixture timeout.

    This function runs each zero-argument callable in its own thread,
    waits up to *timeout_seconds* for completion, and captures output via
    ``capsys.readouterr()``.  If a fixture exceeds the timeout, a
    :class:`TimeoutError` is raised indicating which fixture timed out.
    Any exception raised by the fixture is re-raised to preserve original
    validation semantics.

    Parameters
    ----------
    fixture_dict: dict[str, Callable[[], None]]
        Mapping of fixture names to zero-argument callables that perform
        assertions using ``capsys``.
    capsys: pytest.CaptureFixture
        Pytest fixture used to capture stdout and stderr.
    timeout_seconds: float
        Maximum allowed execution time per fixture.

    Raises
    ------
    TimeoutError
        If any fixture runs longer than *timeout_seconds*.
    AssertionError
        If a fixture produces no stdout or stderr output.
    Exception
        Any exception raised by the fixture is propagated.
    """
    for name, func in fixture_dict.items():
        caught: list[BaseException] = []

        def wrapper(f: Callable[[], None] = func) -> None:
            try:
                f()
            except BaseException as exc:
                caught.append(exc)

        thread = threading.Thread(target=wrapper)
        thread.start()
        thread.join(timeout=timeout_seconds)
        if thread.is_alive():
            raise TimeoutError(
                f"Fixture '{name}' timed out after {timeout_seconds} seconds"
            )

        if caught:
            raise caught[0]

        captured = capsys.readouterr()
        if not isinstance(captured.out, str) or not isinstance(captured.err, str):
            raise AssertionError(
                f"Fixture '{name}' did not produce output on stdout or stderr"
            )
        if captured.out == "" and captured.err == "":
            raise AssertionError(
                f"Fixture '{name}' produced no output on stdout or stderr"
            )


_plan = Plan(
    assumption="RootAct must execute fixtures under a per-fixture timeout while preserving capsys capture semantics and propagating assertion/validation errors",
    confidence=0.96,
    steps=[
        Step(
            action="execute_with_timeout",
            provider_hint="internal",
            expected_artifact="None",
        )
    ],
)
# RACT 0.1.0 - Initial Public Release
