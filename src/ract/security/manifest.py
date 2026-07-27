"""Capability manifest — declarative allowlist consumed by the sandbox.

SUBSTRATE spec §4.3. The manifest is authored as YAML for operator
readability (lateral chain branch B), but the canonical serialization
used for the digest is JSON with sorted keys — the digest is what
module_06 stamps into its extended ``Rootknot`` as ``manifest_digest``,
and downstream comparability requires a single canonical form.

Public documentation used for the schema shape:

- Pydantic v2 (``https://docs.pydantic.dev/``) for the model layer;
- Landlock (``https://landlock.io/`` and the kernel userspace-api docs)
  for the filesystem allowlist idiom;
- seccomp-bpf
  (``https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html``)
  for the syscall-profile idiom;
- Apple's ``sandbox-exec`` / Seatbelt public documentation for the
  filesystem + network + process primitives that survive on macOS.

The manifest is a strict allowlist. Any field the manifest does not
mention is denied by construction (SUBSTRATE §4.2 Ona-incident lesson:
``/proc/self/root/usr/bin/npx`` slipped past a denylist because the
denylist enumerated origins, not resolved paths — an allowlist inverts
the burden of proof and refuses the resolved path unless it is named).

**Tier-3 compile-time hard-off.** ``TierPolicy.allow_tier_3`` defaults
``False``. Even when set to ``True``, ``ManifestValidator.validate``
refuses unless the module-level ``RACT_TIER_3_ENABLED`` constant is
true. That constant ships ``False`` and is only flipped by an ADR — the
manifest cannot lift its own tier-3 ban without a governance event. See
ADR-0012 for the design rationale.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ract.core.types import Digest


# ---------------------------------------------------------------------------
# Compile-time hard-off for tier 3
# ---------------------------------------------------------------------------


# Governance gate: shipped ``False``. Flipping this to ``True`` requires
# an ADR (see ADR-0012 "Rejected alternatives" — the alternative of
# leaving tier-3 as a purely runtime flag was rejected because the v0.3
# threat-model already carried that shape and SUBSTRATE §4.1 named
# incidents happened anyway).
RACT_TIER_3_ENABLED: bool = False


# ---------------------------------------------------------------------------
# Path pattern
# ---------------------------------------------------------------------------


# A ``PathPattern`` is a glob-shaped absolute path. Kept as a string so
# the manifest is trivial to author in YAML; the sandbox is responsible
# for translating patterns into Landlock rules (Linux) or Seatbelt
# ``file-read*`` / ``file-write*`` clauses (macOS).
PathPattern = str


# ---------------------------------------------------------------------------
# Sub-policies (Pydantic v2)
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    """Base model: extra fields are refused so a stray key never grants."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FilesystemPolicy(_StrictModel):
    """Filesystem allowlist for the sandbox.

    ``read`` and ``write`` are the only paths a step may read or write.
    ``denied`` is a defence-in-depth belt over the allowlist: even if a
    later widen would grant one of these paths, the sandbox refuses. In
    practice ``denied`` is used to make specific paths that would
    otherwise be readable (say, ``~/.aws/**``) explicitly refused with a
    named reason.
    """

    read: tuple[PathPattern, ...] = ()
    write: tuple[PathPattern, ...] = ()
    denied: tuple[PathPattern, ...] = ()


class NetworkPolicy(_StrictModel):
    """Network egress allowlist.

    ``deny_default`` MUST be ``True``. The sandbox refuses to instantiate
    a network policy with ``deny_default=False`` — the whole point of the
    substrate is that egress is allowlisted, not denylisted.
    """

    allow_hosts: tuple[str, ...] = ()
    deny_default: bool = True

    @field_validator("deny_default")
    @classmethod
    def _must_be_deny_default(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "NetworkPolicy.deny_default must be True; the manifest is "
                "an allowlist by design (SUBSTRATE §4.2)."
            )
        return value


class SyscallPolicy(_StrictModel):
    """seccomp-bpf profile selector.

    ``strict`` is the default and refuses ``ptrace``, ``mount``,
    ``unshare``, ``module_load``, and every other kernel-config-adjacent
    syscall not on the shipped allowlist. ``moderate`` opens a few more
    (e.g. ``prctl(PR_SET_NAME)``) for legitimate tools that break under
    ``strict``. See the seccomp-bpf kernel docs for the syscall set.
    """

    seccomp_profile: Literal["strict", "moderate"] = "strict"


class ProcessPolicy(_StrictModel):
    """Process-count and wall-time bounds."""

    max_procs: int = Field(default=64, ge=1)
    max_wall_seconds: int = Field(default=60, ge=1)


class EnvPolicy(_StrictModel):
    """Environment-variable passthrough and scrubbing rules."""

    passthrough: tuple[str, ...] = ()
    # ``scrub`` is a list of glob patterns; the sandbox removes every
    # matching env var before entering the step, even if the operator's
    # login shell had it set.
    scrub: tuple[str, ...] = ()


class TierPolicy(_StrictModel):
    """Which capability tier the manifest may reach.

    ``default`` is the *maximum* tier for un-handshake-widened steps.
    ``allow_tier_3`` is the compile-time hard-off flag documented at the
    module top. See SUBSTRATE §4.3 + module_03 step 4.
    """

    default: int = Field(default=1, ge=0, le=3)
    allow_tier_3: bool = False


class YoloWiden(_StrictModel):
    """Pre-declared bounds for ``--yolo`` auto-widen.

    SUBSTRATE §4.3 narrowed: ``--yolo`` does NOT disable the sandbox and
    does NOT reach tier 3. It reads these bounds and widens the manifest
    within them for a single step. Every widen is logged.

    ``extra_read`` / ``extra_write`` extend the filesystem allowlist;
    ``extra_hosts`` extends the network allowlist. Tier 3 stays denied.
    """

    extra_read: tuple[PathPattern, ...] = ()
    extra_write: tuple[PathPattern, ...] = ()
    extra_hosts: tuple[str, ...] = ()


class ApprovalPolicy(_StrictModel):
    """Actions that require an operator handshake before execution."""

    handshake_required_for: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# ALM Gate G5 — TestIntegrityConfig section
# ---------------------------------------------------------------------------


# Defaults from ALM spec §3.5 — the denied patterns that ship with
# every manifest. Widening ``denied_ast_patterns`` (adding more) is
# always fine; NARROWING requires an operator handshake because the
# section is what keeps the reward channel non-writable from inside
# the sandbox. Compare TierPolicy.allow_tier_3 — the same principle
# applies: a manifest cannot silently disable its own anti-lazy floor.
DEFAULT_DENIED_AST_PATTERNS: tuple[str, ...] = (
    "pytest.skip",
    "pytest.xfail",
    "pytest.mark.skip",
    "pytest.mark.skipif",
    "pytest.mark.xfail",
)
DEFAULT_DENIED_ASSERTION_TRANSFORMS: tuple[str, ...] = (
    "assertion_removal",
    "assert_true_to_pass",
)
DEFAULT_DENIED_FILE_EDITS: tuple[str, ...] = (
    "tests/conftest.py",
    "tests/**/conftest.py",
    "tests/grader.py",
    "tests/**/grader.py",
    "tests/*grader*.py",
    "tests/**/*grader*.py",
    "evals/grader.py",
    "evals/**/grader.py",
    "evals/*grader*.py",
    "evals/**/*grader*.py",
)
DEFAULT_MONKEY_PATCH_WATCHLIST: tuple[str, ...] = (
    "sys.modules['grader']",
    "sys.modules['pytest']",
    "builtins.__import__",
    "sys.settrace",
    "sys.setprofile",
)
DEFAULT_ALLOWED_SKIP_REASON_SUBSTRINGS: tuple[str, ...] = (
    "only on windows",
    "only on linux",
    "only on macos",
    "requires windows",
    "requires linux",
    "requires macos",
    "requires posix",
    "not supported on windows",
    "not supported on linux",
    "not supported on macos",
    "platform-specific",
)


class TestIntegrityConfig(_StrictModel):
    """G5 policy — the denied AST patterns the pre-commit gate refuses.

    ALM spec §3.5. The pre-commit gate walks the diff between parent
    and child snapshots; any hit against ``denied_ast_patterns``,
    ``denied_assertion_transforms``, or ``denied_file_edits`` rolls
    back the merge and emits ``laziness.violated`` with
    ``kind="test_hack_denied"``. ``allow_with_operator_handshake``
    controls whether the trace-recorded handshake event lets an
    otherwise-denied diff through.

    Defaults populate the ALM spec's baseline; adding more denied
    patterns is safe; narrowing requires ManifestValidator flags.
    """

    denied_ast_patterns: tuple[str, ...] = DEFAULT_DENIED_AST_PATTERNS
    denied_assertion_transforms: tuple[str, ...] = DEFAULT_DENIED_ASSERTION_TRANSFORMS
    denied_file_edits: tuple[str, ...] = DEFAULT_DENIED_FILE_EDITS
    monkey_patch_watchlist: tuple[str, ...] = DEFAULT_MONKEY_PATCH_WATCHLIST
    allowed_skip_reason_substrings: tuple[str, ...] = (
        DEFAULT_ALLOWED_SKIP_REASON_SUBSTRINGS
    )
    allow_with_operator_handshake: bool = True


def default_test_integrity_config() -> TestIntegrityConfig:
    """Return the shipped-defaults ``TestIntegrityConfig``.

    Callers that want to analyze a diff without threading a full
    ``CapabilityManifest`` (tests, fixtures, offline auditors) use this
    helper to get the canonical policy.
    """
    return TestIntegrityConfig()


# ---------------------------------------------------------------------------
# CapabilityManifest
# ---------------------------------------------------------------------------


class CapabilityManifest(_StrictModel):
    """Run-scoped capability manifest.

    Fields match SUBSTRATE §4.3. ``version`` is pinned to ``1``; any
    future incompatible change bumps this and requires a migration path.
    """

    version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    filesystem: FilesystemPolicy = Field(default_factory=FilesystemPolicy)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    syscalls: SyscallPolicy = Field(default_factory=SyscallPolicy)
    processes: ProcessPolicy = Field(default_factory=ProcessPolicy)
    env: EnvPolicy = Field(default_factory=EnvPolicy)
    tiers: TierPolicy = Field(default_factory=TierPolicy)
    yolo_widen: YoloWiden = Field(default_factory=YoloWiden)
    approvals: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    # ALM module_03: G5's denied-AST-pattern list. Every manifest
    # carries a populated section by default; an author-narrowed
    # section triggers ManifestValidator (see ADR-0021).
    test_integrity: TestIntegrityConfig = Field(default_factory=TestIntegrityConfig)
    # Lateral chain branch C: the manifest names the sandbox key id (a
    # SHA256 hex of the pubkey the sandbox will use to attest); module_06
    # generates and stores the key, and this field is how the manifest
    # binds to that key.
    sandbox_key_id: str = ""


# ---------------------------------------------------------------------------
# ManifestValidator + ManifestViolation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManifestViolation:
    """One reason a manifest is invalid, structured for the event log."""

    code: str
    message: str
    field: str = ""


@dataclass(frozen=True)
class RunContext:
    """Small carrier for validator inputs the manifest itself cannot know.

    Kept minimal on purpose — the validator is a pure function so the
    tests can drive it without a live filesystem or a live sandbox.
    """

    workspace_root: str = ""


class ManifestValidator:
    """Refuse manifests that would silently grant more than they claim."""

    @staticmethod
    def validate(
        manifest: CapabilityManifest, run_context: RunContext | None = None
    ) -> list[ManifestViolation]:
        """Return the list of violations for ``manifest``.

        The manifest schema is already enforced by Pydantic; this pass
        checks cross-field invariants and the compile-time tier-3 gate.
        """
        violations: list[ManifestViolation] = []

        # Version gate.
        if manifest.version != 1:
            violations.append(
                ManifestViolation(
                    code="unknown_manifest_version",
                    message=(
                        f"manifest version {manifest.version} is not supported; "
                        "current substrate is version 1"
                    ),
                    field="version",
                )
            )

        # Tier-3 compile-time hard-off.
        if manifest.tiers.allow_tier_3 and not RACT_TIER_3_ENABLED:
            violations.append(
                ManifestViolation(
                    code="tier_3_compile_time_denied",
                    message=(
                        "manifest sets allow_tier_3=True but the compile-time "
                        "constant RACT_TIER_3_ENABLED is False. Submit an ADR "
                        "flipping the constant before enabling tier 3 in the "
                        "manifest (see ADR-0012)."
                    ),
                    field="tiers.allow_tier_3",
                )
            )

        # Tier default sanity.
        if manifest.tiers.default > 2:
            violations.append(
                ManifestViolation(
                    code="tier_default_out_of_range",
                    message=(
                        "manifest tiers.default may not exceed 2; tier 3 is a "
                        "per-action escalation, never a default"
                    ),
                    field="tiers.default",
                )
            )

        # Network sanity — the sub-policy validator already refuses
        # deny_default=False, but a manifest that both denies by default
        # AND lists no allow_hosts AND has yolo_widen add hosts is a
        # useful shape and not a violation. We only surface a warning-
        # shaped violation when the deny-default is False despite the
        # sub-policy check (guarding against a future extra="allow"
        # regression on the model config).
        if not manifest.network.deny_default:
            violations.append(
                ManifestViolation(
                    code="network_must_deny_default",
                    message=(
                        "network.deny_default must be True; the manifest is "
                        "an allowlist"
                    ),
                    field="network.deny_default",
                )
            )

        # Filesystem allowlist sanity — a manifest that lists a path in
        # both ``write`` and ``denied`` is a mis-authored allowlist.
        write_set = set(manifest.filesystem.write)
        denied_set = set(manifest.filesystem.denied)
        overlap = write_set & denied_set
        if overlap:
            violations.append(
                ManifestViolation(
                    code="filesystem_write_denied_overlap",
                    message=(
                        f"paths appear in both filesystem.write and "
                        f"filesystem.denied: {sorted(overlap)!r}"
                    ),
                    field="filesystem",
                )
            )

        # ALM module_03: test-integrity section must be present and the
        # denied-AST-pattern list must be non-empty. A manifest that
        # ships ``TestIntegrityConfig(denied_ast_patterns=())`` reads
        # as an operator-initiated narrowing and requires a signed
        # handshake to land; the validator refuses the shape at load
        # time so ``--yolo`` cannot silently widen it (ADR-0021).
        if not manifest.test_integrity.denied_ast_patterns:
            violations.append(
                ManifestViolation(
                    code="test_integrity_section_narrowed",
                    message=(
                        "test_integrity.denied_ast_patterns is empty; the ALM "
                        "spec §3.5 baseline requires at least the canonical "
                        "pytest.skip / pytest.xfail / pytest.mark.skip family "
                        "of denied patterns. Narrowing requires a signed "
                        "operator handshake (see ADR-0021)."
                    ),
                    field="test_integrity.denied_ast_patterns",
                )
            )
        if not manifest.test_integrity.denied_file_edits:
            violations.append(
                ManifestViolation(
                    code="test_integrity_denied_files_missing",
                    message=(
                        "test_integrity.denied_file_edits is empty; the grader "
                        "and conftest globs must ship as a baseline (ADR-0021)."
                    ),
                    field="test_integrity.denied_file_edits",
                )
            )

        # yolo_widen sanity — no widen path may re-enable a denied one.
        for path in manifest.yolo_widen.extra_write:
            if path in denied_set:
                violations.append(
                    ManifestViolation(
                        code="yolo_widen_conflicts_with_denied",
                        message=(
                            f"yolo_widen.extra_write path {path!r} is also in "
                            "filesystem.denied; the denied list wins by design"
                        ),
                        field="yolo_widen.extra_write",
                    )
                )

        return violations


# ---------------------------------------------------------------------------
# ManifestDigest
# ---------------------------------------------------------------------------


class ManifestDigest:
    """SHA256 over the manifest's canonical JSON serialization.

    Canonical form: JSON, sorted keys, no whitespace, UTF-8. This is what
    module_06 stores as ``manifest_digest`` in the extended Rootknot
    schema; downstream comparability requires a single canonical form
    across YAML authors and JSON consumers (lateral chain branch B).
    """

    @staticmethod
    def canonical_bytes(manifest: CapabilityManifest) -> bytes:
        payload: dict[str, Any] = manifest.model_dump(mode="json")
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    @staticmethod
    def of(manifest: CapabilityManifest) -> Digest:
        return Digest(hashlib.sha256(ManifestDigest.canonical_bytes(manifest)).digest())


# ---------------------------------------------------------------------------
# YAML author helper (public dep: pyyaml, already in project dependencies)
# ---------------------------------------------------------------------------


def load_manifest_from_yaml(text: str) -> CapabilityManifest:
    """Author-time helper: parse a YAML manifest into a validated model.

    The canonical serialization is JSON (see ``ManifestDigest``) but the
    author-facing format is YAML for readability. This helper keeps the
    two ends of the pipe wired together.
    """
    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("manifest YAML root must be a mapping")
    return CapabilityManifest.model_validate(data)


# RACT 0.4.0
