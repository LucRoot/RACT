"""B-087: modules that few commands use are not imported at start.

``ract --version`` paid for the provider conformance suite, the structured-
output schema, the response validator and the loop controller.
They load on first use now; every name stays importable where it was.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

LAZY = (
    "ract.providers.conformance",
    "ract.providers.schema",
    "ract.providers.validator",
    "ract.loop_controller",
    "ract.loop_planner",
)


def _loaded_after(code: str) -> set[str]:
    env = dict(os.environ)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            code + "\nimport sys, json\nprint(json.dumps(sorted(sys.modules)))",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert probe.returncode == 0, probe.stderr
    return set(json.loads(probe.stdout.strip().splitlines()[-1]))


def test_importing_the_cli_loads_none_of_them() -> None:
    loaded = _loaded_after("import ract.cli")
    assert not loaded & set(LAZY), sorted(loaded & set(LAZY))


def test_every_name_is_still_importable_from_providers() -> None:
    from ract import providers

    for name in (
        "run_conformance",
        "ConformanceReport",
        "parse_action_dict",
        "to_openai_structured_outputs",
        "ResponseValidator",
        "ValidationOutcome",
    ):
        assert getattr(providers, name) is not None
    from ract.providers import ResponseValidator, run_conformance  # noqa: F401


def test_an_unknown_name_is_still_an_attribute_error() -> None:
    import pytest

    from ract import providers

    with pytest.raises(AttributeError):
        _ = providers.no_such_name


def test_version_still_prints() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "ract.cli", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0 and proc.stdout.strip()
