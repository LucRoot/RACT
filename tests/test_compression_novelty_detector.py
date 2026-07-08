# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for compression-based novelty detection."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.compression_novelty_detector import CompressionNoveltyDetector
from rootact.executor import Executor
from rootact.manager import Plan, Step
from rootact.rooted import Rooted
from pathlib import Path


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


def _seed_diverse_project(project_dir: Path) -> None:
    """Create several diverse Python files so dictionary training succeeds."""
    for i in range(10):
        (project_dir / f"module_{i}.py").write_text(
            f"def compute_value_{i}(x):\n"
            f"    return x * {i + 1}\n"
            f"\n"
            f"class DataStore{i}:\n"
            f"    def __init__(self):\n"
            f"        self.items = []\n"
            f"\n"
            f"    def add(self, item):\n"
            f"        self.items.append(item)\n"
            f"\n"
            f"    def get(self, index):\n"
            f"        return self.items[index]\n"
            f"\n" * 20,
            encoding="utf-8",
        )


def test_detector_scores_low_novelty_for_duplicative_content(tmp_path):
    _seed_diverse_project(tmp_path)
    detector = CompressionNoveltyDetector(tmp_path)

    duplicative = (
        "def compute_value_3(x):\n"
        "    return x * 4\n"
        "\n"
        "class DataStore3:\n"
        "    def __init__(self):\n"
        "        self.items = []\n"
        "\n"
        "    def add(self, item):\n"
        "        self.items.append(item)\n"
    )
    score = detector.score("src/new.py", duplicative)

    assert score is not None
    assert score.verdict == "low"
    assert score.ratio < 1.0


def test_detector_scores_high_novelty_for_unrelated_content(tmp_path):
    _seed_diverse_project(tmp_path)
    detector = CompressionNoveltyDetector(tmp_path)

    unrelated = (
        "class QuantumFluxCapacitor:\n"
        "    def engage(self):\n"
        "        # warp drive calibration\n"
        "        flux = 1.21\n"
        "        return flux * 1000000\n"
        "\n"
        "def navigate_wormhole(entry, exit):\n"
        "    return (entry + exit) / 2\n"
    )
    score = detector.score("src/new.py", unrelated)

    assert score is not None
    assert score.verdict == "high"
    assert score.ratio > 1.0


def test_detector_returns_nominal_for_empty_project(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    detector = CompressionNoveltyDetector(tmp_path)

    score = detector.score("src/new.py", "def f():\n    pass\n")

    assert score is not None
    assert score.verdict == "nominal"
    assert score.ratio == 1.0


def test_detector_handles_empty_content(tmp_path):
    detector = CompressionNoveltyDetector(tmp_path)
    assert detector.score("src/new.py", "") is None


def test_executor_includes_novelty_scores_in_report(tmp_path):
    sample = tmp_path / "existing.py"
    sample.write_text(
        "def helper_function(x):\n    return x * 2\n\n" * 50,
        encoding="utf-8",
    )
    detector = CompressionNoveltyDetector(tmp_path)
    adapter = FakeAdapter("mock", response_content="def helper_function(x): pass\n")
    executor = Executor(
        FakeRouter(adapter), project_dir=tmp_path, compression_novelty_detector=detector
    )
    plan = _make_plan(
        [
            Step(
                action="add helper",
                provider_hint="mock",
                expected_artifact="src/new.py",
            )
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    scores = report.artifacts.get("novelty_scores", [])
    assert len(scores) == 1
    assert scores[0]["artifact"] == "src/new.py"
    assert "verdict" in scores[0]


def test_detector_scan_project_returns_scores(tmp_path):
    (tmp_path / "a.py").write_text(
        "def helper_function(x):\n    return x * 2\n\n" * 50,
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "class TotallyDifferent:\n    pass\n", encoding="utf-8"
    )
    detector = CompressionNoveltyDetector(tmp_path)
    result = detector.scan_project()

    assert "scores" in result
    assert "a.py" in result["scores"]
    assert "b.py" in result["scores"]


# RACT 0.1.0 - Initial Public Release
