from __future__ import annotations


"""Executor for RACT.

Runs each step of a plan through the provider selected by the router. Every step
result is Rooted so the harness can decide whether to continue, retry, or stop.
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from ract.artifact_store import Artifact as StoreArtifact, ArtifactStore
from ract.artifact_tracker import ArtifactTracker, TrackedArtifact
from ract.diff_applier import DiffApplier
from ract.duplication_guard import DuplicationGuard
from ract.error_classifier import classify_error
from ract.handshake_registry import HandshakeRegistry
from ract.hook_system import HookManager
from ract.load_bearing_guard import LoadBearingGuard
from ract.manager import Plan, Step
from ract.compression_novelty_detector import CompressionNoveltyDetector
from ract.mcp_adapter import McpToolRegistry
from ract.novelty_budget import NoveltyBudget
from ract.provenance_tracker import Artifact as ProvenanceArtifact, ProvenanceTracker
from ract.providers.base import ProviderAdapter
from ract.providers.router import ProviderRouter
from ract.rooted import Rooted
from ract.core.threat_model import Refusal, authorize_action
from ract.safety_guardrails import SafetyGuardrail
from ract.temperature_router import TemperatureRouter


@dataclass(frozen=True)
class StepResult:
    """Result of executing one plan step."""

    step: Step
    raw_response: dict[str, Any]
    content: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionReport:
    """Aggregate result of executing a plan."""

    intent: str
    step_results: list[StepResult]
    assumptions: list[str]
    provenance: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    plan: Plan | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    refusals: list[Refusal] = field(default_factory=list)


class Executor:
    """Executes a plan step-by-step through selected providers."""

    def __init__(
        self,
        router: ProviderRouter,
        hook_manager: HookManager | None = None,
        project_dir: Path | None = None,
        mcp_registry: McpToolRegistry | None = None,
        diff_applier: DiffApplier | None = None,
        duplication_guard: DuplicationGuard | None = None,
        temperature_router: TemperatureRouter | None = None,
        allow_load_bearing_override: bool = False,
        novelty_budget: NoveltyBudget | None = None,
        allow_novelty_overrun: bool = False,
        compression_novelty_detector: CompressionNoveltyDetector | None = None,
        handshake_registry: HandshakeRegistry | None = None,
        provenance_index: Any = None,
        session_key: Any = None,
        sandbox_signer: Any = None,
        alm_signer: Any = None,
        workspace_snapshot_provider: Callable[[], Any] | None = None,
        prompt_digest_provider: Callable[[], bytes | None] | None = None,
        acceptance_suite_provider: Callable[[], Any] | None = None,
        manifest_digest_provider: Callable[[], Any] | None = None,
        gate_results_provider: Callable[[], tuple] | None = None,
    ) -> None:
        self.router = router
        self.hook_manager = hook_manager
        self.project_dir = project_dir
        self.mcp_registry = mcp_registry
        self.diff_applier = diff_applier
        self.duplication_guard = duplication_guard
        self.temperature_router = temperature_router or TemperatureRouter()
        self.allow_load_bearing_override = allow_load_bearing_override
        self.load_bearing_guard = (
            LoadBearingGuard(project_dir) if project_dir is not None else None
        )
        self.novelty_budget = novelty_budget
        self.allow_novelty_overrun = allow_novelty_overrun
        self.compression_novelty_detector = compression_novelty_detector
        self.handshake_registry = handshake_registry
        # Optional signed-provenance wiring. When both are supplied, every
        # artifact write is signed and indexed (SQLite + sidecar). When absent
        # (the default, preserving prior behavior), writes are untracked.
        self.provenance_index = provenance_index
        self.session_key = session_key
        # v0.5.1 wiring module_02 (Lens D D2): v4 Rootknot deps. When
        # ``sandbox_signer`` + ``alm_signer`` + all four providers are
        # supplied, :meth:`_record_provenance` builds a v4 Rootknot
        # binding the workspace snapshot, prompt digest, and ambient
        # run_id into the signed canonical bytes. When any dep is
        # absent the write-site emits a diagnostic and skips
        # provenance (rather than silently downgrading to v1 -- the
        # entire point of the wire-in is that production Rootknots
        # bind the module_02 fields).
        self.sandbox_signer = sandbox_signer
        self.alm_signer = alm_signer
        self.workspace_snapshot_provider = workspace_snapshot_provider
        self.prompt_digest_provider = prompt_digest_provider
        self.acceptance_suite_provider = acceptance_suite_provider
        self.manifest_digest_provider = manifest_digest_provider
        self.gate_results_provider = gate_results_provider
        self.provenance = ProvenanceTracker()

    def install_v4_provenance_deps(
        self,
        *,
        session_key: Any,
        sandbox_signer: Any,
        alm_signer: Any,
        workspace_snapshot_provider: Callable[[], Any],
        prompt_digest_provider: Callable[[], bytes | None],
        acceptance_suite_provider: Callable[[], Any],
        manifest_digest_provider: Callable[[], Any],
        gate_results_provider: Callable[[], tuple] | None = None,
        provenance_index: Any = None,
    ) -> None:
        """Install the six v4 Rootknot deps after Executor construction.

        v0.5.1 wiring module_02 SP Q2/Q6 amendment (external reviewer
        DEFECT verdict). The pre-v0.5.1 ``Harness.__init__`` constructs
        the Executor before ``LoopController`` has materialised its
        loop state (workspace snapshot, acceptance suite, manifest
        digest) and before per-run signer lifecycle (SandboxKey +
        AlmVerifierKey) has been established. Rather than force the
        Harness to eagerly build stub providers -- and rather than
        block the wire-in on a full harness-plumbing pass (v0.5.2
        scope) -- this setter lets the loop entry install the deps
        exactly once, at the moment the run begins.

        Contract: the setter overwrites any prior wiring. Passing a
        value of ``None`` leaves the corresponding attribute unset,
        which trips the "any dep missing" guard in
        :meth:`_record_provenance` and skips provenance -- callers
        wanting v4 emission must supply ALL six deps (the seventh,
        gate_results_provider, is optional and defaults to an empty
        tuple). ``provenance_index`` is passed through as the
        SQLite/sidecar sink; supply the run's
        :class:`ract.core.provenance.ProvenanceIndex` here.

        A callable-based wire (rather than a value snapshot) is
        chosen so the loop's workspace / suite / manifest state
        evolves per-iteration without re-invoking the setter.

        Full production plumbing (harness -> Executor -> setter)
        remains a v0.5.2 follow-up; the setter is the architectural
        affordance the follow-up snaps into.
        """
        self.session_key = session_key
        self.sandbox_signer = sandbox_signer
        self.alm_signer = alm_signer
        self.workspace_snapshot_provider = workspace_snapshot_provider
        self.prompt_digest_provider = prompt_digest_provider
        self.acceptance_suite_provider = acceptance_suite_provider
        self.manifest_digest_provider = manifest_digest_provider
        self.gate_results_provider = gate_results_provider
        if provenance_index is not None:
            self.provenance_index = provenance_index
        self.artifact_store = ArtifactStore()
        self.artifact_tracker = ArtifactTracker()
        self.guardrail = SafetyGuardrail(
            rules=[
                {
                    "pattern": r"eval\s*\(",
                    "name": "no-eval",
                    "message": "eval() enables arbitrary code execution.",
                },
                {
                    "pattern": r"exec\s*\(",
                    "name": "no-exec",
                    "message": "exec() enables arbitrary code execution.",
                },
                {
                    "pattern": r"subprocess\.[\w]+\([^)]*shell\s*=\s*True",
                    "name": "no-shell-true",
                    "message": "shell=True can enable command injection.",
                },
                {
                    "pattern": r"except\s*:\s*$",
                    "name": "no-bare-except",
                    "message": "Bare except: catches unexpected errors including SystemExit.",
                },
            ]
        )

    @staticmethod
    def _looks_like_diff(content: str) -> bool:
        """Return True if *content* appears to be a unified diff."""
        return content.startswith("diff --git") or (
            content.startswith("--- ") and "+++ " in content.splitlines()[:2]
        )

    def _apply_diff_if_needed(
        self, expected_artifact: str, content: str
    ) -> tuple[bool, str, str]:
        """Apply a diff if content is one and the target exists.

        Returns (is_diff, final_content, message). On failure, final_content is
        the original content and message describes the failure.
        """
        if self.project_dir is None or not self._looks_like_diff(content):
            return False, content, ""
        if self.diff_applier is None:
            return True, content, "Diff detected but no DiffApplier configured."
        target = self.project_dir / expected_artifact
        if not target.is_file():
            return (
                True,
                content,
                f"Diff targets non-existent file {expected_artifact}; writing diff as new file.",
            )
        results = self.diff_applier.apply_diff(content)
        failures = [r for r in results if not r.applied]
        if failures:
            return True, content, f"Diff apply failed: {failures[0].message}"
        # Read the merged file content back so the rest of the pipeline sees
        # the actual file state.
        merged = target.read_text(encoding="utf-8")
        return True, merged, "Diff applied successfully."

    def _check_load_bearing(self, expected_artifact: str, content: str) -> list[str]:
        """Return human-readable violation messages if the write touches protected code.

        LR:: Load-bearing annotations are institutional memory. Modifying them
        without an explicit override is a continuity failure.
        """
        if self.load_bearing_guard is None or not expected_artifact:
            return []
        if self.allow_load_bearing_override:
            return []
        if self.project_dir is None:
            return []
        target = self.project_dir / expected_artifact
        if not target.is_file():
            return []
        old_text = target.read_text(encoding="utf-8")
        violations = self.load_bearing_guard.check_modification(
            expected_artifact, old_text, content
        )
        if not violations:
            return []
        messages: list[str] = []
        for v in violations:
            lines = ",".join(str(n) for n in v.modified_lines[:5])
            if len(v.modified_lines) > 5:
                lines += ",..."
            messages.append(
                f"{v.path} lines {lines}: load-bearing region "
                f"(annotation line {v.region.annotation_line}): {v.region.reason}"
            )
        return messages

    @staticmethod
    def _strip_markdown_fences(content: str) -> str:
        """Remove common markdown code fences from generated content.

        LR:: Local models often wrap code blocks in ```python ... ``` fences.
        Writing those fences to disk produces syntax errors. We strip the
        outermost fence only, preserving any nested code inside. When no fences
        are present the content is returned unchanged so trailing newlines and
        indentation are not accidentally mutated before novelty scoring.
        """
        stripped = content.strip()
        has_fence = stripped.startswith("```") or stripped.endswith("```")
        if not has_fence:
            return content
        if stripped.startswith("```"):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3].rstrip()
        return stripped

    @staticmethod
    def _extract_json_artifact_wrapper(
        content: str, expected_artifact: str
    ) -> str | None:
        """Extract inner content from a JSON artifact wrapper, if present.

        LR:: Some local models emit the artifact as a JSON object like
        {"artifact": "src/foo.py", "content": "..."} instead of raw file
        content. Writing that wrapper to disk produces syntax errors. We
        detect the wrapper only when the ``artifact`` key matches the
        expected path, so legitimate JSON embedded in source files is not
        accidentally stripped.

        The parser is tolerant: it first tries strict JSON, then falls back
        to a line-agnostic extractor that handles multiline pseudo-JSON
        where the content string contains literal newlines or escaped quotes.
        """
        stripped = content.strip()
        if not stripped.startswith("{"):
            return None

        # Strict JSON path.
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            artifact = data.get("artifact")
            inner = data.get("content")
            if artifact == expected_artifact and isinstance(inner, str):
                return inner

        # Tolerant path for models that emit multiline JSON-ish wrappers.
        def _extract_string(text: str, key: str) -> str | None:
            key_pos = text.find(f'"{key}"')
            if key_pos == -1:
                return None
            colon_pos = text.find(":", key_pos)
            if colon_pos == -1:
                return None
            start = text.find('"', colon_pos)
            if start == -1:
                return None
            end_brace = text.rfind("}")
            if end_brace == -1:
                return None
            if key == "content":
                # Content is the last large string before the closing brace.
                # Exclude the opening quote itself so a missing closing quote
                # returns None instead of an empty string.
                end = text.rfind('"', start + 1, end_brace)
            else:
                end = text.find('"', start + 1)
            if end == -1:
                return None
            return text[start + 1 : end]

        artifact = _extract_string(stripped, "artifact")
        inner = _extract_string(stripped, "content")
        if artifact != expected_artifact or inner is None:
            return None
        return (
            inner.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )

    def _normalize_model_output(self, content: str, expected_artifact: str) -> str:
        """Apply all output-normalization heuristics in order.

        LR:: Local models emit artifacts in many noisy formats: raw code,
        markdown-fenced code, JSON wrappers, and the artifact path on its own
        line followed by a fence. We strip each layer until we reach the actual
        file content.
        """
        content = self._strip_markdown_fences(content)
        wrapped = self._extract_json_artifact_wrapper(content, expected_artifact)
        if wrapped is not None:
            content = wrapped
        content = self._strip_markdown_fences(content)
        content = self._strip_artifact_path_line(content, expected_artifact)
        content = self._strip_markdown_fences(content)
        return content

    @staticmethod
    def _strip_artifact_path_line(content: str, expected_artifact: str) -> str:
        """Remove a leading artifact path line such as ``src/foo.py`` or ``src/foo.py:``.

        Some models prefix the generated file with the target path before the
        actual code. Removing it prevents the path from becoming part of the
        source file. The comparison is separator-agnostic so Windows backslash
        paths match forward-slash paths emitted by the model.
        """
        stripped = content.strip()
        first_line, _, remainder = stripped.partition("\n")
        first_line = first_line.strip().rstrip(":").replace("\\", "/")
        if first_line == expected_artifact.replace("\\", "/"):
            return remainder
        return content

    def _write_artifact(self, expected_artifact: str, content: str) -> None:
        """Persist generated content to the project's expected artifact path.

        LR:: Writing is gated by project_dir because the Executor is also used in
        unit tests that do not target a real filesystem. Absolute paths are
        rejected to prevent a plan from escaping the project directory.

        When ``provenance_index`` and ``session_key`` are configured, every
        successful write is signed into a Rootknot and recorded in the index
        (SQLite + sidecar). This makes the executor the single chokepoint that
        binds provenance to artifacts (per ADR-0001 and docs/PROVENANCE.md).
        """
        if self.project_dir is None:
            return
        if not expected_artifact:
            return
        target = Path(expected_artifact)
        if target.is_absolute():
            return
        full_path = self.project_dir / target
        full_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned = self._strip_markdown_fences(content)
        full_path.write_text(cleaned, encoding="utf-8")
        self._record_provenance(full_path, cleaned)

    def _record_provenance(self, full_path: Path, content: str) -> None:
        """Sign and index the artifact just written, if provenance is configured.

        Failures here are logged, not raised: a provenance recording error must
        not corrupt the artifact write itself. The loop's ``verify_workspace``
        step will catch any artifact that ended up without a valid rootknot.

        v0.5.1 wiring module_02 (Lens D D2): the write-site now emits
        v4 Rootknots via :func:`ract.core.rootknot.make_rootknot_v4`.
        v4 binds ``workspace_digest``, ``prompt_digest``, and
        ``run_id`` into the signed canonical bytes so every artifact
        the executor produces attests over the workspace snapshot +
        operator prompt + run identifier in force at write time. The
        four v0.5.1 provider callables (``workspace_snapshot_provider``,
        ``prompt_digest_provider``, ``acceptance_suite_provider``,
        ``manifest_digest_provider``) plus ``sandbox_signer`` +
        ``alm_signer`` must ALL be supplied for v4 to fire; the
        harness wires them from the ``LoopController``. When any dep
        is absent, provenance is skipped -- silently downgrading to
        v1/v3 would defeat the wire-in's whole purpose (a v4-shipping
        executor whose fallback fires a v1 knot is worse than one
        that emits nothing, because the audit can no longer trust the
        "every knot is v4" invariant).
        """
        if (
            self.provenance_index is None
            or self.session_key is None
            or self.project_dir is None
        ):
            return
        # v4 dep-completeness check: all six providers/signers must be
        # populated. Missing any one is a wiring gap upstream and we
        # decline to sign rather than emit a weaker attestation.
        if (
            self.sandbox_signer is None
            or self.alm_signer is None
            or self.workspace_snapshot_provider is None
            or self.prompt_digest_provider is None
            or self.acceptance_suite_provider is None
            or self.manifest_digest_provider is None
        ):
            print(
                f"[executor] provenance skipped for {full_path}: "
                "v4 Rootknot deps not fully wired "
                "(sandbox_signer/alm_signer/workspace/prompt/suite/manifest "
                "providers); see wiring module_02 harness plumbing.",
                flush=True,
            )
            return
        try:
            from ract.core.rootknot import make_rootknot_v4
            from ract.core.types import digest_bytes
            from ract.core.workspace_digest import (
                workspace_digest as _workspace_digest,
            )
            from ract.runtime import get_current_run_id

            artifact_digest = digest_bytes(content.encode("utf-8"))
            # The assumption digest is opaque at the write layer; use a stable
            # placeholder derived from the path so the rootknot is well-formed.
            # The plan/assumption binding is enriched upstream by the loop.
            assumption_digest = digest_bytes(
                str(full_path.relative_to(self.project_dir)).encode("utf-8")
            )
            workspace_path = str(full_path.relative_to(self.project_dir)).replace(
                "\\", "/"
            )
            # v4 field materialisation.
            ws_snapshot = self.workspace_snapshot_provider()
            ws_digest = _workspace_digest(ws_snapshot)
            prompt_digest_raw = self.prompt_digest_provider()
            if prompt_digest_raw is None:
                raise ValueError(
                    "prompt_digest_provider returned None; suite.prompt_digest "
                    "must be populated for a v4 attestation"
                )
            from ract.core.types import Digest as _Digest2

            prompt_digest = _Digest2(
                bytes(prompt_digest_raw)
                if not isinstance(prompt_digest_raw, bytes)
                else prompt_digest_raw
            )
            suite = self.acceptance_suite_provider()
            acceptance_suite_digest_hex = suite.digest()
            # ``AcceptanceSuite.digest()`` returns the SHA-256 hex string
            # of the canonical serialisation; decode to a 32-byte
            # :class:`Digest` for the Rootknot field.
            from ract.core.types import Digest as _Digest

            acceptance_suite_digest = _Digest(
                bytes.fromhex(acceptance_suite_digest_hex)
                if isinstance(acceptance_suite_digest_hex, str)
                else bytes(acceptance_suite_digest_hex)
            )
            manifest_digest_raw = self.manifest_digest_provider()
            from ract.core.types import Digest as _Digest3

            manifest_digest = (
                manifest_digest_raw
                if isinstance(manifest_digest_raw, bytes)
                and len(manifest_digest_raw) == 32
                else _Digest3(bytes(manifest_digest_raw))
            )
            gate_results = (
                self.gate_results_provider()
                if self.gate_results_provider is not None
                else ()
            )
            run_id = get_current_run_id() or ""
            if not run_id:
                raise ValueError(
                    "no ambient run_id bound; call ract.runtime.bind_run_id() "
                    "in the loop entry before writing artifacts"
                )
            knot = make_rootknot_v4(
                key=self.session_key,
                sandbox_signer=self.sandbox_signer,
                alm_signer=self.alm_signer,
                workspace_path=workspace_path,
                artifact_digest=artifact_digest,
                assumption_digest=assumption_digest,
                acceptance_suite_digest=acceptance_suite_digest,
                predicate_results=(),
                manifest_digest=manifest_digest,
                gate_results=tuple(gate_results),
                workspace_digest=ws_digest,
                prompt_digest=prompt_digest,
                run_id=run_id,
            )
            self.provenance_index.save(knot, full_path)
        except Exception as exc:  # noqa: BLE001 - log and continue (see docstring)
            print(
                f"[executor] v4 provenance recording failed for {full_path}: {exc}",
                flush=True,
            )

    def _stream_completion(
        self,
        adapter: Any,
        messages: list[dict[str, str]],
        stream_callback: Callable[[str], None] | None,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        """Collect a streaming completion into a synthetic raw response dict."""
        start = time.perf_counter()
        collected: list[str] = []
        for chunk_rooted in adapter.complete_stream(
            messages, max_tokens=1024, temperature=temperature
        ):
            if not chunk_rooted.is_ok():
                return chunk_rooted
            chunk = chunk_rooted.unwrap()
            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if delta:
                collected.append(delta)
                if stream_callback is not None:
                    stream_callback(delta)

        latency_ms = int((time.perf_counter() - start) * 1000)
        content = "".join(collected)
        return Rooted(
            value={
                "choices": [
                    {
                        "message": {"content": content},
                        "delta": {"content": content},
                    }
                ],
                "_ract_latency_ms": latency_ms,
            },
            assumption="Streaming completion produced aggregated content.",
            confidence=1.0,
            provenance=["executor._stream_completion"],
        )

    def _extract_step_metrics(
        self, adapter: ProviderAdapter, raw: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract latency, token usage, and cost from a provider response."""
        metrics: dict[str, Any] = {"provider": adapter.name}
        latency_ms = raw.get("_ract_latency_ms")
        if latency_ms is not None:
            metrics["latency_ms"] = latency_ms

        usage = raw.get("usage", {})
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        if input_tokens is not None:
            metrics["input_tokens"] = input_tokens
        if output_tokens is not None:
            metrics["output_tokens"] = output_tokens

        input_cost = getattr(adapter, "input_cost_per_1k", lambda: None)()
        output_cost = getattr(adapter, "output_cost_per_1k", lambda: None)()
        if (
            input_tokens is not None
            and output_tokens is not None
            and input_cost is not None
            and output_cost is not None
        ):
            metrics["cost"] = round(
                (input_tokens * input_cost + output_tokens * output_cost) / 1000, 6
            )

        return metrics

    @staticmethod
    def _aggregate_step_metrics(step_results: list[StepResult]) -> dict[str, Any]:
        """Roll up per-step metrics into execution-level totals.

        LR:: A run report should show the user exactly what they spent and how
        long it took, per provider and in aggregate. This aggregation is
        deterministic and provider-agnostic.
        """
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        total_latency_ms = 0
        provider_breakdown: dict[str, dict[str, Any]] = {}
        steps_with_metrics = 0

        for sr in step_results:
            m = sr.metrics
            if not m:
                continue
            has_meaningful_metrics = any(
                k in m and m[k] not in (None, 0, 0.0)
                for k in ("input_tokens", "output_tokens", "latency_ms", "cost")
            )
            if not has_meaningful_metrics:
                continue
            steps_with_metrics += 1
            provider = m.get("provider", "unknown")
            input_tokens = m.get("input_tokens", 0) or 0
            output_tokens = m.get("output_tokens", 0) or 0
            cost = m.get("cost", 0.0) or 0.0
            latency_ms = m.get("latency_ms", 0) or 0

            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            total_cost += cost
            total_latency_ms += latency_ms

            if provider not in provider_breakdown:
                provider_breakdown[provider] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost": 0.0,
                    "latency_ms": 0,
                    "steps": 0,
                }
            provider_breakdown[provider]["input_tokens"] += input_tokens
            provider_breakdown[provider]["output_tokens"] += output_tokens
            provider_breakdown[provider]["cost"] += cost
            provider_breakdown[provider]["latency_ms"] += latency_ms
            provider_breakdown[provider]["steps"] += 1

        return {
            "steps_with_metrics": steps_with_metrics,
            "total_steps": len(step_results),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "total_cost": round(total_cost, 6),
            "total_latency_ms": total_latency_ms,
            "provider_breakdown": provider_breakdown,
        }

    def _execute_provider_step_with_fallback(
        self,
        step: Step,
        context: str | None,
        index: int,
        stream: bool,
        stream_callback: Callable[[str], None] | None,
    ) -> Rooted[tuple[dict[str, Any], str, dict[str, Any]]]:
        """Run a provider step, falling back to the next best provider on failure.

        LR:: A single unreachable provider should not stall the loop. The router
        exposes a fallback chain ordered by capability score; we try each until
        one succeeds and record which provider ultimately executed the step.
        """
        primary = self.router.select_for_hint(step.provider_hint)
        if not primary.is_ok():
            return Rooted(
                value=None,
                assumption=f"A provider is available for hint '{step.provider_hint}'.",
                confidence=0.0,
                provenance=[f"executor.step:{index}"],
                error=primary.error,
                hint="routing",
            )

        candidates: list[ProviderAdapter] = [primary.unwrap()]
        for candidate_rooted in self.router.fallback_chain(step.provider_hint):
            if candidate_rooted.is_ok():
                candidate = candidate_rooted.unwrap()
                if candidate not in candidates:
                    candidates.append(candidate)

        user_content = (
            f"Task: {step.action}\nExpected artifact: {step.expected_artifact}"
        )
        if context:
            user_content = f"{context}\n\n{user_content}"
        messages = [
            {
                "role": "system",
                "content": "You are a precise coding assistant. Produce the requested artifact.",
            },
            {"role": "user", "content": user_content},
        ]

        temperature = self.temperature_router.for_action(step.action)
        errors: list[str] = []
        hints: list[str] = []
        for adapter in candidates:
            try:
                if stream and "streaming" in adapter.capabilities():
                    response_rooted = self._stream_completion(
                        adapter, messages, stream_callback, temperature=temperature
                    )
                else:
                    response_rooted = adapter.complete(
                        messages, max_tokens=1024, temperature=temperature
                    )
            except Exception as exc:  # noqa: BLE001
                info = classify_error(exc)
                errors.append(f"{adapter.name}: {info.category} {info.message}")
                hints.append(info.category)
                continue

            if response_rooted.is_ok():
                raw = response_rooted.unwrap()
                content = (
                    raw.get("choices", [{}])[0].get("message", {}).get("content", "")
                )
                metrics = self._extract_step_metrics(adapter, raw)
                return Rooted(
                    value=(raw, content, metrics),
                    assumption=f"Provider '{adapter.name}' executed step {index}.",
                    confidence=1.0,
                    provenance=[
                        f"executor.step:{index}",
                        f"provider:{adapter.name}",
                    ],
                )

            errors.append(f"{adapter.name}: {response_rooted.error}")
            hints.append(response_rooted.hint or "provider")

        # Preserve the dominant failure hint when every candidate failed the same way.
        final_hint = "provider"
        if hints and all(h == hints[0] for h in hints):
            final_hint = hints[0]

        return Rooted(
            value=None,
            assumption=f"At least one provider executes step {index} successfully.",
            confidence=0.0,
            provenance=[f"executor.step:{index}"],
            error="; ".join(errors) if errors else "All providers failed.",
            hint=final_hint,
        )

    def execute(
        self,
        intent: str,
        plan: Plan,
        context: str = "",
        approval_callback: Callable[[Step], bool] | None = None,
        stream: bool = False,
        stream_callback: Callable[[str], None] | None = None,
    ) -> Rooted[ExecutionReport]:
        """Execute each step and collect Rooted results.

        If *approval_callback* is provided, it is called before each step. A
        False return stops execution and surfaces a clear Rooted error.

        If *stream* is True and the selected adapter advertises the ``streaming``
        capability, the step is executed via ``complete_stream`` and the chunks
        are accumulated.  *stream_callback* is invoked for each content delta so
        callers can print progress in real time.
        """
        step_results: list[StepResult] = []
        hook_results: list[dict[str, str | int]] = []
        novelty_scores: list[dict[str, Any]] = []
        assumptions = [plan.assumption]

        refusals: list[Refusal] = []
        for index, step in enumerate(plan.steps, start=1):
            if approval_callback is not None and not approval_callback(step):
                return Rooted(
                    value=None,
                    assumption=f"Step {index} is approved before execution.",
                    confidence=0.0,
                    provenance=[f"executor.step:{index}"],
                    error=f"Approval denied for step {index}: {step.action}",
                    hint="approval",
                )

            # Threat-model tier check: every workspace-mutating action passes
            # through the same authorization chokepoint, including MCP tool calls.
            if self.project_dir is not None:
                step_dict: dict[str, Any] = {
                    "action": step.action,
                    "expected_artifact": step.expected_artifact,
                }
                if step.tool_call is not None:
                    step_dict["tool_call"] = step.tool_call
                auth = authorize_action(step_dict, self.project_dir)
                refusals.extend(auth.refusals)
                if not auth.allowed:
                    details = "; ".join(r.reason for r in auth.refusals)
                    return Rooted(
                        value=None,
                        assumption=f"Step {index} passes the threat-model authorization check.",
                        confidence=0.0,
                        provenance=[f"executor.step:{index}"],
                        error=f"Step {index} refused by threat model: {details}",
                        hint="security",
                    )

            if self.hook_manager is not None:
                pre_results = self.hook_manager.run_hooks(
                    "pre",
                    {
                        "intent": intent,
                        "step_index": str(index),
                        "step_action": step.action,
                        "expected_artifact": step.expected_artifact,
                    },
                )
                hook_results.extend(pre_results)

            raw: Any
            content: str
            metrics: dict[str, Any] = {}
            if step.tool_call is not None:
                if self.mcp_registry is None or not self.mcp_registry.has_servers():
                    return Rooted(
                        value=None,
                        assumption="An MCP registry is configured for tool_call steps.",
                        confidence=0.0,
                        provenance=[f"executor.step:{index}"],
                        error="Tool-call step requires a configured MCP server, but none is available.",
                        hint="mcp",
                    )
                tool_name = step.tool_call.get("name")
                tool_args = step.tool_call.get("arguments", {})
                if not tool_name:
                    return Rooted(
                        value=None,
                        assumption="Tool-call step specifies a tool name.",
                        confidence=0.0,
                        provenance=[f"executor.step:{index}"],
                        error="Tool-call step is missing 'name'.",
                        hint="mcp",
                    )
                tool_result = self.mcp_registry.call_tool(tool_name, tool_args)
                if not tool_result.is_ok():
                    return Rooted(
                        value=None,
                        assumption=f"MCP tool '{tool_name}' executes successfully.",
                        confidence=0.0,
                        provenance=[f"executor.step:{index}"],
                        error=tool_result.error,
                        hint="mcp",
                    )
                result_value = tool_result.unwrap()
                raw = {
                    "tool": result_value.tool,
                    "content": result_value.content,
                    "is_error": result_value.is_error,
                }
                content = json.dumps(result_value.content, indent=2)
            else:
                step_result = self._execute_provider_step_with_fallback(
                    step, context, index, stream, stream_callback
                )
                if not step_result.is_ok():
                    return Rooted(
                        value=None,
                        assumption=step_result.assumption,
                        confidence=step_result.confidence,
                        provenance=[*step_result.provenance, f"executor.step:{index}"],
                        error=step_result.error,
                        hint=step_result.hint,
                    )
                raw, content, metrics = step_result.unwrap()

            content = self._normalize_model_output(content, step.expected_artifact)

            is_diff, content, diff_message = self._apply_diff_if_needed(
                step.expected_artifact, content
            )
            if is_diff and diff_message and not diff_message.startswith("Diff applied"):
                # Diff was detected but could not be applied; treat as error so the
                # loop does not silently write a malformed patch to disk.
                return Rooted(
                    value=None,
                    assumption=f"Step {index} diff applies cleanly to {step.expected_artifact}.",
                    confidence=0.0,
                    provenance=[f"executor.step:{index}"],
                    error=diff_message,
                    hint="diff",
                )

            # Safety guardrails: block forbidden patterns before the artifact is
            # recorded or returned. The harness can decide whether to escalate.
            violations = self.guardrail.check(step.expected_artifact, content)
            if violations:
                summary = "; ".join(
                    f"{v['rule']} at line {v['line']}: {v['message']}"
                    for v in violations[:3]
                )
                return Rooted(
                    value=None,
                    assumption=f"Step {index} output passes safety guardrails.",
                    confidence=0.0,
                    provenance=[f"executor.step:{index}"],
                    error=f"Safety guardrail violation(s): {summary}",
                    hint="safety",
                )

            # Anti-rot: duplication guard blocks writes that reproduce existing
            # symbols above the similarity threshold. The planner must justify
            # deliberate duplication rather than accidental copy-paste.
            if self.duplication_guard is not None and step.expected_artifact:
                dupes = self.duplication_guard.check(step.expected_artifact, content)
                if dupes:
                    summary = "; ".join(
                        f"{d.name} ({d.module}) similarity={d.similarity:.3f}"
                        for d in dupes[:3]
                    )
                    return Rooted(
                        value=None,
                        assumption=(
                            f"Step {index} artifact does not duplicate "
                            "existing symbols."
                        ),
                        confidence=0.0,
                        provenance=[f"executor.step:{index}"],
                        error=f"Duplication guard blocked write: {summary}",
                        hint="duplication",
                    )

            # Anti-rot: load-bearing weirdness annotations protect legacy code
            # that looks wrong but is correct. Modifying them without override is
            # treated as a regression.
            if step.expected_artifact:
                lb_messages = self._check_load_bearing(step.expected_artifact, content)
                if lb_messages:
                    summary = "; ".join(lb_messages[:3])
                    override_hint = (
                        " Pass --allow-load-bearing to override."
                        if not self.allow_load_bearing_override
                        else ""
                    )
                    return Rooted(
                        value=None,
                        assumption=(
                            f"Step {index} does not modify load-bearing code in "
                            f"{step.expected_artifact}."
                        ),
                        confidence=0.0,
                        provenance=[f"executor.step:{index}"],
                        error=f"Load-bearing guard blocked write: {summary}{override_hint}",
                        hint="load-bearing",
                    )

            # Anti-rot: novelty budget makes new files, symbols, and dependencies
            # costly so the agent prefers extending existing code over inventing.
            if (
                self.novelty_budget is not None
                and step.expected_artifact
                and not self.allow_novelty_overrun
            ):
                charges = self.novelty_budget.assess(step.expected_artifact, content)
                if charges and self.novelty_budget.would_exceed(charges):
                    summary = "; ".join(
                        f"{c.category} ({c.points}pts)" for c in charges[:3]
                    )
                    return Rooted(
                        value=None,
                        assumption=(
                            f"Step {index} stays within the novelty budget "
                            f"({self.novelty_budget.remaining} remaining)."
                        ),
                        confidence=0.0,
                        provenance=[f"executor.step:{index}"],
                        error=(
                            f"Novelty budget exhausted: {summary}. "
                            "Increase budget in ract.yaml or pass --allow-novelty-overrun."
                        ),
                        hint="novelty-budget",
                    )

            # Quirk: compression-based novelty detection. Low-ratio content may
            # duplicate existing code; high-ratio content is either genuinely new
            # or genuinely wrong and deserves stronger review.
            # LR:: Run this BEFORE writing so the gate can reject near-duplicates.
            # Route low-novelty rejections into the operator handshake queue so
            # the loop continues instead of halting.
            if self.compression_novelty_detector is not None and step.expected_artifact:
                score = self.compression_novelty_detector.assess_new_artifact(
                    step.expected_artifact, content
                )
                if score is not None:
                    score_payload = {
                        "artifact": score.artifact,
                        "raw_bytes": score.raw_bytes,
                        "compressed_bytes": score.compressed_bytes,
                        "dict_compressed_bytes": score.dict_compressed_bytes,
                        "ratio": score.ratio,
                        "verdict": score.verdict,
                        "detail": score.detail,
                        "nearest": score.nearest,
                    }
                    novelty_scores.append(score_payload)
                    if score.verdict == "low" and not self.allow_novelty_overrun:
                        nearest_hint = (
                            f" Extend {score.nearest} instead."
                            if score.nearest
                            else " Edit the most similar existing module instead."
                        )
                        description = (
                            f"Step {index} proposed {step.expected_artifact} with "
                            f"compression ratio {score.ratio}: {score.detail}."
                            f"{nearest_hint}"
                        )
                        acceptance = (
                            "Approve to allow this near-duplicate artifact, or "
                            "reject and require the planner to extend existing "
                            "code instead."
                        )
                        if self.handshake_registry is not None:
                            self.handshake_registry.add(
                                f"novelty:{step.expected_artifact}:{index}",
                                description,
                                acceptance,
                            )
                            assumptions.append(
                                f"Step {index} ({step.action}) queued a novelty "
                                f"handshake for {step.expected_artifact} "
                                f"(ratio {score.ratio})"
                            )
                            continue
                        return Rooted(
                            value=None,
                            assumption=(
                                f"Step {index} artifact is not structurally novel "
                                f"relative to the existing codebase; it is a near-"
                                f"duplicate of existing code."
                            ),
                            confidence=0.0,
                            provenance=[f"executor.step:{index}"],
                            error=(
                                f"Compression novelty gate blocked low-novelty write "
                                f"to {step.expected_artifact} "
                                f"(ratio={score.ratio:.3f}).{nearest_hint} "
                                "Pass --allow-novelty-overrun to override."
                            ),
                            hint="novelty",
                        )

            self._write_artifact(step.expected_artifact, content)

            # Charge the novelty budget only after a successful write so partial
            # failures do not consume points.
            if self.novelty_budget is not None and step.expected_artifact:
                charges = self.novelty_budget.assess(step.expected_artifact, content)
                if charges:
                    self.novelty_budget.spend(charges)

            step_results.append(
                StepResult(
                    step=step, raw_response=raw, content=content, metrics=metrics
                )
            )
            assumptions.append(
                f"Step {index} ({step.action}) produced artifact: {step.expected_artifact}"
            )

            # Record the artifact in provenance so callers can audit what was
            # produced without re-hashing the raw response themselves.
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            size_bytes = len(content.encode("utf-8"))
            prov_artifact = ProvenanceArtifact(
                name=step.expected_artifact,
                path=step.expected_artifact,
                size_bytes=size_bytes,
                checksum=checksum,
            )
            self.provenance.register(prov_artifact, datetime.now().isoformat())

            # Also store and track the artifact for diff/lookup/replay use cases.
            store_artifact = StoreArtifact(
                name=step.expected_artifact,
                path=step.expected_artifact,
                size_bytes=size_bytes,
                checksum=checksum,
            )
            self.artifact_store.add(store_artifact)
            self.artifact_tracker.register(
                TrackedArtifact(
                    identifier=step.expected_artifact,
                    checksum=checksum,
                    path=step.expected_artifact,
                )
            )

            if self.hook_manager is not None:
                post_results = self.hook_manager.run_hooks(
                    "post",
                    {
                        "intent": intent,
                        "step_index": str(index),
                        "step_action": step.action,
                        "expected_artifact": step.expected_artifact,
                        "content_checksum": checksum,
                    },
                )
                hook_results.extend(post_results)

        aggregated_metrics = self._aggregate_step_metrics(step_results)

        return Rooted(
            value=ExecutionReport(
                intent=intent,
                step_results=step_results,
                assumptions=assumptions,
                provenance=self.provenance.snapshot(),
                plan=plan,
                metrics=aggregated_metrics,
                refusals=refusals,
                artifacts=(
                    {
                        "hook_results": hook_results,
                        "store": [
                            {"name": a.name, "checksum": a.checksum}
                            for a in map(
                                self.artifact_store.get,
                                self.artifact_store.list_names(),
                            )
                            if a is not None
                        ],
                        "tracker": sorted(self.artifact_tracker.list_identifiers()),
                        "novelty_scores": novelty_scores,
                    }
                    if self.hook_manager is not None
                    else {
                        "store": [
                            {"name": a.name, "checksum": a.checksum}
                            for a in map(
                                self.artifact_store.get,
                                self.artifact_store.list_names(),
                            )
                            if a is not None
                        ],
                        "tracker": sorted(self.artifact_tracker.list_identifiers()),
                        "novelty_scores": novelty_scores,
                    }
                ),
            ),
            assumption="All plan steps executed successfully.",
            confidence=plan.confidence,
            provenance=["executor.execute"],
        )


# RACT 0.1.1 - Trust and tooling
