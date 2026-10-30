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


def _after_main(argv: list[str]) -> set[str]:
    code = (
        "import ract.cli\n"
        "try:\n"
        f"    ract.cli.main({argv!r})\n"
        "except SystemExit:\n"
        "    pass\n"
    )
    return _loaded_after(code)


def test_version_and_help_do_not_import_httpx() -> None:
    # B-087b: httpx is imported when the first request is made, not at start.
    assert "httpx" not in _after_main(["--version"])
    assert "httpx" not in _after_main(["--help"])


def test_the_first_client_imports_httpx_and_records() -> None:
    loaded = _loaded_after(
        "import ract.cli\n"
        "from ract import egress_ledger\n"
        "assert 'httpx' not in __import__('sys').modules\n"
        "egress_ledger.client('model').close()\n"
    )
    assert "httpx" in loaded


def test_the_lazy_module_reads_through_to_the_real_one() -> None:
    import httpx

    from ract.lazy_import import lazy_module

    lazy = lazy_module("httpx")
    assert lazy.HTTPError is httpx.HTTPError
    assert "loaded" in repr(lazy)
