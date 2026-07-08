# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the load-bearing weirdness guard."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.executor import Executor
from rootact.load_bearing_guard import LoadBearingGuard
from rootact.manager import Plan, Step
from rootact.rooted import Rooted


class FakeAdapter:
    """Minimal fake provider adapter."""

    def __init__(self, name: str, response_content: str = "ok") -> None:
        self._name = name
        self._response_content = response_content

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict]:
        return Rooted(
            value={"choices": [{"message": {"content": self._response_content}}]},
            assumption="fake adapter responds",
            confidence=1.0,
            provenance=["fake_adapter.complete"],
        )


class FakeRouter:
    """Fake router that always returns the configured adapter."""

    def __init__(self, adapter: FakeAdapter) -> None:
        self._adapter = adapter

    def select_for_hint(self, hint: str) -> Rooted:
        return Rooted(
            value=self._adapter,
            assumption="fake router has an adapter",
            confidence=1.0,
            provenance=["fake_router.select_for_hint"],
        )

    def fallback_chain(self, hint: str, max_attempts: int = 3) -> list[Rooted]:
        return []


def _make_plan(steps: list[Step]) -> Plan:
    return Plan(assumption="test assumption", confidence=0.9, steps=steps)


def test_guard_detects_load_bearing_function(tmp_path):
    source = tmp_path / "legacy.py"
    source.write_text(
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_two()\n"
        "\n"
        "def normal_operation():\n"
        "    pass\n",
        encoding="utf-8",
    )
    guard = LoadBearingGuard(tmp_path)
    regions = guard.scan_file(source)

    assert len(regions) == 1
    assert regions[0].start_line == 1
    assert regions[0].end_line == 4
    assert "race on shutdown" in regions[0].reason


def test_guard_detects_modification_of_protected_region(tmp_path):
    source = tmp_path / "legacy.py"
    original = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_two()\n"
    )
    source.write_text(original, encoding="utf-8")
    guard = LoadBearingGuard(tmp_path)

    modified = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_three()\n"
    )
    violations = guard.check_modification("legacy.py", original, modified)

    assert len(violations) == 1
    assert 4 in violations[0].modified_lines


def test_guard_ignores_unrelated_modifications(tmp_path):
    source = tmp_path / "legacy.py"
    original = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_two()\n"
        "\n"
        "def normal_operation():\n"
        "    pass\n"
    )
    source.write_text(original, encoding="utf-8")
    guard = LoadBearingGuard(tmp_path)

    modified = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_two()\n"
        "\n"
        "def normal_operation():\n"
        "    return 1\n"
    )
    violations = guard.check_modification("legacy.py", original, modified)

    assert violations == []


def test_guard_scans_project(tmp_path):
    (tmp_path / "a.py").write_text(
        "# load-bearing: reason one.\ndef f():\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text("def g():\n    pass\n", encoding="utf-8")
    guard = LoadBearingGuard(tmp_path)
    result = guard.scan_project()

    assert "a.py" in result
    assert "b.py" not in result


def test_executor_blocks_write_touching_load_bearing(tmp_path):
    original = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_two()\n"
    )
    (tmp_path / "legacy.py").write_text(original, encoding="utf-8")

    modified = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_three()\n"
    )
    adapter = FakeAdapter("mock", response_content=modified)
    executor = Executor(FakeRouter(adapter), project_dir=tmp_path)
    plan = _make_plan(
        [Step(action="fix legacy", provider_hint="mock", expected_artifact="legacy.py")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert not result.is_ok()
    assert result.hint == "load-bearing"
    assert "Load-bearing guard blocked write" in (result.error or "")


def test_executor_allows_write_with_override(tmp_path):
    original = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_two()\n"
    )
    (tmp_path / "legacy.py").write_text(original, encoding="utf-8")

    modified = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_three()\n"
    )
    adapter = FakeAdapter("mock", response_content=modified)
    executor = Executor(
        FakeRouter(adapter),
        project_dir=tmp_path,
        allow_load_bearing_override=True,
    )
    plan = _make_plan(
        [Step(action="fix legacy", provider_hint="mock", expected_artifact="legacy.py")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    assert "step_three" in (tmp_path / "legacy.py").read_text(encoding="utf-8")


def test_executor_allows_new_file_even_with_annotation(tmp_path):
    content = (
        "# load-bearing: do not refactor; this ordering prevents a race on shutdown.\n"
        "def fragile_operation():\n"
        "    step_one()\n"
        "    step_two()\n"
    )
    adapter = FakeAdapter("mock", response_content=content)
    executor = Executor(FakeRouter(adapter), project_dir=tmp_path)
    plan = _make_plan(
        [
            Step(
                action="create legacy",
                provider_hint="mock",
                expected_artifact="legacy.py",
            )
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()


# RACT 0.1.0 - Initial Public Release
