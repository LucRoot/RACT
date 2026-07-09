# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the Executor module."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path
from typing import Any

from rootact.executor import Executor, ExecutionReport
from rootact.hook_system import HookManager
from rootact.manager import Plan, Step
from rootact.rooted import Rooted
from rootact.user_signature_registry import SignatureRegistry


class FakeDiffApplier:
    """DiffApplier that always reports a failure."""

    def __init__(self, message: str = "hunk failed") -> None:
        self.message = message

    def apply_diff(self, _diff_text: str):
        from rootact.diff_applier import DiffApplyResult

        return [
            DiffApplyResult(
                path=Path("foo.py"),
                applied=False,
                backup=None,
                message=self.message,
            )
        ]


class FakeAdapter:
    """A fake provider adapter that returns a deterministic response."""

    def __init__(
        self,
        name: str,
        response_content: str = "done",
        *,
        input_cost: float | None = None,
        output_cost: float | None = None,
    ) -> None:
        self._name = name
        self._response_content = response_content
        self._input_cost = input_cost
        self._output_cost = output_cost

    @property
    def name(self) -> str:
        return self._name

    def capabilities(self) -> set[str]:
        return {"chat"}

    def input_cost_per_1k(self) -> float | None:
        return self._input_cost

    def output_cost_per_1k(self) -> float | None:
        return self._output_cost

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        self.last_temperature = temperature
        return Rooted(
            value={"choices": [{"message": {"content": self._response_content}}]},
            assumption="fake adapter responds",
            confidence=1.0,
            provenance=["fake_adapter.complete"],
        )


class FakeRouter:
    """A fake router that always returns the configured adapter."""

    def __init__(self, adapter: FakeAdapter) -> None:
        self._adapter = adapter

    def select_for_hint(self, hint: str) -> Rooted[Any]:
        return Rooted(
            value=self._adapter,
            assumption="fake router has an adapter",
            confidence=1.0,
            provenance=["fake_router.select_for_hint"],
        )

    def fallback_chain(self, hint: str, max_attempts: int = 3) -> list[Rooted[Any]]:
        """No fallback candidates in unit tests."""
        return []

    def health_check(self, slot_id: str) -> Rooted[bool]:
        return Rooted(
            value=True,
            assumption="fake router always reports healthy",
            confidence=1.0,
            provenance=["fake_router.health_check"],
        )


def _make_plan(
    steps: list[Step], assumption: str = "test assumption", confidence: float = 0.9
) -> Plan:
    return Plan(assumption=assumption, confidence=confidence, steps=steps)


def test_executor_passes_step_specific_temperature():
    adapter = FakeAdapter("mock", response_content="code")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(
                action="write the implementation",
                provider_hint="mock",
                expected_artifact="src/foo.py",
            )
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    assert adapter.last_temperature == 0.15


def test_executor_runs_single_step_and_reports_success():
    adapter = FakeAdapter("mock", response_content="hello world")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert isinstance(report, ExecutionReport)
    assert report.intent == "test intent"
    assert len(report.step_results) == 1
    assert report.step_results[0].content == "hello world"


def test_executor_report_carries_original_plan():
    adapter = FakeAdapter("mock", response_content="hello world")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert report.plan is plan
    assert report.plan.confidence == plan.confidence


def test_executor_writes_artifact_to_project_dir(tmp_path):
    adapter = FakeAdapter("mock", response_content="hello world")
    router = FakeRouter(adapter)
    executor = Executor(router, project_dir=tmp_path)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    artifact_path = tmp_path / "greeting.txt"
    assert artifact_path.is_file()
    assert artifact_path.read_text(encoding="utf-8") == "hello world"


def test_executor_writes_artifact_to_nested_project_dir(tmp_path):
    adapter = FakeAdapter("mock", response_content="def greet(): pass\n")
    router = FakeRouter(adapter)
    executor = Executor(router, project_dir=tmp_path)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="src/foo.py")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    artifact_path = tmp_path / "src" / "foo.py"
    assert artifact_path.is_file()
    assert "def greet():" in artifact_path.read_text(encoding="utf-8")


def test_executor_skips_writing_absolute_artifact_path(tmp_path):
    adapter = FakeAdapter("mock", response_content="hello world")
    router = FakeRouter(adapter)
    executor = Executor(router, project_dir=tmp_path)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="/etc/passwd")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    assert not (tmp_path / "etc" / "passwd").exists()


def test_executor_approval_callback_can_block_step():
    adapter = FakeAdapter("mock", response_content="hello world")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(
        intent="test intent", plan=plan, approval_callback=lambda _step: False
    )

    assert not result.is_ok()
    assert "approval" in (result.error or "").lower()


def test_executor_approval_callback_allows_step_when_true():
    adapter = FakeAdapter("mock", response_content="hello world")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(
        intent="test intent", plan=plan, approval_callback=lambda _step: True
    )

    assert result.is_ok()
    report = result.unwrap()
    assert len(report.step_results) == 1


def test_executor_returns_error_when_provider_missing():
    router = FakeRouter(FakeAdapter("mock"))
    # Override router to simulate missing provider for a specific hint.
    router.select_for_hint = lambda hint: Rooted(
        value=None,
        assumption=f"provider available for {hint}",
        confidence=0.0,
        provenance=["fake_router.select_for_hint"],
        error=f"no provider for {hint}",
    )
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(
                action="greet",
                provider_hint="missing",
                expected_artifact="greeting.txt",
            )
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert not result.is_ok()
    assert "no provider for missing" in str(result.error)


def test_executor_returns_error_when_adapter_completion_fails():
    failing_adapter = FakeAdapter("mock")
    failing_adapter.complete = lambda *args, **kwargs: Rooted(
        value=None,
        assumption="adapter responds",
        confidence=0.0,
        provenance=["fake_adapter.complete"],
        error="model refused",
    )
    router = FakeRouter(failing_adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert not result.is_ok()
    assert "model refused" in (result.error or "")


def test_executor_accumulates_assumptions_from_each_step():
    adapter = FakeAdapter("mock", response_content="ok")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(action="step one", provider_hint="mock", expected_artifact="one.txt"),
            Step(action="step two", provider_hint="mock", expected_artifact="two.txt"),
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert len(report.assumptions) == 3  # plan assumption + one per step
    assert "step one" in report.assumptions[1]
    assert "step two" in report.assumptions[2]


def test_executor_records_provenance_for_each_step():
    adapter = FakeAdapter("mock", response_content="step output")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(action="step one", provider_hint="mock", expected_artifact="one.txt"),
            Step(action="step two", provider_hint="mock", expected_artifact="two.txt"),
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert len(report.provenance) == 2
    assert "one.txt" in report.provenance
    assert "two.txt" in report.provenance
    record = report.provenance["one.txt"]
    assert record.artifact.checksum
    assert record.artifact.size_bytes == len("step output".encode("utf-8"))


def test_executor_classifies_adapter_exception():
    class TimeoutAdapter:
        @property
        def name(self):
            return "timeout_mock"

        def complete(self, *args, **kwargs):
            raise TimeoutError("model timed out")

    router = FakeRouter(TimeoutAdapter())  # type: ignore[arg-type]
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert not result.is_ok()
    assert result.hint == "timeout"
    assert "model timed out" in (result.error or "")


def test_executor_blocks_forbidden_content():
    adapter = FakeAdapter("mock", response_content="result = eval(user_input)")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="generate code", provider_hint="mock", expected_artifact="bad.py")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert not result.is_ok()
    assert result.hint == "safety"
    assert "no-eval" in (result.error or "")


def test_executor_stores_and_tracks_artifacts():
    adapter = FakeAdapter("mock", response_content="step output")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(action="step one", provider_hint="mock", expected_artifact="one.txt"),
            Step(action="step two", provider_hint="mock", expected_artifact="two.txt"),
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert report.artifacts["tracker"] == ["one.txt", "two.txt"]
    store_names = {a["name"] for a in report.artifacts["store"]}
    assert store_names == {"one.txt", "two.txt"}
    assert executor.artifact_tracker.contains("one.txt")
    assert executor.artifact_store.get("two.txt") is not None


def test_executor_runs_pre_and_post_hooks(tmp_path):
    adapter = FakeAdapter("mock", response_content="step output")
    router = FakeRouter(adapter)
    hooks_dir = tmp_path / "hooks"
    hook_manager = HookManager(hooks_dir)
    if __import__("sys").platform == "win32":
        hook_manager.register("pre", "pre_hook", ["cmd", "/c", "echo pre"])
        hook_manager.register("post", "post_hook", ["cmd", "/c", "echo post"])
    else:
        hook_manager.register("pre", "pre_hook", ["sh", "-c", "echo pre"])
        hook_manager.register("post", "post_hook", ["sh", "-c", "echo post"])
    executor = Executor(router, hook_manager=hook_manager)
    plan = _make_plan(
        [Step(action="step one", provider_hint="mock", expected_artifact="one.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    hook_results = report.artifacts.get("hook_results", [])
    assert len(hook_results) == 2
    assert hook_results[0]["name"] == "pre_hook"
    assert hook_results[0]["stdout"].strip() == "pre"
    assert hook_results[1]["name"] == "post_hook"
    assert hook_results[1]["stdout"].strip() == "post"


def test_executor_without_hook_manager_omits_hook_results():
    adapter = FakeAdapter("mock", response_content="step output")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="step one", provider_hint="mock", expected_artifact="one.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert "hook_results" not in report.artifacts


def test_executor_applies_signature_profile(tmp_path):
    adapter = FakeAdapter(
        "mock", response_content="from __future__ import annotations\n\nx = 1\n"
    )
    router = FakeRouter(adapter)
    registry = SignatureRegistry(tmp_path)
    registry.save_profile(
        "custom",
        {"author_marker": "__author__ = 'A'", "knot_marker": "_KNOT = object()"},
    )
    executor = Executor(router, signature_registry=registry, signature_profile="custom")
    plan = _make_plan(
        [Step(action="step one", provider_hint="mock", expected_artifact="one.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert "__author__ = 'A'" in report.step_results[0].content
    assert "_KNOT = object()" in report.step_results[0].content


def test_executor_ignores_signature_failure(tmp_path):
    adapter = FakeAdapter("mock", response_content="step output")
    router = FakeRouter(adapter)
    registry = SignatureRegistry(tmp_path)
    executor = Executor(
        router, signature_registry=registry, signature_profile="missing"
    )
    plan = _make_plan(
        [Step(action="step one", provider_hint="mock", expected_artifact="one.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert report.step_results[0].content == "step output"


class FakeStreamingAdapter(FakeAdapter):
    """A fake adapter that supports streaming."""

    def capabilities(self) -> set[str]:
        return {"chat", "streaming"}

    def complete_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ):
        for token in ["stream", "ed", " ", "content"]:
            yield Rooted(
                value={"choices": [{"delta": {"content": token}, "index": 0}]},
                assumption="fake stream chunk",
                confidence=1.0,
                provenance=["fake_stream"],
            )


def test_executor_uses_streaming_when_adapter_supports_it():
    adapter = FakeStreamingAdapter("mock")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    received: list[str] = []
    result = executor.execute(
        intent="test intent",
        plan=plan,
        stream=True,
        stream_callback=received.append,
    )

    assert result.is_ok()
    report = result.unwrap()
    assert report.step_results[0].content == "streamed content"
    assert received == ["stream", "ed", " ", "content"]


def test_executor_falls_back_to_complete_when_streaming_unsupported():
    adapter = FakeAdapter("mock", response_content="non-stream")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan, stream=True)

    assert result.is_ok()
    report = result.unwrap()
    assert report.step_results[0].content == "non-stream"


from rootact.mcp_adapter import McpAdapter, McpToolRegistry, McpToolResult


class FakeMcpAdapter(McpAdapter):
    """In-memory MCP adapter for executor tests."""

    def list_tools(self) -> Rooted[list[dict[str, Any]]]:
        return Rooted(
            value=[{"name": "read", "description": "read file"}],
            assumption="fake adapter has tools",
            confidence=1.0,
            provenance=["fake_mcp_adapter.list_tools"],
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Rooted[McpToolResult]:
        return Rooted(
            value=McpToolResult(
                tool=name,
                content=[
                    {"type": "text", "text": f"contents of {arguments.get('path')}"}
                ],
            ),
            assumption="fake tool succeeds",
            confidence=1.0,
            provenance=["fake_mcp_adapter.call_tool"],
        )


def test_executor_runs_tool_call_step():
    router = FakeRouter(FakeAdapter("mock"))
    registry = McpToolRegistry()
    registry.register("fs", FakeMcpAdapter())
    executor = Executor(router, mcp_registry=registry)
    plan = _make_plan(
        [
            Step(
                action="read config",
                provider_hint="mcp",
                expected_artifact="",
                tool_call={"name": "fs/read", "arguments": {"path": "config.yaml"}},
            )
        ]
    )

    result = executor.execute(intent="inspect project", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert len(report.step_results) == 1
    assert "config.yaml" in report.step_results[0].content


def test_executor_fails_tool_call_without_registry():
    router = FakeRouter(FakeAdapter("mock"))
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(
                action="read config",
                provider_hint="mcp",
                expected_artifact="",
                tool_call={"name": "fs/read", "arguments": {"path": "config.yaml"}},
            )
        ]
    )

    result = executor.execute(intent="inspect project", plan=plan)

    assert not result.is_ok()
    assert "configured MCP server" in result.error


from rootact.diff_applier import DiffApplier


def test_executor_applies_diff_to_existing_file(tmp_path):
    target = tmp_path / "foo.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_changed\n"
        " line3\n"
    )
    adapter = FakeAdapter("mock", response_content=diff)
    router = FakeRouter(adapter)
    executor = Executor(
        router, project_dir=tmp_path, diff_applier=DiffApplier(tmp_path)
    )
    plan = _make_plan(
        [Step(action="update foo", provider_hint="mock", expected_artifact="foo.py")]
    )

    result = executor.execute(intent="edit foo", plan=plan)

    assert result.is_ok()
    content = target.read_text(encoding="utf-8")
    assert "line2_changed" in content
    assert len(result.unwrap().step_results) == 1


def test_executor_fails_when_diff_applier_missing(tmp_path):
    target = tmp_path / "foo.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_changed\n"
        " line3\n"
    )
    adapter = FakeAdapter("mock", response_content=diff)
    router = FakeRouter(adapter)
    executor = Executor(router, project_dir=tmp_path)
    plan = _make_plan(
        [Step(action="update foo", provider_hint="mock", expected_artifact="foo.py")]
    )

    result = executor.execute(intent="edit foo", plan=plan)

    assert not result.is_ok()
    assert "DiffApplier" in result.error


def test_executor_writes_non_diff_content_normally(tmp_path):
    adapter = FakeAdapter("mock", response_content="new content")
    router = FakeRouter(adapter)
    executor = Executor(
        router, project_dir=tmp_path, diff_applier=DiffApplier(tmp_path)
    )
    plan = _make_plan(
        [Step(action="create foo", provider_hint="mock", expected_artifact="foo.txt")]
    )

    result = executor.execute(intent="create foo", plan=plan)

    assert result.is_ok()
    assert (tmp_path / "foo.txt").read_text(encoding="utf-8") == "new content"


def test_executor_skips_writing_empty_artifact_path(tmp_path):
    adapter = FakeAdapter("mock", response_content="hello world")
    router = FakeRouter(adapter)
    executor = Executor(router, project_dir=tmp_path)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    assert len(list(tmp_path.iterdir())) == 0


class ErrorStreamingAdapter(FakeAdapter):
    """Fake streaming adapter that fails on the second chunk."""

    def capabilities(self) -> set[str]:
        return {"chat", "streaming"}

    def complete_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ):
        yield Rooted(
            value={"choices": [{"delta": {"content": "partial"}}]},
            assumption="first chunk ok",
            confidence=1.0,
            provenance=["fake_stream"],
        )
        yield Rooted(
            value=None,
            assumption="second chunk fails",
            confidence=0.0,
            error="stream broke",
            provenance=["fake_stream"],
        )


def test_executor_surfaces_streaming_chunk_error():
    adapter = ErrorStreamingAdapter("mock")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan, stream=True)

    assert not result.is_ok()
    assert "stream broke" in result.error


def test_executor_tool_call_missing_name_returns_error():
    router = FakeRouter(FakeAdapter("mock"))
    registry = McpToolRegistry()
    registry.register("fs", FakeMcpAdapter())
    executor = Executor(router, mcp_registry=registry)
    plan = _make_plan(
        [
            Step(
                action="read config",
                provider_hint="mcp",
                expected_artifact="",
                tool_call={"name": "", "arguments": {"path": "config.yaml"}},
            )
        ]
    )

    result = executor.execute(intent="inspect project", plan=plan)

    assert not result.is_ok()
    assert "missing 'name'" in result.error


def test_executor_diff_targets_missing_file_returns_error(tmp_path):
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_changed\n"
        " line3\n"
    )
    adapter = FakeAdapter("mock", response_content=diff)
    router = FakeRouter(adapter)
    executor = Executor(
        router, project_dir=tmp_path, diff_applier=DiffApplier(tmp_path)
    )
    plan = _make_plan(
        [Step(action="create foo", provider_hint="mock", expected_artifact="foo.py")]
    )

    result = executor.execute(intent="create foo", plan=plan)

    assert not result.is_ok()
    assert "Diff targets non-existent file" in result.error


class FailingAdapter(FakeAdapter):
    """Fake adapter that returns a Rooted failure."""

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        return Rooted(
            value=None,
            assumption="primary fails",
            confidence=0.0,
            error="primary provider down",
            provenance=["failing_adapter"],
        )


class FallbackRouter(FakeRouter):
    """Router with a primary and fallback adapter."""

    def __init__(self, primary: FakeAdapter, fallback: FakeAdapter) -> None:
        self._primary = primary
        self._fallback = fallback

    def select_for_hint(self, hint: str) -> Rooted[Any]:
        return Rooted(
            value=self._primary,
            assumption="primary selected",
            confidence=1.0,
            provenance=["fallback_router"],
        )

    def fallback_chain(self, hint: str, max_attempts: int = 3) -> list[Rooted[Any]]:
        return [
            Rooted(
                value=self._fallback,
                assumption="fallback selected",
                confidence=1.0,
                provenance=["fallback_router"],
            )
        ]


def test_executor_uses_fallback_adapter_when_primary_fails():
    primary = FailingAdapter("primary")
    fallback = FakeAdapter("fallback", response_content="fallback output")
    router = FallbackRouter(primary, fallback)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    assert result.unwrap().step_results[0].content == "fallback output"


class MetricsAdapter(FakeAdapter):
    """Fake adapter that reports latency and usage for metric tests."""

    def __init__(self, name: str, latency_ms: int = 42) -> None:
        super().__init__(name, input_cost=0.001, output_cost=0.002)
        self._latency_ms = latency_ms

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        self.last_temperature = temperature
        return Rooted(
            value={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                },
                "_ract_latency_ms": self._latency_ms,
            },
            assumption="fake adapter responds with metrics",
            confidence=1.0,
            provenance=["metrics_adapter.complete"],
        )


def test_executor_populates_step_and_report_metrics():
    adapter = MetricsAdapter("metrics")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(
                action="greet",
                provider_hint="metrics",
                expected_artifact="greeting.txt",
            )
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    step_metrics = report.step_results[0].metrics
    assert step_metrics["provider"] == "metrics"
    assert step_metrics["input_tokens"] == 100
    assert step_metrics["output_tokens"] == 50
    assert step_metrics["latency_ms"] == 42
    assert step_metrics["cost"] == 0.0002  # (100*0.001 + 50*0.002) / 1000

    agg = report.metrics
    assert agg["total_input_tokens"] == 100
    assert agg["total_output_tokens"] == 50
    assert agg["total_tokens"] == 150
    assert agg["total_cost"] == 0.0002
    assert agg["total_latency_ms"] == 42
    assert agg["provider_breakdown"]["metrics"]["steps"] == 1


def test_executor_aggregates_metrics_across_multiple_steps():
    adapter = MetricsAdapter("metrics", latency_ms=10)
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [
            Step(action="one", provider_hint="metrics", expected_artifact="one.txt"),
            Step(action="two", provider_hint="metrics", expected_artifact="two.txt"),
        ]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert report.metrics["total_input_tokens"] == 200
    assert report.metrics["total_output_tokens"] == 100
    assert report.metrics["total_tokens"] == 300
    assert report.metrics["total_cost"] == 0.0004
    assert report.metrics["total_latency_ms"] == 20


def test_executor_metrics_empty_when_adapter_has_no_usage():
    adapter = FakeAdapter("mock", response_content="hello")
    router = FakeRouter(adapter)
    executor = Executor(router)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="greeting.txt")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    report = result.unwrap()
    assert report.step_results[0].metrics == {"provider": "mock"}
    assert report.metrics["total_steps"] == 1
    assert report.metrics["steps_with_metrics"] == 0


def test_write_artifact_strips_markdown_fences(tmp_path):
    router = FakeRouter(FakeAdapter("mock"))
    executor = Executor(router, project_dir=tmp_path)
    fenced = "```python\n# Rooted by Dr. Lucas Root, Ph.D.\nx = 1\n```\n"
    executor._write_artifact("src/fenced.py", fenced)
    written = (tmp_path / "src" / "fenced.py").read_text(encoding="utf-8")
    assert "```python" not in written
    assert "```" not in written


def test_extract_json_artifact_wrapper_extracts_matching_artifact():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = '{"artifact": "src/foo.py", "content": "x = 1\\n"}'
    extracted = executor._extract_json_artifact_wrapper(wrapped, "src/foo.py")
    assert extracted == "x = 1\n"


def test_extract_json_artifact_wrapper_ignores_mismatched_artifact():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = '{"artifact": "src/foo.py", "content": "x = 1\n"}'
    assert executor._extract_json_artifact_wrapper(wrapped, "src/bar.py") is None


def test_extract_json_artifact_wrapper_ignores_invalid_json():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    assert executor._extract_json_artifact_wrapper("not json", "src/foo.py") is None


def test_normalize_model_output_extracts_wrapped_python_code():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = (
        '```json\n{"artifact": "src/foo.py", "content": "# code\ndef x(): pass\n"}\n```'
    )
    normalized = executor._normalize_model_output(wrapped, "src/foo.py")
    assert "# code" in normalized
    assert "def x(): pass" in normalized


def test_executor_writes_extracted_artifact_content(tmp_path):
    wrapped = '{"artifact": "src/foo.py", "content": "def greet(): pass\n"}'
    adapter = FakeAdapter("mock", response_content=wrapped)
    router = FakeRouter(adapter)
    executor = Executor(router, project_dir=tmp_path)
    plan = _make_plan(
        [Step(action="greet", provider_hint="mock", expected_artifact="src/foo.py")]
    )

    result = executor.execute(intent="test intent", plan=plan)

    assert result.is_ok()
    artifact_path = tmp_path / "src" / "foo.py"
    assert artifact_path.is_file()
    content = artifact_path.read_text(encoding="utf-8")
    assert "def greet():" in content
    assert "artifact" not in content
    assert "{" not in content


def test_normalize_model_output_strips_leading_artifact_path_and_fence(tmp_path):
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    noisy = "src/foo.py\n```python\n# code\ndef x(): pass\n```"
    normalized = executor._normalize_model_output(noisy, "src/foo.py")
    assert normalized == "# code\ndef x(): pass"


def test_strip_artifact_path_line_ignores_mismatched_first_line():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    content = "not_the_path\n# code\n"
    assert executor._strip_artifact_path_line(content, "src/foo.py") == content


def test_strip_artifact_path_line_is_separator_agnostic_with_crlf():
    """Windows paths and CRLF newlines must match forward-slash model output."""
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    noisy = "tests/test_greeter.py\r\n```python\r\n# code\r\ndef x(): pass\r\n```"
    expected_artifact = "tests\\test_greeter.py"
    normalized = executor._strip_artifact_path_line(noisy, expected_artifact)
    assert normalized == "```python\r\n# code\r\ndef x(): pass\r\n```"


def test_strip_artifact_path_line_matches_forward_slash_expected():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    noisy = "src/foo.py\n# code\n"
    assert executor._strip_artifact_path_line(noisy, "src\\foo.py") == "# code"


def test_executor_surfaces_diff_apply_failure(tmp_path):
    target = tmp_path / "foo.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_changed\n"
        " line3\n"
    )
    adapter = FakeAdapter("mock", response_content=diff)
    router = FakeRouter(adapter)
    executor = Executor(
        router, project_dir=tmp_path, diff_applier=FakeDiffApplier("bad hunk")
    )
    plan = _make_plan(
        [Step(action="update foo", provider_hint="mock", expected_artifact="foo.py")]
    )

    result = executor.execute(intent="edit foo", plan=plan)

    assert not result.is_ok()
    assert "bad hunk" in (result.error or "")
    assert "Diff apply failed" in (result.error or "")


def test_executor_surfaces_mcp_tool_call_failure():
    class FailingMcpAdapter(FakeMcpAdapter):
        def call_tool(self, name: str, arguments: dict[str, Any]) -> Rooted:
            return Rooted(
                value=None,
                assumption="tool succeeds",
                confidence=0.0,
                provenance=["fake_mcp_adapter.call_tool"],
                error="tool refused",
            )

    router = FakeRouter(FakeAdapter("mock"))
    registry = McpToolRegistry()
    registry.register("fs", FailingMcpAdapter())
    executor = Executor(router, mcp_registry=registry)
    plan = _make_plan(
        [
            Step(
                action="read config",
                provider_hint="mcp",
                expected_artifact="",
                tool_call={"name": "fs/read", "arguments": {"path": "config.yaml"}},
            )
        ]
    )

    result = executor.execute(intent="inspect project", plan=plan)

    assert not result.is_ok()
    assert "tool refused" in (result.error or "")


def test_extract_json_artifact_wrapper_tolerant_missing_colon():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = '{"artifact" "src/foo.py" "content" "x = 1"}'
    assert executor._extract_json_artifact_wrapper(wrapped, "src/foo.py") is None


def test_extract_json_artifact_wrapper_tolerant_missing_start_quote():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = '{"artifact": src/foo.py", "content": "x = 1"}'
    assert executor._extract_json_artifact_wrapper(wrapped, "src/foo.py") is None


def test_extract_json_artifact_wrapper_tolerant_missing_end_brace():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = '{"artifact": "src/foo.py", "content": "x = 1"'
    assert executor._extract_json_artifact_wrapper(wrapped, "src/foo.py") is None


def test_extract_json_artifact_wrapper_tolerant_missing_end_quote():
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = '{"artifact": "src/foo.py", "content": "x = 1}'
    assert executor._extract_json_artifact_wrapper(wrapped, "src/foo.py") is None


# RACT 0.1.0 - Initial Public Release


def test_write_artifact_rejects_absolute_path(tmp_path):
    router = FakeRouter(FakeAdapter("mock"))
    executor = Executor(router, project_dir=tmp_path)
    absolute_path = str(Path(tmp_path.anchor) / "evil.txt")
    executor._write_artifact(absolute_path, "evil")
    assert not (tmp_path / "evil.txt").exists()


def test_check_load_bearing_returns_empty_when_no_project_dir():
    from unittest.mock import MagicMock

    router = FakeRouter(FakeAdapter("mock"))
    executor = Executor(router)
    executor.load_bearing_guard = MagicMock()
    assert executor._check_load_bearing("src/foo.py", "content") == []


def test_check_load_bearing_truncates_long_modified_lines_list(tmp_path):
    from rootact.load_bearing_guard import LoadBearingGuard, LoadBearingRegion
    from unittest.mock import MagicMock

    router = FakeRouter(FakeAdapter("mock"))
    executor = Executor(router, project_dir=tmp_path, allow_load_bearing_override=False)
    target = tmp_path / "src" / "foo.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("old content", encoding="utf-8")

    region = LoadBearingRegion(
        path="src/foo.py",
        annotation_line=1,
        reason="legacy quirk",
        start_line=1,
        end_line=2,
    )
    violation = MagicMock()
    violation.region = region
    violation.modified_lines = list(range(1, 10))

    fake_guard = MagicMock(spec=LoadBearingGuard)
    fake_guard.check_modification.return_value = [violation]
    executor.load_bearing_guard = fake_guard

    messages = executor._check_load_bearing("src/foo.py", "new content")
    assert len(messages) == 1
    assert "1,2,3,4,5,..." in messages[0]


def test_duplication_guard_blocks_write(tmp_path):
    from rootact.duplication_guard import DuplicationMatch
    from unittest.mock import MagicMock

    router = FakeRouter(FakeAdapter("mock", response_content="def dup(): pass"))
    executor = Executor(router, project_dir=tmp_path)
    match = DuplicationMatch(
        symbol_id="src.existing.dup",
        name="dup",
        module="src.existing",
        symbol_type="function",
        similarity=0.95,
    )
    fake_guard = MagicMock()
    fake_guard.check.return_value = [match]
    executor.duplication_guard = fake_guard

    plan = _make_plan(
        [Step(action="emit", provider_hint="mock", expected_artifact="src/new.py")]
    )
    result = executor.execute(intent="test intent", plan=plan)

    assert not result.is_ok()
    assert "Duplication guard blocked write" in (result.error or "")
    assert "dup" in (result.error or "")


def test_extract_json_artifact_wrapper_tolerant_missing_value_quote():
    """No opening quote after the colon -> _extract_string returns None at start."""
    executor = Executor(FakeRouter(FakeAdapter("mock")))
    wrapped = '{"artifact": no_quotes}'
    assert executor._extract_json_artifact_wrapper(wrapped, "src/foo.py") is None
