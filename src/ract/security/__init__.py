"""RACT security substrate.

SUBSTRATE spec §4 (Substrate Layer 3: Capabilities as Physics). The
public surface here is the capability manifest and the platform-specific
sandbox backends. Enforcement is at the OS layer — Bubblewrap plus
Landlock plus seccomp-bpf on Linux (see
``https://github.com/containers/bubblewrap``,
``https://www.kernel.org/doc/html/latest/userspace-api/landlock.html``,
``https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html``),
Seatbelt / ``sandbox-exec`` on macOS
(see Apple's public sandboxing documentation) — with the manifest as a
strict **allowlist**, not a denylist (SUBSTRATE §4.2 Ona incident).

The manifest sits above ``ract.core.threat_model``. Classification and
authorization (v0.3 baseline) still run; the sandbox is the OS-layer
belt-and-braces so a plausible destructive proposal cannot walk past a
guardrail that lives at the same level as the proposal.

Historical Sandlock.mcp per-tool sandboxing pattern (SUBSTRATE §4.2)
informs the "manifest per plan, sandbox per step" split: the manifest is
a run-scoped declaration; each ``StepTransaction`` derives its concrete
sandbox at ``open`` time.
"""

from ract.security.manifest import (
    ApprovalPolicy,
    CapabilityManifest,
    EnvPolicy,
    FilesystemPolicy,
    ManifestDigest,
    ManifestValidator,
    ManifestViolation,
    NetworkPolicy,
    PathPattern,
    ProcessPolicy,
    SyscallPolicy,
    TierPolicy,
    YoloWiden,
)
from ract.security.sandbox import (
    SandboxBackend,
    SandboxEvent,
    SandboxNotAvailable,
    SandboxViolation,
    resolve_backend,
)

__all__ = [
    "ApprovalPolicy",
    "CapabilityManifest",
    "EnvPolicy",
    "FilesystemPolicy",
    "ManifestDigest",
    "ManifestValidator",
    "ManifestViolation",
    "NetworkPolicy",
    "PathPattern",
    "ProcessPolicy",
    "SandboxBackend",
    "SandboxEvent",
    "SandboxNotAvailable",
    "SandboxViolation",
    "SyscallPolicy",
    "TierPolicy",
    "YoloWiden",
    "resolve_backend",
]

_SECURITY_EXPORTS = (
    ApprovalPolicy,
    CapabilityManifest,
    EnvPolicy,
    FilesystemPolicy,
    ManifestDigest,
    ManifestValidator,
    ManifestViolation,
    NetworkPolicy,
    PathPattern,
    ProcessPolicy,
    SyscallPolicy,
    TierPolicy,
    YoloWiden,
    SandboxBackend,
    SandboxEvent,
    SandboxNotAvailable,
    SandboxViolation,
    resolve_backend,
)

# RACT 0.4.0
