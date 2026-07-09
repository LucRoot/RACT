# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for compression-based novelty detection."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.compression_novelty_detector import CompressionNoveltyDetector
from rootact.executor import Executor
from rootact.handshake_registry import HandshakeItem, HandshakeRegistry
from rootact.manager import Plan, Step
from rootact.rooted import Rooted
from pathlib import Path


class FakeHandshakeRegistry(HandshakeRegistry):
    """In-memory handshake registry that never touches disk."""

    def __init__(self) -> None:
        self._items: list[HandshakeItem] = []

    def _load(self) -> list[dict]:
        return []

    def _save(self, items: list[HandshakeItem]) -> None:
        self._items = list(items)

    def entries(self) -> list[HandshakeItem]:
        return list(self._items)


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
    score = detector.assess_new_artifact("src/new.py", duplicative)

    assert score is not None
    assert score.verdict == "low"
    assert score.ratio < 1.0
    assert score.nearest is not None


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
    score = detector.assess_new_artifact("src/new.py", unrelated)

    assert score is not None
    assert score.verdict == "high"


def test_detector_scores_high_novelty_for_novel_python(tmp_path):
    _seed_diverse_project(tmp_path)
    detector = CompressionNoveltyDetector(tmp_path)

    # Structurally unlike the seeded modules: new class name, new method
    # names, new domain. It is long enough to be structurally distinct from
    # every existing module, so it must score "high", not "nominal".
    novel_python = (
        "class RaftNode:\n"
        "    def __init__(self, node_id, peers):\n"
        "        self.node_id = node_id\n"
        "        self.peers = peers\n"
        "        self.current_term = 0\n"
        "        self.voted_for = None\n"
        "        self.log = []\n"
        "        self.commit_index = 0\n"
        "        self.last_applied = 0\n"
        '        self.state = "follower"\n'
        "\n"
        "    def request_vote(self, candidate_id, term, last_log_index, last_log_term):\n"
        "        if term > self.current_term:\n"
        "            self.current_term = term\n"
        '            self.state = "follower"\n'
        "            self.voted_for = None\n"
        "        if term < self.current_term:\n"
        "            return False\n"
        "        if self.voted_for in (None, candidate_id):\n"
        "            return True\n"
        "        return False\n"
        "\n"
        "    def append_entries(self, leader_id, term, prev_log_index, prev_log_term, entries, leader_commit):\n"
        "        if term < self.current_term:\n"
        "            return False\n"
        "        if prev_log_index >= len(self.log):\n"
        "            return False\n"
        "        for entry in entries:\n"
        "            self.log.append(entry)\n"
        "        if leader_commit > self.commit_index:\n"
        "            self.commit_index = min(leader_commit, len(self.log) - 1)\n"
        "        return True\n"
    )
    score = detector.assess_new_artifact("src/new.py", novel_python)

    assert score is not None
    assert score.verdict == "high"


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


def _write_distinct_modules(project_dir: Path) -> None:
    """Create a small set of structurally distinct Python modules."""
    (project_dir / "raft.py").write_text(
        "class RaftNode:\n"
        "    def __init__(self, node_id, peers):\n"
        "        self.node_id = node_id\n"
        "        self.peers = peers\n"
        "        self.current_term = 0\n"
        "        self.voted_for = None\n"
        "        self.log = []\n"
        "        self.commit_index = 0\n"
        "\n"
        "    def request_vote(self, candidate_id, term, last_log_index, last_log_term):\n"
        "        if term > self.current_term:\n"
        "            self.current_term = term\n"
        "            self.voted_for = None\n"
        "        if term < self.current_term:\n"
        "            return False\n"
        "        if self.voted_for in (None, candidate_id):\n"
        "            return True\n"
        "        return False\n"
        "\n"
        "    def append_entries(self, leader_id, term, prev_log_index, prev_log_term, entries, leader_commit):\n"
        "        if term < self.current_term:\n"
        "            return False\n"
        "        if prev_log_index >= len(self.log):\n"
        "            return False\n"
        "        for entry in entries:\n"
        "            self.log.append(entry)\n"
        "        if leader_commit > self.commit_index:\n"
        "            self.commit_index = min(leader_commit, len(self.log) - 1)\n"
        "        return True\n"
        "\n" * 50,
        encoding="utf-8",
    )
    (project_dir / "parser.py").write_text(
        "class ExprParser:\n"
        "    def __init__(self, tokens):\n"
        "        self.tokens = tokens\n"
        "        self.pos = 0\n"
        "\n"
        "    def peek(self):\n"
        "        if self.pos < len(self.tokens):\n"
        "            return self.tokens[self.pos]\n"
        "        return None\n"
        "\n"
        "    def consume(self):\n"
        "        token = self.peek()\n"
        "        self.pos += 1\n"
        "        return token\n"
        "\n"
        "    def parse_add(self):\n"
        "        left = self.parse_mul()\n"
        "        while self.peek() and self.peek().type == 'PLUS':\n"
        "            self.consume()\n"
        "            right = self.parse_mul()\n"
        "            left = ('add', left, right)\n"
        "        return left\n"
        "\n"
        "    def parse_mul(self):\n"
        "        left = self.parse_atom()\n"
        "        while self.peek() and self.peek().type == 'STAR':\n"
        "            self.consume()\n"
        "            right = self.parse_atom()\n"
        "            left = ('mul', left, right)\n"
        "        return left\n"
        "\n"
        "    def parse_atom(self):\n"
        "        token = self.consume()\n"
        "        if token and token.type == 'NUMBER':\n"
        "            return ('num', token.value)\n"
        "        raise ValueError('expected number')\n"
        "\n" * 40,
        encoding="utf-8",
    )
    (project_dir / "http.py").write_text(
        "class HttpClient:\n"
        "    def __init__(self, base_url, timeout=30):\n"
        "        self.base_url = base_url\n"
        "        self.timeout = timeout\n"
        "        self.session = {}\n"
        "\n"
        "    def get(self, path, headers=None):\n"
        "        url = self.base_url + path\n"
        "        return self._request('GET', url, headers=headers)\n"
        "\n"
        "    def post(self, path, data, headers=None):\n"
        "        url = self.base_url + path\n"
        "        return self._request('POST', url, data=data, headers=headers)\n"
        "\n"
        "    def _request(self, method, url, data=None, headers=None):\n"
        "        if not headers:\n"
        "            headers = {}\n"
        "        headers['Method'] = method\n"
        "        return {'url': url, 'headers': headers, 'data': data}\n"
        "\n"
        "    def close(self):\n"
        "        self.session.clear()\n"
        "\n" * 50,
        encoding="utf-8",
    )


def test_scan_project_uses_leave_one_out_for_existing_files(tmp_path):
    """Distinct existing files should not all be flagged as low novelty.

    Before the leave-one-out fix, scanning a codebase reported most files as
    low because the dictionary contained the file being scored. After the fix,
    structurally distinct files should escape the low bucket.
    """
    _write_distinct_modules(tmp_path)
    detector = CompressionNoveltyDetector(tmp_path)
    result = detector.scan_project()

    low_count = sum(
        1 for score in result["scores"].values() if score["verdict"] == "low"
    )
    assert low_count == 0, f"expected 0 low scores for distinct files, got {low_count}"


def test_scan_project_still_flags_verbatim_duplicates(tmp_path):
    """A file that is a verbatim copy of another file still scores low."""
    _write_distinct_modules(tmp_path)
    content = "def helper_function(x):\n    return x * 2\n\n" * 50
    (tmp_path / "original.py").write_text(content, encoding="utf-8")
    (tmp_path / "copy.py").write_text(content, encoding="utf-8")

    detector = CompressionNoveltyDetector(tmp_path)
    result = detector.scan_project()

    assert "copy.py" in result["scores"]
    assert result["scores"]["copy.py"]["verdict"] == "low"
    assert result["scores"]["copy.py"]["nearest"] == "original.py"


def test_detector_flags_renamed_clone_as_low_novelty(tmp_path):
    """A module whose identifiers are all renamed but structure is identical scores low."""
    existing = (
        "class Rooted:\n"
        "    def __init__(self, assumption, confidence, provenance):\n"
        "        self.assumption = assumption\n"
        "        self.confidence = confidence\n"
        "        self.provenance = provenance\n"
        "        self.value = None\n"
        "\n"
        "    def bind(self, value):\n"
        "        self.value = value\n"
        "        return self\n"
        "\n"
        "    def is_ok(self):\n"
        "        return self.value is not None\n"
    )
    renamed_clone = (
        "class Outcome:\n"
        "    def __init__(self, claim, certainty, lineage):\n"
        "        self.claim = claim\n"
        "        self.certainty = certainty\n"
        "        self.lineage = lineage\n"
        "        self.payload = None\n"
        "\n"
        "    def set(self, payload):\n"
        "        self.payload = payload\n"
        "        return self\n"
        "\n"
        "    def success(self):\n"
        "        return self.payload is not None\n"
    )
    (tmp_path / "existing.py").write_text(existing, encoding="utf-8")
    detector = CompressionNoveltyDetector(tmp_path)
    score = detector.assess_new_artifact("src/new.py", renamed_clone)

    assert score is not None
    assert score.verdict == "low"
    assert score.nearest == "existing.py"


def _write_docstring_heavy_project(project_dir: Path) -> None:
    """Create modules where most bytes are prose inside docstrings/comments."""
    prose = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do "
        "eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco.\n"
    )
    for i in range(6):
        (project_dir / f"module_{i}.py").write_text(
            f'"""Module {i} - {prose}'
            f'"""\n\n'
            f"# Overview: {prose}"
            f"def compute_value_{i}(x):\n"
            f"    # Multiply by {i + 1}\n"
            f"    return x * {i + 1}\n\n"
            f"class DataStore{i}:\n"
            f'    """A data store. {prose}'
            f'    """\n'
            f"    def __init__(self):\n"
            f"        self.items = []\n"
            f"        self._dirty = True\n\n"
            f"    def add(self, item):\n"
            f"        # Add an item to the store. {prose}"
            f"        self.items.append(item)\n"
            f"        self._dirty = True\n\n"
            f"    def get(self, index):\n"
            f"        # Retrieve an item. {prose}"
            f"        return self.items[index]\n\n" + "\n" * 20,
            encoding="utf-8",
        )


def test_detector_discriminates_novel_python_from_prose_in_docstring_heavy_project(
    tmp_path,
):
    """Prose must not look like familiar code just because comments look like prose.

    When the dictionary is trained on docstring-heavy modules, raw compression
    can make prose and novel Python look equally familiar. Stripping prose from
    training samples should keep the gap wide: prose is structurally unlike code
    and should score at least as high as genuinely novel Python.
    """
    _write_docstring_heavy_project(tmp_path)
    detector = CompressionNoveltyDetector(tmp_path)

    novel_python = (
        "class RaftNode:\n"
        "    def __init__(self, node_id, peers):\n"
        "        self.node_id = node_id\n"
        "        self.peers = peers\n"
        "        self.current_term = 0\n"
        "        self.voted_for = None\n"
        "        self.log = []\n"
        "        self.commit_index = 0\n"
        "\n"
        "    def request_vote(self, candidate_id, term, last_log_index, last_log_term):\n"
        "        if term > self.current_term:\n"
        "            self.current_term = term\n"
        "            self.voted_for = None\n"
        "        if term < self.current_term:\n"
        "            return False\n"
        "        if self.voted_for in (None, candidate_id):\n"
        "            return True\n"
        "        return False\n"
    )
    prose = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do "
        "eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim "
        "ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut "
        "aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit "
        "in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
        "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui "
        "officia deserunt mollit anim id est laborum.\n"
    )

    python_score = detector.assess_new_artifact("src/raft.py", novel_python)
    prose_score = detector.assess_new_artifact("src/prose.txt", prose)

    assert python_score is not None
    assert prose_score is not None
    # Prose should compress worse than novel Python once prose is stripped from
    # the training dictionary, so its ratio must be at least as high.
    assert prose_score.ratio >= python_score.ratio, (
        f"prose ratio {prose_score.ratio} should be >= "
        f"novel python ratio {python_score.ratio}"
    )


def _duplicative_content() -> str:
    """Return content that compresses well against the seeded project."""
    return (
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


def test_executor_blocks_low_novelty_without_handshake(tmp_path):
    _seed_diverse_project(tmp_path)
    detector = CompressionNoveltyDetector(tmp_path)
    adapter = FakeAdapter("mock", response_content=_duplicative_content())
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
    assert "Compression novelty gate blocked" in (result.error or "")
    assert not (tmp_path / "src" / "new.py").exists()


def test_executor_routes_low_novelty_to_handshake_queue(tmp_path):
    _seed_diverse_project(tmp_path)
    detector = CompressionNoveltyDetector(tmp_path)
    adapter = FakeAdapter("mock", response_content=_duplicative_content())
    registry = FakeHandshakeRegistry()
    executor = Executor(
        FakeRouter(adapter),
        project_dir=tmp_path,
        compression_novelty_detector=detector,
        handshake_registry=registry,
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
    # The low-novelty step is skipped and no artifact is written.
    assert not (tmp_path / "src" / "new.py").exists()
    assert len(report.step_results) == 0
    assert len(registry.pending()) == 1
    pending = registry.pending()[0]
    assert pending.id == "novelty:src/new.py:1"
    assert "compression ratio" in pending.description
    scores = report.artifacts.get("novelty_scores", [])
    assert len(scores) == 1
    assert scores[0]["artifact"] == "src/new.py"


# RACT 0.1.1 - Trust and Tooling
