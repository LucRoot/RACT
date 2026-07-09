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
    """Create several diverse Python files so dictionary training succeeds.

    The modules share a lot of boilerplate so the trained dictionary strongly
    recognizes the project's lexical patterns, while still varying enough names
    to avoid trivial duplication warnings.
    """
    shared_boilerplate = (
        "    def validate(self):\n"
        "        if not self.items:\n"
        "            raise ValueError('empty')\n"
        "        return True\n"
        "\n"
        "    def reset(self):\n"
        "        self.items.clear()\n"
        "        self._dirty = False\n"
        "\n"
    )
    for i in range(12):
        (project_dir / f"module_{i}.py").write_text(
            f"# Module module_{i} - generated for novelty calibration\n"
            f"def compute_value_{i}(x):\n"
            f"    return x * {i + 1}\n"
            f"\n"
            f"class DataStore{i}:\n"
            f"    def __init__(self):\n"
            f"        self.items = []\n"
            f"        self._dirty = True\n"
            f"\n"
            f"    def add(self, item):\n"
            f"        self.items.append(item)\n"
            f"        self._dirty = True\n"
            f"\n"
            f"    def get(self, index):\n"
            f"        return self.items[index]\n"
            f"\n"
            f"{shared_boilerplate}"
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

    # Deliberately non-Python, lexically distant content so the codebase
    # dictionary should not help compression.
    unrelated = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do "
        "eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim "
        "ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
        "aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit "
        "in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
        "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui "
        "officia deserunt mollit anim id est laborum.\n"
        "\n"
        "The quick brown fox jumps over the lazy dog. Pack my box with five "
        "dozen liquor jugs. How vexingly quick daft zebras jump. "
        "Sphinx of black quartz, judge my vow.\n"
    )
    score = detector.score("src/new.py", unrelated)

    assert score is not None
    # The dictionary should not help compress unrelated prose. We allow
    # "nominal" as well as "high" because exact ratios vary slightly across
    # zstd builds, but the ratio must stay above 1.0 (dictionary did not help).
    assert score.ratio > 1.0
    assert score.verdict in {"high", "nominal"}


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
    # Use structurally distinct content so the enforcing gate does not reject it.
    response_content = (
        "class QuantumFlux:\n"
        "    def calibrate(self, warp):\n"
        "        return warp * 1.21\n"
    )
    adapter = FakeAdapter("mock", response_content=response_content)
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


def _duplicative_helper_content() -> str:
    return "def helper_function(x):\n    return x * 2\n\n" * 50


def test_executor_rejects_low_novelty_write(tmp_path):
    _seed_diverse_project(tmp_path)
    sample = tmp_path / "existing.py"
    sample.write_text(_duplicative_helper_content(), encoding="utf-8")
    detector = CompressionNoveltyDetector(tmp_path)
    adapter = FakeAdapter("mock", response_content=_duplicative_helper_content())
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

    assert not result.is_ok()
    assert result.hint == "novelty"
    assert "Compression novelty gate blocked" in result.error
    assert "Extend" in result.error


def test_executor_allows_low_novelty_write_with_overrun(tmp_path):
    _seed_diverse_project(tmp_path)
    sample = tmp_path / "existing.py"
    sample.write_text(_duplicative_helper_content(), encoding="utf-8")
    detector = CompressionNoveltyDetector(tmp_path)
    adapter = FakeAdapter("mock", response_content=_duplicative_helper_content())
    executor = Executor(
        FakeRouter(adapter),
        project_dir=tmp_path,
        compression_novelty_detector=detector,
        allow_novelty_overrun=True,
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
    assert scores[0]["verdict"] == "low"


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
