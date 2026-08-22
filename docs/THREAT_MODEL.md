# RACT Threat Model

RACT enforces safety at the operating-system layer via a per-run
**capability manifest** and a per-step OS-enforced sandbox. This
document is the operator-facing overview; ADR-0012 carries the design
rationale.

## Manifest-first framing

Every RACT run declares a ``CapabilityManifest``
(``src/ract/security/manifest.py``). The manifest is a strict allowlist
for filesystem, network, syscalls, environment, and processes. Any
resource the manifest does not name is refused by construction.

The manifest is authored as YAML for readability but serialized to
canonical JSON for the digest that downstream modules join against.
v0.5.1 module_03 replaced the legacy ``json.dumps(sort_keys=True)``
serializer with RFC 8785 JCS via ``ract.canonical.dumps_jcs`` --
byte output is deterministic across Python minor versions, PyPy,
and Windows/POSIX line endings; NFC-normalised codepoint-sorted
keys with strict-JSON floats. Module_06's extended ``Rootknot``
stamps the digest as ``manifest_digest`` — the manifest is the
substrate the environment signature attests.

## Default manifest

The tier table below is the **default** manifest a run inherits when
its own manifest section is empty. A live manifest is a delta from
this default; ``ManifestValidator.validate`` refuses a delta that
would silently grant more than the default.

| Tier | Name            | Examples                                                                | Default policy         |
|------|-----------------|--------------------------------------------------------------------------|------------------------|
| T0   | Read-only        | file read, symbol search, ``git log``                                    | Allow                  |
| T1   | Workspace-write  | file write under the workspace root                                      | Allow with Rootknot    |
| T2   | Environment      | ``pip install``, ``npm install``, ``git commit``, allowlisted egress    | Require handshake      |
| T3   | External         | shell outside sandbox, package publish, ``rm -rf`` on untracked paths   | **Denied at compile time until ADR flips the flag** |

Classification is deterministic — it comes from the step's schema
fields (``action``, ``expected_artifact``, ``tool_call.name``), not
from parsing free text.

### Tier 3: denied at compile time

``TierPolicy.allow_tier_3`` defaults ``False``. Even when set to
``True``, the validator refuses unless the module-level constant
``RACT_TIER_3_ENABLED`` in ``ract.security.manifest`` is ``True``.
That constant ships ``False``. An operator who later needs tier 3 must
submit an ADR that flips the constant — the manifest cannot lift its
own tier-3 ban.

See ADR-0012 "Rejected alternatives" for why a purely runtime flag
was rejected in favor of the compile-time hard-off.

## Sandbox enforcement

- **Linux:** Bubblewrap (namespace isolation) + Landlock (filesystem
  allowlist) + seccomp-bpf (syscall filter). Public docs:
  <https://github.com/containers/bubblewrap>,
  <https://landlock.io/>,
  <https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html>.
- **macOS:** Seatbelt / ``sandbox-exec`` with a generated ``.sb``
  profile. Public docs: Apple's sandboxing documentation.
- **Windows:** No shipped OS-enforced sandbox in this module (see
  ADR-0012 "Negative / follow-ups"). ``resolve_backend`` refuses to
  start unless the operator sets ``--allow-unenforced-sandbox``. The
  flag is loud in the event log and stamped into the run report.

The sandbox derives its policy from the manifest: filesystem
allowlist, network allowlist, seccomp profile, env scrub. Runtime
refusals surface as process exit codes / SIGSYS, not as harness-level
exceptions — the enforcement is a fact about the environment.

## ``--yolo`` narrowed

``--yolo`` does **not** disable the sandbox, and does **not** reach
tier 3. It reads the manifest's ``yolo_widen`` section (pre-declared
bounds on filesystem writes, filesystem reads, and network hosts) and
unions those bounds into the manifest for a single step. The
enforcement layer still fires; every widen is logged as a
``sandbox.granted`` event with the widen details in ``details``.

## Approvals (handshakes)

``HandshakeRegistry.widen_manifest_for`` applies an approved
handshake's widen to the manifest. The widen is bounded by
``yolo_widen``; a handshake cannot grant a resource the manifest did
not pre-declare could be widened. An unresolved handshake blocks the
step's *commit* at the git layer (see ADR-0011 and module_02) —
handshakes are enforcement, not opinion.

## Refuse-list (default manifest instantiation)

The default manifest instantiation refuses:

1. Writing or modifying files outside the workspace root.
2. Executing ``rm -rf`` / ``rm -r`` / ``rmdir /s`` on paths not under
   version control.
3. Publishing to package registries (PyPI, npm, crates.io, etc.)
   without ``allow_tier_3=True`` **and** the compile-time constant
   flipped **and** an operator-signed handshake.
4. Committing directly to a protected branch.
5. Sending the full workspace to a remote provider in a single
   request above the configured chunk-size threshold (default 1 MiB).
6. Reading files matching the sensitive-pattern list: ``.env``,
   ``.env.*``, ``*.pem``, ``*.key``, ``id_rsa``, ``id_ed25519``,
   ``~/.ssh/**``, ``~/.aws/**``, ``~/.config/gcloud/**``.
7. Overwriting a file whose current Rootknot was signed by a different
   session key, unless the operator explicitly passes
   ``--force-overwrite <path>``.

## Named-incident regressions

The SUBSTRATE §4.1 named incidents are first-class regression tests in
``tests/security/test_named_incidents.py``:

- Claude Code home-directory ``rm -rf ~/``
- Cursor 70-file deletion
- Replit production-database deletion

The SUBSTRATE §4.2 April-2026 Ona ``/proc/self/root/`` Bubblewrap
escape is ``tests/security/test_proc_self_root_synonym_refused.py::test_ona_2026_04``.

## v0.5.1 substrate closures

Module_05 of the External Review Response pipeline
(``_BUILD/ract_v0.5.1_external_review_response/module_05.md``)
closed four SUBSTRATE §4-§7 gaps the executor-adapter shim carried
since v0.4. ADR-0041 names the decision rationale and the five
rejected alternatives; the surfaces are summarised here for the
operator-facing threat model.

### Environ allowlist (``src/ract/security/sandbox_env.py``)

Sandbox init is deny-by-default over the process env. The loader
computes a strict allowlist over
``manifest.env.passthrough ∪ .ract/sandbox_env.allowlist ∪
DEFAULT_ALLOWLIST`` (44 POSIX + Windows + locale names), minus a
hardcoded ``NEVER_PASSTHROUGH`` set (17 credential-shaped names
including ``AWS_*``, ``GITHUB_TOKEN``, ``OPENAI_API_KEY``,
``ANTHROPIC_API_KEY``, plus SP-Q3a NEVER_PASSTHROUGH_PREFIXES for
credential-shaped prefixes). Names not on the union are dropped;
only the COUNT lands in the ``sandbox.granted`` WARN payload
(never the value or the name of the scrubbed var).
``UnenforcedSandbox.enter`` calls the loader so even the Windows
stub emits the env audit -- a data-exfil path via inherited
``os.environ`` is closed on every backend.

### Tool-invocation gate (``src/ract/executor/tool_gate.py``)

Every tool call inside a substrate step passes through
``SubstrateLoop.invoke_tool`` (four-gate ``ToolInvocationGate``):

1. **manifest gate** -- the tool id must appear in the run's
   ``CapabilityManifest`` declared-tools set.
2. **registry gate** -- an implementation for the id must be
   registered before the loop enters step one; unregistered ids
   refuse.
3. **args gate** -- arguments must conform to the tool's frozen
   ``ToolArgSchema`` (typed, ``extra="forbid"``); mismatches
   refuse with structured details.
4. **budget gate** -- the per-step ``InvocationBudget`` cap
   refuses further calls once the ceiling is hit.

Refusals raise ``ToolInvocationRefused`` (structured; carries
``tool_id``, ``gate``, ``reason``, ``details``) and emit a
``tool.invocation.refused`` event. Pre + post events emit
``tool.invocation.pre`` and ``tool.invocation.post`` with bounded
``args_repr`` (privacy-safe truncation) and latency /
result-size metadata. Every tool call in a substrate step has a
single audit chokepoint; a new tool cannot ship without going
through the gate.

### Process-group tree-kill (``src/ract/executor/process_group.py``)

Step subprocess spawning uses ``process_group.spawn`` which sets
``start_new_session=True`` (POSIX ``setsid``) or Windows
``CREATE_NEW_PROCESS_GROUP`` + Job Object with kill-on-close.
Rollback calls ``kill_tree`` which reaps parent + every
descendant via ``killpg(pgid, SIGKILL)`` or
``TerminateJobObject`` (with ``taskkill /F /T`` fallback).
Idempotent; optional SIGTERM grace period. Closes
REVIEW_4_UNKNOWN §B3 -- grandchildren spawned inside a step no
longer outlive the transaction and no longer hold worktree file
handles open.

### Git commit compensator (``src/ract/executor/commit_compensator.py``)

After each successful commit that advanced the loop's HEAD, the
``SubstrateLoop`` installs a ``CommitCompensator`` (soft-reset
default) onto its ``CompensatorStack``. Loop disposal on any
T-cause other than T1 drains the stack LIFO; each compensator
``reset --soft <sha_before>``s its branch. Compensators refuse to
run against pushed commits (``check_pushed`` walks
``git branch -r --contains``); pushed compensators emit
``compensator.refused`` and leave the ref intact. The run report
can honestly claim "the tree is at the pre-loop state" for
non-T1 exits.

## Historical Manifest Ledger (module_07)

``src/ract/security/manifest_ledger.py`` (~1000 lines) is an
append-only Merkle-chained JSONL at
``.ract/manifest_ledger.jsonl`` + a content-addressable snapshot
store at ``.ract/manifest_snapshots/{digest_hex}.json`` (idempotent
CAS via tmp + ``os.replace``). Every RK-3 environment attestation
signed by ``Rootknot.attest_environment`` records an observation
onto the ledger via a local-import wire (breaking the
security -> core cycle -- the signed RK-3 payload itself is
unchanged).

Integrity properties:

- **Merkle chain** via ``prev_ledger_hash`` (GENESIS sentinel
  for the first entry). Any middle-excise attack (an attacker
  removes entry N to hide the observation) breaks the hash
  chain at N+1 and surfaces as ``LedgerVerifyResult.first_break_at
  = N+1`` under ``verify_chain``. Truncated tails surface as
  reduced ``tail_valid_count``; the SP Q4 middle-excise total-
  entry-count sidecar hardens the verify against the "middle
  excise + tail rewrite" variant.
- **Cross-platform file lock** mirrors ``assumptions_wal.py``
  (msvcrt.locking on Windows + fcntl.flock on POSIX,
  3-attempt / 10ms backoff, ``LedgerLockContended`` on lock
  starvation). Concurrent appends from two loop instances are
  serialised.
- **WAL cross-link** via ``count_wal_entries`` ties the ledger's
  observation stream to the assumptions WAL at
  ``.ract/assumptions.wal`` -- an entry that references an
  assumption id absent from the WAL fails verification.
- **Idempotence by ``(run_id, manifest_digest)`` within a run**
  -- re-observing the same digest is a no-op, so a compaction-
  triggered replay never inflates the ledger.

New EventKinds ``manifest.ledger.appended`` (SP Q3) and
``manifest.ledger.refused`` (SP Q5 amendment) land on the closed
vocabulary. ``ract verify`` uses the refused event to
distinguish "ledger was never bound" (no event) from "ledger
was bound but refused" (event present with ``error_kind``
naming the failure).

## Rootknot schema_version 4 (module_02)

v0.5.1 module_02 bumped ``Rootknot.schema_version`` from 3 to 4
with three OPT-IN payload fields: ``workspace_digest``,
``prompt_digest``, ``run_id``. Older sidecars continue to
verify under the v3 compatibility reader path (SCHEMA_VERSION
dispatch); a v4 sidecar carries the new fields as trailing
alphabetically-sorted entries under JCS canonicalisation.
``AcceptanceSuite.prompt_digest`` is populated by
``IntentCompiler.compile`` and drives the T8 PROMPT_DRIFT
termination hook (ADR-0040). The dispatch note: a v4 payload
constructed WITHOUT the new fields produces byte-identical
canonical bytes to the v0.5.0 v3 baseline (see
``tests/unit/test_schema_version_backread``) -- the sacred spine
extends, nothing removed.

## v0.5.2 Deep-Audit Hardening additions

Six hardening modules layered on v0.5.1 close fifteen
Ox-Alpha-partnered deep-audit findings. Each closes an attack
surface the sacred spine implicitly promised but the code did
not enforce end-to-end.

- **DOWNGRADE refusal (module_01 / DA-A M-1):** the verifier
  now carries a `min_acceptable_schema_version` policy floor.
  Without it, a v4 knot could be relabelled as v1 and re-signed
  by the same key-holder and verified as a weaker attestation.
  Default floor stays at v3 (v0.5.1 compat); strict deployments
  set `--min-schema 4`.
- **v4-label-implies-v4-fields (module_01 / DA-A F-1/F-2/F-5):**
  `Rootknot.__post_init__` now refuses a v4-labelled knot with
  absent `workspace_digest` / `prompt_digest` / `run_id`;
  `_check_rk3` cross-checks at verify time because deserialization
  paths (copy/pickle) can bypass `__post_init__`.
- **Known-schema-versions allowlist (module_01 / DA-A M-2):** a
  hostile `schema_version=9` payload is refused with
  `RK-UNKNOWN-SCHEMA` rather than falling through to v3
  semantics.
- **Library-injection env deny (module_02 / DA-A F-3):**
  `NEVER_PASSTHROUGH` extended by 40+ classic vectors including
  `LD_PRELOAD`, `DYLD_INSERT_LIBRARIES`, `PYTHONPATH`,
  `NODE_OPTIONS`, `BASH_ENV`, `GLIBC_TUNABLES` (CVE-2023-4911),
  `GIT_SSH_COMMAND`, `HTTPS_PROXY`, `PSMODULEPATH`.
- **PID-reuse guard (module_03 / DA-A F-4 + M-5):** every
  `SubprocessSubagentHandle.dispose` captures the pid's
  `creation_time_ns` at spawn; a signal is refused with
  `substrate.subagent.pid_reuse_detected` when the live pid's
  creation time no longer matches. Killing the wrong tenant is
  worse than a leaked descendant.
- **RACT_RUN_ID strip-and-reinject (module_04 / DA-B F-3.1):**
  a hostile parent env's `RACT_RUN_ID=victim` is stripped from
  the spawned child's env; the loop's ambient value is
  re-injected. Even the `env=None` path now flows through the
  strip helper (module_04 SP amendment) so no substrate spawn
  path leaks the poisoned key.
- **RACT_RUN_ID boundary regex (module_06 / m04 C-6 fold):**
  `bootstrap_ambient_from_env` refuses a `RACT_RUN_ID` value
  that fails `^[A-Za-z0-9_-]{1,240}$`. Path-shape values
  (`../`, absolute paths, whitespace, shell metacharacters,
  dots) fail the boundary check and the subagent falls through
  to synthetic-orphan generation. Rationale: module_05's
  `{run_id}.verify.json` sidecar takes this value straight into
  a filesystem path.
- **Torn-tail decode (module_05 / DA-B F-4.5):** trace-log
  post-crash tails are readable via a last-line `errors="replace"`
  fallback (body stays strict). `TORN_TAIL` reports as a
  first-class status; the chain is resumable at exit code 0.
- **Unknown sidecar format refusal (module_06 / m01 Q3 fold):**
  `_knot_from_json` refuses a sidecar with an unknown named
  `schema` literal (e.g. `sidecar/v9`) rather than silently
  downgrading to v1 semantics.
- **On-move reorder-race defense (module_06 / DA-B F-5.4):**
  the watcher's flush loop now decides delete-vs-write from the
  file's actual existence at flush time, not the enqueued flag.
  Bounds stale-cache-miss windows introduced by network-share
  event reordering to a single scan interval.

## Reporting

See [SECURITY.md](../SECURITY.md) for the vulnerability reporting
policy and PGP key.

<!-- RACT 0.5.2 -->

