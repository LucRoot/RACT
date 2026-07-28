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
canonical JSON (sorted keys) for the digest that downstream modules
join against. Module_06's extended ``Rootknot`` stamps the digest as
``manifest_digest`` — the manifest is the substrate the environment
signature attests.

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

## Reporting

See [SECURITY.md](../SECURITY.md) for the vulnerability reporting
policy and PGP key.
