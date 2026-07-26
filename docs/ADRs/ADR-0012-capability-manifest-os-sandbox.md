# ADR-0012: Capability Manifest as Allowlist Enforced at the OS Layer

## Status

Accepted

## Context

Through v0.3, ``src/ract/core/threat_model.py`` classified plan actions
into four tiers and refused tier 3 by default. Enforcement lived at the
same layer as the action — a Python-level string check on the plan step.
The SUBSTRATE §4 audit named three incidents that made this shape
untenable:

- Claude Code home-directory ``rm -rf ~/``,
- Cursor 70-file deletion,
- Replit production-database deletion.

All three had a common shape: the destructive action's plan step
classified as tier 3 (or a mislabeled tier 2), the harness-layer refusal
either did not fire or was bypassed by a plausible synonym, and the
operating system had no independent guardrail — the harness was the
only fence, and the harness was already inside the pen.

SUBSTRATE §4.2 further named the April 2026 Bubblewrap escape at Ona:
``/proc/self/root/usr/bin/npx`` reached a denied binary because the
denylist enumerated origins ("do not run npx") but the resolved path
was allowed by construction. An allowlist inverts the burden.

## Decision

Every RACT run declares a ``CapabilityManifest``
(``src/ract/security/manifest.py``). The manifest is a strict allowlist:
any filesystem path, network host, syscall, or environment variable the
manifest does not name is refused by construction. Enforcement layers
below the harness:

- **Linux:** ``LinuxSandbox`` (``src/ract/security/sandbox_linux.py``)
  stacks Bubblewrap (namespace isolation), Landlock (kernel filesystem
  allowlist), and seccomp-bpf (syscall filter). References:
  ``https://github.com/containers/bubblewrap``,
  ``https://landlock.io/``,
  ``https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html``.
- **macOS:** ``MacosSandbox`` (``src/ract/security/sandbox_macos.py``)
  renders a Seatbelt ``.sb`` profile and executes the step under
  ``sandbox-exec``. Reference: Apple's public sandboxing documentation.
- **Windows:** No equivalent primitive ships in this module (lateral
  chain branch A). ``resolve_backend`` raises ``SandboxNotAvailable``
  unless the operator sets ``--allow-unenforced-sandbox``; the flag is
  loud in the event log and stamped into the run report.

Every ``StepTransaction.open`` receives the run's manifest and derives
its per-step sandbox from it. The sandbox emits ``sandbox.granted`` /
``sandbox.denied`` events (schema lands in module_05; the call site
exists today via ``ract.security.sandbox.emit``).

The manifest's canonical serialization is JSON with sorted keys
(``ManifestDigest``), even though the author-facing format is YAML
(lateral chain branch B). Module_06 stamps the digest into the extended
Rootknot as ``manifest_digest``.

### ``--yolo`` narrowed

Under SUBSTRATE §4.3, ``--yolo`` disabled interactive prompts. Module_03
narrows this further: ``--yolo`` never disables the enforcement layer,
never lifts tier 3, and never widens outside the manifest's
pre-declared ``yolo_widen`` bounds. An approved handshake goes through
``HandshakeRegistry.widen_manifest_for``, which unions the manifest's
allowlist with ``yolo_widen.extra_read`` / ``extra_write`` /
``extra_hosts`` and returns a new manifest for the next
``StepTransaction.open`` call.

### Tier 3 compile-time hard-off

The manifest's ``TierPolicy.allow_tier_3`` field defaults ``False``.
Even when set to ``True``, ``ManifestValidator.validate`` refuses
unless the module-level constant ``RACT_TIER_3_ENABLED`` is ``True``.
The constant ships ``False``. An operator who later needs tier 3 must
submit an ADR that flips the constant; the manifest cannot lift its
own tier-3 ban.

This is stricter than SUBSTRATE §4.3, which only spec'd the runtime
flag. The rationale is that the v0.3 tier-3 gate already existed and
the SUBSTRATE §4.1 incidents happened anyway — a purely runtime flag
does not carry enough friction to prevent the same class of accident.

## Rejected alternatives

- **Denylist-based sandboxing.** The Ona escape (SUBSTRATE §4.2)
  demonstrated that denylists enumerate origins, not resolved paths;
  ``/proc/self/root/usr/bin/npx`` slipped past the denylist because it
  was not on the list. Rejected — an allowlist inverts the burden of
  proof so the sandbox refuses unless the literal resolved path is
  named.
- **Harness-layer refusals only (v0.3 baseline).** SUBSTRATE §4.1
  incidents all happened under harnesses that had refuse-list checks.
  A guardrail at the same layer as the proposal cannot stop a plausible
  proposal that reads as compliant. Rejected — enforcement moves to the
  OS.
- **Container-only isolation without a filesystem allowlist inside.**
  A container with a permissive root filesystem still writes wherever
  the mount points say. SUBSTRATE §4.3 and module_02 (ADR-0011) already
  land the container-per-step surface; module_03 adds the Landlock /
  Seatbelt allowlist *inside* the container so a mount misconfiguration
  cannot re-open the whole tree. Rejected as sole enforcement.
- **Runtime-only tier-3 flag (SUBSTRATE §4.3 spec).** Rejected in favor
  of the compile-time hard-off documented above.

## Consequences

Positive:

- Every step's sandbox is a fact about the environment, not an opinion
  about the plan. The kernel refuses the write; the harness need only
  observe.
- The ``manifest_digest`` is a stable identifier the event log and the
  Rootknot both reference; module_06's extended Rootknot re-orientation
  becomes a schema addition, not a schema replacement.
- Tier 3 requires an ADR event to reach, which puts the required
  friction on the escalation path.

Negative / follow-ups:

- **Windows enforcement is the shipped honest gap.** No AppContainer,
  no Job Object isolation, no Windows Filtering Platform rules are
  wired here. Runs on Windows must set ``--allow-unenforced-sandbox``;
  the escape hatch is loud but real. A hardening module owes an
  AppContainer + Job Object backend.
- **``--allow-unenforced-sandbox`` is a real escape hatch.** The v0.4
  bar accepts this because the alternative (refusing Windows runs
  entirely) collapses the dev loop for the operator who is building the
  substrate. The hardening module that closes it must arrive before
  RACT ships to non-operator users on Windows.
- **Pydantic promotion.** The manifest schema uses Pydantic v2 models.
  See ADR-0013 for the runtime-dependency promotion this required.
- **Landlock version drift.** Older kernels expose a subset of the
  Landlock API. When the kernel lacks a Landlock-3 feature the manifest
  relies on, ``LinuxSandbox.enter`` falls back to bwrap-only namespace
  isolation (weaker but still allowlist-shaped) and emits a
  ``sandbox.unenforced`` event with the missing feature named. That
  fallback is loud on purpose.
- **SubstrateLoop is not the CLI default yet.** The sandbox fires
  automatically when a step runs under ``SubstrateLoop.run_step`` with
  a manifest attached. The CLI's default execution path is still the
  v0.3 provider-facing executor (see module_02 flagged gaps); until the
  loop migration lands in a later module, ``ract run`` still writes
  directly to the live tree without a manifest. The call site exists;
  the wiring waits.

## References

- ``docs/RACT_v0.4.0_SUBSTRATE_SPEC.md`` §4 (Substrate Layer 3:
  Capabilities as Physics) and §11 signals 4, 5, 6.
- Bubblewrap: ``https://github.com/containers/bubblewrap``
- Landlock: ``https://landlock.io/`` and
  ``https://www.kernel.org/doc/html/latest/userspace-api/landlock.html``
- seccomp-bpf:
  ``https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html``
- Apple sandboxing (Seatbelt / ``sandbox-exec``): Apple Developer
  documentation.
- Sandlock.mcp per-tool sandboxing pattern (SUBSTRATE §4.2).
- ADR-0004 (v0.3 tier-based threat model) as the pre-substrate baseline
  this ADR extends.
- ADR-0011 (worktree-per-step + container-per-step) — the substrate
  layer this module lives inside.
- ADR-0013 — Pydantic v2 runtime dependency promotion.

<!-- RACT 0.4.0 -->
