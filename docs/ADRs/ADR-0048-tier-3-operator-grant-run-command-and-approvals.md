# ADR-0048: Tier 3 by Operator Grant: Commands, Tests, Git, Network, Approvals and Trust

## Status

Accepted 2026-10-30 (07:47 PT) by the owner: decisions 1 to 4, 6 to 9 and 11
as recommended, with two amendments (R4 and the unlock window in D2, marked
below). Decision 10 (a patch release) is not decided here. Proposed for v0.6,
section 2 of the agentic brief. Amends ADR-0012 on one point (D1). Companion to
ADR-0047 (tool layer, agent loop, review and undo), which this ADR does not
repeat.

## Decisions for the operator

Each is argued below with its rejected alternatives.

1. Open tier 3 per project through a signed operator grant, keeping
   `RACT_TIER_3_ENABLED` at `False` (D1). This amends ADR-0012.
2. Key custody: an Ed25519 key outside every workspace, always
   passphrase-protected, with a short in-memory unlock window (D2).
3. Tier 2 asks instead of running silently (R1).
4. Handshake approvals written outside a session must be signed (R2).
5. Keys move out of `.ract/` (R3).
6. The production substrate gets a manifest, handshakes and a sandbox
   backend (R4).
7. Only `external` content disables allowlist rules for the rest of a step
   (D9), revisited if approvals per task run high (D6 metric).
8. Windows runs commands as `best_effort`, reported as not confining the
   filesystem or network (D7).
9. `unrestricted` mode exists only under a grant with `max_mode` set (D6).
10. A guided first grant (D13) so a new user reaches a signed test-runner
    rule in under two minutes.

## Context

A coding tool that cannot run the tests cannot check its own work. Today
RACT refuses every tier-3 action. `TierPolicy.allow_tier_3` exists, but
`ManifestValidator` refuses it while the module constant
`RACT_TIER_3_ENABLED` in `src/ract/security/manifest.py` is `False`, and
ADR-0012 says only an ADR that flips the constant can change that. The
reason is sound: a manifest the run itself authors must never lift its own
ban, and the named incidents (home-directory deletion, the 70-file deletion,
the production database) all came from tools where a runtime flag was
enough.

The brief keeps that constant as it is and asks for tier 3 to be reachable
per project, by the operator, without a code change, and never unreviewed.
The design has to hold on Windows, the operator's primary platform.

## Enforcement today

The threat model and ADR-0012 describe more enforcement than the code
performs. This ADR is written against the code at the end of Phase 0:

| Finding | Where | This ADR |
|---|---|---|
| The Linux and macOS sandbox backends render a bubblewrap or `sandbox-exec` command and never execute it. No Landlock or seccomp call exists anywhere. Only the scrubbed environment is consumed. | `src/ract/security/sandbox_linux.py:176-481`, `src/ract/security/sandbox_macos.py:94-277`, `src/ract/executor/loop.py:1186` | D7 states what will be enforced and when. Until then every platform is reported as `enforced: false`. Honest reporting in `ract doctor`, `THREAT_MODEL.md` and the README ships as a defect fix now. |
| `resolve_backend` has no caller, and the `--allow-unenforced-sandbox` flag it refers to does not exist. | `src/ract/security/sandbox.py:276-329` | D7 wires it for `run_command`; the flag becomes the grant's `sandbox: best_effort`. |
| The production `SubstrateLoop` gets no manifest, no sandbox backend and no handshake registry. | `src/ract/harness.py:372`, `src/ract/executor/substrate_adapter.py:206` | Recommendation R4 below. |
| Tier 2 `REQUIRE_HANDSHAKE` counts as allowed: `Authorization.allowed` only rejects `REFUSE`, and the executor creates no handshake. ADR-0009 says the opposite. | `src/ract/core/threat_model.py:89-91`, `src/ract/executor/steps.py:983-994` | Recommendation R1 below. |
| `.ract/handshakes.json` is plain JSON with no lock, no atomic write and no signature; `ract handshakes approve` authenticates nobody. | `src/ract/handshake_registry.py:56,69-85`, `src/ract/cli.py:219-320` | Recommendation R2 below; D6 for tier 3. |
| The operator HMAC key, the per-run sandbox keys and the ALM verifier keys live inside the workspace, readable by anything that can read the project. | `.ract/operator.key`, `.ract/sandbox/*.key`, `.ract/alm/*.key` | Recommendation R3 below; D2. |
| `.ract/hooks/*.json` commands run with `os.environ.copy()` plus `RACT_*` context values, so a hook sees every API key in the operator's environment, and no gate applies. | `src/ract/hook_system.py:45-94` (environment built at 50-60) | D12. Environment scrub ships now as a defect fix. |
| The Job Object sets only kill-on-close. `ResourceBudget`, `StepTransaction.timeout_seconds` and `ProcessPolicy` are not enforced; `spawn` has no timeout. | `src/ract/executor/process_group.py:132,354-411`, `src/ract/core/transaction.py:48-68` | D5 enforces limits for commands. |
| Without a sandbox, a child process inherits `os.environ` minus `RACT_*`, provider API keys included. | `src/ract/executor/loop.py:1231` | D5 builds every command environment from the allowlist. |
| `.ract/sandbox_env.allowlist` is read from the step worktree, so a write to it widens the environment for the next spawn. | `src/ract/security/sandbox_env.py:1345` | D3: an allowlist file widens only when it is part of a signed grant. |

### Recommendations on the four existing defects (operator decisions)

- **R1 (tier 2 counts as allowed).** Recommend: `Authorization` gains
  `needs_approval`; `allowed` is false for `REQUIRE_HANDSHAKE` unless an
  approval id is attached. In a session the executor asks (D6); headless it
  records a handshake and blocks the commit (ADR-0011). Consequence: plans
  whose prose classifies as tier 2 ("git commit", "pip install") will start
  asking where they silently ran. Alternative: keep the current behavior and
  document it; rejected because ADR-0009 promises the opposite and the gap
  is invisible to the operator.
- **R2 (unsigned handshakes).** Recommend: every approval written outside a
  live session (`ract handshakes approve`) carries an Ed25519 signature from
  the operator key (D2) over handshake id, action digest and expiry, written
  with a file lock and atomic replace. Unsigned records are shown and never
  unlock anything. Alternative: sign only tier-3 approvals; rejected because
  tier 2 includes commits and control-file edits, which also change what
  runs next.
- **R3 (keys in the workspace).** Recommend: move the operator key to the
  user config directory (D2) and the per-run sandbox and ALM keys to the
  user state directory, where `SessionKey` already lives
  (`%LOCALAPPDATA%\ract\keys`, `$XDG_STATE_HOME/ract/keys`). Keep a read
  path for old locations for one release, warn, and migrate. Tools refuse
  `.ract/**` regardless (ADR-0047 D3). Alternative: keep them in `.ract/`
  and rely on path refusal; rejected because tier-3 commands on an
  unenforced backend read any file the user can, and a stolen ALM key forges
  Invariant AL-1.
- **R4 (production substrate without manifest).** Recommend: the harness
  builds a default `CapabilityManifest` from the default tier table and the
  workspace root, passes the `HandshakeRegistry`, and passes the sandbox
  backend from `resolve_backend`, with Windows reported as unenforced.
  Ships in phase 2 together with D7 honesty, since it changes every
  `ract run`. Alternative: leave the legacy path alone and enforce only in
  the new agent loop; rejected because two paths with different guarantees
  is how the current gap arose.
  **Amended on acceptance (2026-10-30):** the legacy plan-and-verify path is
  staged: first observe-only (it records what the manifest would refuse and
  refuses nothing), then enforcing one release later. The new tool layer
  enforces the manifest from its first run.

## Decision

### D1. Tier-3 governance: the constant stays, a signed grant opens one project

`RACT_TIER_3_ENABLED` keeps its value (`False`) and its meaning: no build of
RACT opens tier 3 by itself, and a manifest cannot lift its own ban. It
stays a kill switch visible in the manifest: `tiers.allow_tier_3`, the grant
digest and the key id are part of `manifest_digest`, so every RK-3
environment attestation records whether tier 3 was live and under which
grant.

A second input, an **operator tier-3 grant** (D3), can open tier 3 for
exactly one project:

```
tier3_available = (RACT_TIER_3_ENABLED or grant_verified(project))
                  and not machine_kill_switch
```

- `grant_verified`: an Ed25519 signature over the grant's canonical JCS
  bytes, checked with a public key the operator pinned in user-level config.
  Keys found in the workspace are never trusted.
- `machine_kill_switch`: `tier3: disabled` in user-level config or
  `RACT_TIER_3_KILL=1`. Either refuses every grant on that machine, for
  shared machines and CI runners that must never execute.

This changes ADR-0012's statement that only an ADR can open tier 3. After
this ADR, an ADR opens it for every project and a verified operator grant
opens it for one. The property ADR-0012 defended holds: the run cannot
grant itself tier 3, because the grant needs a key the run cannot use.

Tier map for the section 2 tools (section 1 tools are in ADR-0047 D1):

| Tool | Tier | Why |
|---|---|---|
| `git_status`, `git_diff`, `git_log`, `git_show`, `git_blame` | T0 | RACT runs git with a fixed argv; read only (D8) |
| `git_add` | T1 | Index of the step worktree only |
| `git_commit`, `git_branch`, `git_worktree` | T2 | History and refs outlive the step |
| `run_command`, `run_tests`, `build`, `lint`, `typecheck`, `format` | T3 | Execute code; repository code in most cases |
| `git_push`, `git_fetch`, `git_pull`, `git_remote`, force and ref-deleting operations | T3, always asked | Remote or irreversible |
| `web_fetch`, `web_search` | T3 | Network egress and untrusted content |
| MCP tools without a mapping | T3 | Unknown capability (section 5 adds per-server mapping) |

### D2. The operator key

- `ract policy keygen` creates an Ed25519 key pair in the user config
  directory (`%APPDATA%\ract\operator\`, `~/.config/ract/operator/`),
  outside every workspace, and pins the public key in user config.
- The private key is always encrypted with a passphrase, in the key file
  format `ract-operator-key/1` (amended 2026-10-30, D-123: the earlier
  "scrypt through `BestAvailableEncryption`" does not exist, since that
  encryption is PBKDF2): JSON holding the key id, the public key, scrypt
  parameters (n = 2^17, r = 8, p = 1, a 16-byte salt) and AES-256-GCM over
  the 32 private bytes, with the whole header (every field but the
  ciphertext) as associated data. The passphrase is NFKC-normalized before
  the KDF, so the same typed text opens the file on every system, and scrypt
  may ask for at most 512 MiB. The loader
  treats the file as untrusted data (at most 4 KiB, a closed schema, no
  link), uses the parameters it stores and refuses n below 2^15. A
  passphrase under 8 characters is refused and one under 12 warns; every
  failure to open the file gives one message. The file is 0600 on POSIX and
  limited to the user by its ACL on Windows, and `ract doctor` says which.
  On Windows any process running as the user can read the file, so the
  passphrase is the control that matters there.
- Signing asks for the passphrase on the terminal and refuses when stdin is
  not a TTY. No environment variable supplies the passphrase.
- CI never needs the private key: a grant signed on the operator's machine
  can be committed, and CI pins the public key, which is not secret.
- Rotation: `ract policy keygen --rotate` pins a new key; grants signed with
  the old key stop verifying and the session says which grant needs
  re-signing.
- Unlock window. After the operator enters the passphrase, the decrypted
  signing key stays in process memory for 10 minutes by default where
  commands are confined, and **not at all by default where a grant says
  `sandbox: best_effort`** (Windows without WSL2 or a container), so there
  every signature asks for the passphrase (amended on acceptance,
  2026-10-30). It is configurable in user config (0 disables), never written
  to disk, and cleared on exit or `/permissions lock`. Without it, every "allow
  always" costs a passphrase prompt, and operators drift to `unrestricted`
  to avoid prompts, which is worse. The window covers signing only; it never
  answers an approval.

### D3. The grant and the policy layers

**Location.** `.ract/policy.yaml` (written by the operator) and
`.ract/policy.yaml.sig` (written by `ract policy sign`). Tools cannot write
either (ADR-0047 D3).

**Layers and precedence.**

| Layer | Where | Can do |
|---|---|---|
| User | user config dir `ract/config.yaml` | Pin keys, kill switch, maximum mode, deny rules for every project, trusted projects (D12). Narrows only. |
| Project | `.ract/policy.yaml` plus signature | The only layer that can allow tier-3 actions. Unsigned, it can only narrow. |
| Session | `/permissions`, `--tier3` flag | Choose a mode up to the grant's maximum; add allow-for-session rules inside the grant. Narrows or adds within the grant only. |

A deny at any layer wins. An allow needs the project grant. The session
layer never widens past the grant.

**Schema v1.**

```yaml
version: 1
binding:
  project_root: /home/me/myrepo        # realpath at signing time
  repo_root_commit: 9b1c...            # first commit, when the project is a git repo
issued_at: 2026-10-21T18:00:00Z
expires_at: 2027-01-19T18:00:00Z       # default 90 days, max 365
key_id: ed25519:4f0a...
max_mode: ask                           # ask | allowlist | unrestricted
sandbox: enforced                       # enforced | best_effort
commands:
  allow:
    - id: tests
      argv: [python, -m, pytest]        # argv prefix, element by element
      network: false
      cwd: step_worktree                # step_worktree | step_worktree/<rel>
      timeout_s: 900
      max_output_bytes: 1048576
      home: isolated                    # isolated | real
      env_extra: [PYTHONHASHSEED]
      git_hooks: false
  deny:
    - argv: [git, push]
shell:
  enabled: false                        # true still needs approval per invocation
network_tools:
  web_fetch:
    allow_domains: [docs.python.org, pypi.org]
limits:
  max_procs: 64
  memory_mb: 4096
  cpu_seconds: 900
```

**Validation errors** name the file, line, field and fix, for example:
`policy.yaml:14 commands.allow[0].argv: [python] is too broad: an
interpreter alone runs any code. hint: name the module or script, for
example [python, -m, pytest].` Errors refuse the whole grant; a partly valid
grant grants nothing.

**When the grant is missing, expired, tampered or wrongly bound** (other
root, other root commit, unknown key, bad signature): tier 3 is off for the
session, with the reason. The grant is loaded once at session start and
pinned by digest. If `policy.yaml` or its signature changes during a
session, tier 3 is suspended until the operator confirms on the terminal.

**Revocation.** `ract policy revoke` deletes the signature and appends the
grant digest to a user-level revocation list, so a copy restored from git
history is still refused.

**A cloned repository's policy grants nothing**: its signature does not
verify under the operator's pinned key. A policy can be committed so a team
sees the rules; each operator signs their own grant.

**Status line.** `T3 off (no grant)`, `T3 off (grant expired 2026-12-01)`,
`T3 ask`, `T3 allowlist`, and `UNRESTRICTED (signed grant)` in a style that
cannot be missed. `T3 suspended: policy changed` when D3's pin trips. A grant
expiring within 7 days adds a notice at session start.

### D4. Command matching

- **argv prefix, element by element.** `[pytest]` matches
  `[pytest, -k, foo]` and not `[pytest-evil]`. Deny rules win.
- **Subcommand awareness.** For multi-command tools (`git`, `npm`, `pnpm`,
  `yarn`, `pip`, `uv`, `cargo`, `go`, `dotnet`, `docker`, `kubectl`) argv is
  split into global options, subcommand and the rest. A rule for
  `[git, status]` does not allow `[git, push]`. Global options before the
  subcommand (`git -c`, `git -C`, `git --exec-path`, `npm --prefix`,
  `cargo --config`) never match an allow rule, because they change what the
  subcommand does (`git -c alias.x=!sh` runs a shell). They go to approval.
- **Output and execution flags inside an allowed subcommand.** Known
  dangerous flags are refused from allow-rule matching: `git show --output`,
  `git diff --output`, `git log --output`, `--upload-pack`,
  `--receive-pack`, `--ext-diff`, `pytest -p` (plugin load) when the plugin
  module is in the workspace, `find -exec/-execdir/-ok/-delete`.
- **Executable resolution.** `argv[0]` is resolved through a scrubbed
  `PATH` that excludes the workspace and every directory inside it, at grant
  load and again at execution. A `./pytest` shim planted in the repo does
  not satisfy a `pytest` rule. A rule may name an in-repo executable
  explicitly (`./gradlew`); the prompt then says it runs repository code.
- **Interpreters and runners are arbitrary-code launchers.** A rule whose
  argv is a bare interpreter or runner (`[python]`, `[node]`, `[bash]`,
  `[npm, run]`, `[make]`, `[cargo, run]`, `[go, run]`, `[npx]`, `[uvx]`) is
  refused at grant load as too broad. Allowed forms name the entry point:
  `[python, -m, pytest]`, `[npm, test]`, `[make, test]`.
- **Repository-defined entry points are bound to their definition.** A rule
  that runs something the repository defines (an `npm` script, a `make`
  target, `./gradlew`, `scripts/*.sh`) stores the digest of the defining file
  (or the script entry) at approval time. A changed definition stops
  matching, so the command asks again and the prompt shows the new text.
  A command whose arguments name a file the model wrote or changed in this
  session (`python new_script.py`) always asks.
- **Wrappers.** `env`, `nice`, `nohup`, `timeout`, `time`, `stdbuf`,
  `ionice` are stripped and the inner command is matched. Environment
  assignments (`env VAR=x cmd`, or the `env` field of a call) are allowed
  only for names in the rule's `env_extra`, and never for a name in
  `NEVER_PASSTHROUGH`. `xargs`, `parallel`, `find ... -exec`, `watch`,
  `script`, `sudo`, `doas`, `su`, `runas`, `pkexec` never match: they run a
  command chosen at run time, or change privilege.
- **Hard floor, no rule can allow in argv mode:** shells and inline-code
  forms (`sh`, `bash`, `zsh`, `fish`, `cmd`, `powershell`, `pwsh`,
  `python -c`, `node -e`, `perl -e`, `ruby -e`, `deno eval`), which run only
  in shell mode (D5); privilege changes; RACT governance from inside a run
  (`ract` or `python -m ract` with `policy`, `handshakes`, `intent`,
  `operator-queue`, `config`, `provider`); package publishing (`twine
  upload`, `npm publish`, `cargo publish`, `poetry publish`, `uv publish`,
  `gh release`); remote git, which always asks (D8).
- **Windows `.bat` and `.cmd` targets** (for example `npm.cmd`) run through
  `cmd.exe`, which reparses arguments (the BatBadBut class). They are
  allowed only when every argument matches `[A-Za-z0-9_./:=@+-]+`; anything
  else is refused with a hint to use shell mode.

The bypass corpus is a table-driven red-team test
(`tests/security/test_command_matching_corpus.py`), one row per case:
substring names, planted shims, `git -c`, `git -C`, `git show --output`,
`sh -c`, `bash -lc`, `python -c`, `env LD_PRELOAD=...`, `env -i`, `xargs`,
`find -exec`, `find -delete`, `npm run` with an edited script, `make` with an
edited Makefile, `.cmd` with `&`, `%`, `"`, `^`, and Unicode look-alike
command names. Each row states the expected outcome (refused, asks, or
matches).

### D5. `run_command`

- argv execution with `shell=False` by default. Shell mode takes one string,
  needs `shell.enabled: true` in the grant, and asks for every invocation
  regardless of mode, rules or session approvals.
- Spawned through `process_group.spawn` with:
  - `stdin` closed (`DEVNULL`): a command cannot wait on input and the model
    cannot type into it;
  - the `sandbox_env` allowlist plus the rule's `env_extra`, minus
    `NEVER_PASSTHROUGH`, minus every `RACT_*` variable except `RACT_RUN_ID`;
  - `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA` and `XDG_*` pointed at a
    per-step temporary directory unless the rule says `home: real`;
  - `cwd` pinned to the step worktree or a subdirectory of it;
  - limits: POSIX `setrlimit` (`RLIMIT_NPROC`, `RLIMIT_AS`, `RLIMIT_CPU`,
    `RLIMIT_FSIZE`); Windows Job Object `ActiveProcessLimit`,
    `JobMemoryLimit`, `PerJobUserTimeLimit`;
  - a hard wall-clock timeout, then `kill_tree` after a short grace period.
- stdout and stderr are captured with byte caps. A cut shows the head, the
  tail and a marker naming how many bytes were dropped. Escape sequences are
  stripped from what the model and the operator see.
- The result is `Rooted[CommandResult]` (D10 lists the fields).
- Files a command writes inside the worktree become part of the step's
  proposed change and go through review (ADR-0047 D6). Files it writes
  outside the worktree are not tracked; on an unenforced backend that is a
  residual risk the prompt states.

**Budgets for commands.**

| Limit | Default | Ceiling set by | Lowered by |
|---|---|---|---|
| Wall time | 300 s | grant rule `timeout_s` | `ract.yaml`, session |
| Output kept | 1 MiB per stream | grant rule `max_output_bytes` | same |
| Processes | 64 | grant `limits.max_procs` | same |
| Memory | 4 GiB | grant `limits.memory_mb` | same |
| CPU time | 900 s | grant `limits.cpu_seconds` | same |

### D6. Approvals

**Order of checks** for a tier-2 or tier-3 action:

1. Tier 3 with no verified grant: refused, hint names `ract policy init`,
   `ract policy sign` and this ADR.
2. Hard floor or a deny rule: refused, naming the rule.
3. The session mode decides the rest:
   - `off` (default without a grant): tier 3 refused; tier 2 asks.
   - `ask` (default with a grant): every tier-2 and tier-3 action asks.
   - `allowlist`: a command matching an allow rule runs without asking;
     tier 2 asks.
   - `unrestricted` (only when the grant's `max_mode` is `unrestricted`):
     tier-3 commands outside the floor and deny rules, and local tier-2
     actions (commit, branch, control-file edits), run without asking.
   In every mode, these always ask: shell mode, remote git, a command that
   names a file the model wrote this session, a changed repository-defined
   entry point (D4), and any tier-2 or tier-3 action in a step that has taken
   in `external` content (D9).
4. The mode changes only through operator input: `--tier3 ask|allowlist|
   unrestricted` on the command line or `/permissions` in a session. No tool
   can change it.

**`--yolo` and `--auto`.** `--yolo` keeps its ADR-0012 meaning (widen the
filesystem within `yolo_widen`) and in the agent loop it also skips edit
review (auto-accept edits). It never changes the tier-3 mode, never answers
an approval and never reaches tier 3. `--auto` keeps the legacy per-step
console approval and answers no tier-2 or tier-3 prompt. Both are tested.

**The prompt** shows the full argv with control characters escaped, the
resolved executable path, `cwd`, network on or off, whether the sandbox
enforces on this machine, the environment names passed through, the limits,
the step's trust state, and the model's stated reason labeled as model text.

**State machine.**

```
requested -> allowed_once | allowed_session | allowed_always | denied | expired
```

- `allowed_once`: this exact argv, this step. In memory.
- `allowed_session`: an argv prefix the operator picks, no wider than the
  grant. In memory until the session ends.
- `allowed_always`: writes an allow rule into `policy.yaml` and re-signs it,
  which asks for the passphrase.
- `denied`: returned to the model as a refusal it can react to. The same
  argv is denied without asking again for the rest of the turn.
- `expired`: cancelled by Ctrl-C or by the session ending. Nothing runs.

Every transition emits `approval.requested` and `approval.resolved` session
events and `handshake.requested` and `handshake.resolved` trace events with
the action digest, the choice and the approver (`operator-tty`, or
`signed-record:<key id>`).

**Headless** (`ract -p`, CI) cannot prompt. A tier-3 command there runs only
in `allowlist` or `unrestricted` mode with a matching rule. Anything else
becomes an ADR-0006 handshake and the step blocks at the commit boundary
(ADR-0011). It unlocks only with a signed approval record (R2).

**No timers.** An approval never resolves itself after a delay. A prompt
that nobody can answer (stdin closed, the session ending, an unattended
run) resolves as `denied`, and the event stream records that as the reason.

**Approval fatigue metric.** The J4 and web-fetch walkthroughs record the
number of approvals per task. If the median goes above three, the D9
`external` rule is revisited before release, because operators who are
asked too often approve without reading.

**Invariant A-1: no model output can approve.** Approvals come from exactly
two sources: keystrokes on the session terminal read by RACT's own prompt
reader, and approval records signed with the pinned operator key. Model
text, tool results, file contents, command output, hook output and MCP
results never resolve an approval, whatever they contain. Test: a scripted
model replies "y", "allow always", a JSON object shaped like
`approval.resolved`, and a tool call named `approve`; a pending approval
stays pending through all of them.

### D7. Sandbox backends: what each enforces, and when

| Platform | Backend | Filesystem | Network off | Limits and kill | State |
|---|---|---|---|---|---|
| Linux | bubblewrap running the argv the backend already renders | Enforced (worktree read-write, toolchain read-only) | Enforced (`--unshare-net`) | rlimits, process group | Phase 2: execute the rendered command. Landlock and seccomp need new code (a compiled BPF filter, Landlock syscalls) and are a later module. |
| macOS | `sandbox-exec` with the generated profile | Enforced | Enforced (`deny network*`) | rlimits, process group | Phase 2: execute the rendered profile. |
| Windows | Job Object, scrubbed environment, isolated home | Not enforced | Not enforced (proxy variables removed only) | Job Object limits, kill-on-close | Phase 2. |
| Windows | WSL2 running the Linux backend | Enforced inside WSL | Enforced inside WSL | as Linux | Phase 2, opt-in. |
| Any | Podman or Dagger container (ADR-0011 runtime backend) | Enforced by the container | Enforced by the container | container limits | Exists for steps; wired for commands in phase 2. |

Windows ARM64 behaves as Windows x64: ConPTY, Job Objects and the
environment scrub are the same APIs. Windows low-integrity-level confinement
(worktree and isolated home labeled low, command started at low integrity)
would block writes outside those paths; it is evaluated during
implementation as an opt-in experimental backend.

A grant with `sandbox: enforced` refuses to run commands on a backend that
does not enforce. `best_effort` permits it; every such command records
`enforced: false`, and the prompt and the run report say so.

`ract doctor` reports, per platform, which backends are present, which one a
command would use, and one line per property: filesystem, network,
processes, environment, each `enforced`, `reported only` or `absent`. Until
phase 2 lands it reports every platform as not enforcing, which is the truth
at the end of Phase 0.

### D8. Git as tools

RACT runs git with `-c core.fsmonitor=false`, `-c core.hooksPath=` set to an
empty directory, `--no-ext-diff`, `--no-textconv` and no pager, so
repository configuration cannot run a program during a read. Commit hooks
are repository code and run only when the matched rule sets
`git_hooks: true`. Before a commit the staged diff is scanned for secrets; a
hit refuses the commit and names the file and line, and only the operator on
the terminal can override it. Remote operations always ask, in every mode.

### D9. Trust labels and the injection rule

Every item in a step's conversation carries one label, rendered in the
context as a delimited block (`<data trust="external" source="web"
url="...">...</data>`), never as instruction text:

- `operator`: what the operator typed, and guidance files from a trusted
  project (D12).
- `workspace`: tracked or untracked non-ignored files, git output, and
  output of local commands that ran with network off.
- `external`: web pages, search results, MCP results, output of commands
  that ran with network on, and files under gitignored paths
  (`node_modules`, `vendor`, `.venv`), which are usually third party.

Once a step has taken in `external` content, the rest of that step can reach
tier 2 or tier 3 only through an explicit allow-once approval. Allowlist
rules, session approvals and unrestricted mode stop applying. Headless, the
action becomes a handshake.

A call that the model quotes from content it read is still parsed as a
call (`ract.tool_calls` reports the prose around it as `prose_before` and
`prose_after`). Parsing grants nothing: the call goes through the tier gate,
the matching rules and this trust rule like any other. Test:
`test_f5_a_quoted_fenced_call_is_marked_as_inside_prose` in
`tests/test_tool_calls.py`, and the end-to-end case in the D9 red-team
tests once the loop exists.

Workspace content stays eligible for allowlist rules. A repository is the
operator's own code, and a rule that cannot survive reading a file would
make the allowlist useless. Injection through workspace files is bounded: it
reaches only what a signed rule already allows, and every rule is something
the operator wrote and signed.

### D10. What is recorded for a command

A Rootknot attests that a file's content was produced under the run's
signatures. A command execution is a different fact, so it is recorded in
the hash-chained trace and in a per-step `commands.jsonl` sidecar:

- argv as executed, resolved executable path and its SHA-256;
- `cwd` relative to the workspace;
- the names of environment variables passed (never values) and the digest
  of the allowlist that produced them;
- grant digest, rule id, approval id and approver;
- sandbox backend and `enforced` flag, limits applied;
- exit code, duration, `killed_by`;
- stdout and stderr sizes, SHA-256 digests and truncation flags.

Binding the `commands.jsonl` digest into the step's Rootknot needs an
optional field in the Rootknot payload, which is a sacred-spine change. It
is deferred to its own ADR. Until then the trace chain is the attestation,
and the harness verdict and `ract verify` must say so in plain words
("command records are in the trace; they are not part of the signed
Rootknot"). The Rootknot field ADR is scheduled before `ract verify`
(board card B-039).

### D11. Network tools and data egress

- `web_fetch` is tier 3 and needs `network_tools.web_fetch` in the grant.
  HTTPS only. The domain must be on `allow_domains`, checked again on every
  redirect hop. Targets that resolve to loopback, private, link-local or
  cloud metadata addresses are refused after DNS resolution. Size cap,
  content-type allowlist (HTML, plain text, Markdown, JSON), HTML reduced to
  text. Results are labeled `external`.
- `web_search` is an adapter interface with no default provider. Without one
  it refuses with a hint.

The statement "nothing leaves the machine except calls to the providers the
operator configured" becomes checkable with `ract doctor --egress`, which
lists every destination RACT itself can contact: each configured provider
URL, each `web_fetch` domain in the grant, and each command rule with
`network: true`. A test pins the set of modules allowed to open network
connections. The report says plainly what RACT cannot see: a command with
network on, and any command on a backend that does not enforce network off,
can contact hosts RACT does not list.

### D12. Repository-supplied configuration and trust on first open

A repository can carry hooks (`.ract/hooks`), skills, MCP server
definitions, a policy and guidance files. Each is a way for a cloned
repository to run code or steer the model. RACT keeps a user-level list of
trusted projects (realpath plus root commit). Until the operator trusts a
project:

- no hook, skill or MCP server from the repository is loaded;
- the project policy is ignored, signed or not;
- guidance files are loaded as `workspace` content, never as `operator`
  content.

Opening an untrusted project in a session asks once and shows what would be
loaded. Headless runs never ask: an untrusted project loads none of it and
prints a notice. `--bare` loads none of it even for a trusted project. Until
the hook design lands, hook commands run with the scrubbed environment.

### D13. A guided first grant

Without help, reaching `run_tests` takes four steps: keygen, init, editing
`policy.yaml`, and signing. `ract policy init --guided` (and `/permissions`
in a session) does it in one flow: it detects the test runner from the
repository, proposes the narrowest rule (for example
`[python, -m, pytest]` with network off and a 15-minute limit), explains
each field in one line, shows the resulting `policy.yaml` as a diff, creates
the key if there is none, and signs once. Acceptance: a new user goes from
no grant to a signed `pytest` rule in under two minutes in a real terminal,
with the transcript saved as a walkthrough.

### Implementation slices

Each slice ends with a real-terminal walkthrough of the journeys it
touches.

1. Tool layer with review and undo (ADR-0047).
2. Policy loader, keygen, sign, guided grant, status line (D2, D3, D13).
3. `run_tests` in `ask` mode on the existing process group (D5, D11).
4. Windows enforcement work for commands (Job Object limits, the
   low-integrity evaluation), right after the first `run_command` slice.
5. Allowlist mode, session approvals and the approval prompt polish (D4,
   D6).
6. Sandbox execution on Linux and macOS (D7).
7. Git tools (D8).
8. Network tools (D11).

## Compatibility

- Without a grant, tier 3 is off exactly as today, and existing configs
  behave as before.
- `tests/security/test_manifest_schema.py` and `test_yolo_narrowing.py` keep
  passing: the constant is unchanged and those tests carry no grant.
  `ManifestValidator` gains one path (a verified grant in `RunContext`) with
  its own tests.
- Existing sidecars verify unchanged. No Rootknot schema change in this ADR.
- No new runtime dependency (`cryptography` is already declared), so the
  import allowlist does not change.
- New verbs (`ract policy`, `ract doctor --egress`) are registered in
  `CLI_VERBS`, `cli_help.py`, `docs/USE_CASES.jsonl` and the README index.
- Every commit that changes `src/ract/` re-locks the source digest.

## Threat table

Attackers: a hostile repository, hostile model output (a compromised or
confused model), a hostile web page, a hostile MCP server, and a careless
operator. Out of scope: other malware already running as the operator's
user, which can attack RACT's process directly.

| Asset | Attacker | Vector | Control | Residual risk |
|---|---|---|---|---|
| Tier-3 capability | Hostile repo | Ships a permissive `.ract/policy.yaml` | Signature under the operator's pinned key (D3); untrusted project ignores policy (D12) | None known |
| Tier-3 capability | Hostile model | Writes policy, signs, or calls `ract policy` | `.ract/**` refused to tools; floor bans RACT governance verbs (D4); signing needs a TTY passphrase (D2) | On an unenforced backend an allowed command can rewrite `policy.yaml`; the digest pin suspends tier 3 (D3) |
| Approvals | Hostile model | Text or tool output that looks like an approval | Invariant A-1 | None known |
| Approvals | Hostile model via command | Edits `.ract/handshakes.json` | Signed records only (R2) | Unsigned tier-2 records until R2 ships |
| Operator key | Hostile model via command | Reads the key file | Passphrase encryption (D2), key outside workspace | An offline guess of a weak passphrase |
| Credentials in env | Hostile model | Command prints its environment | Env built from allowlist, `NEVER_PASSTHROUGH`, isolated home (D5) | Secrets in files a `home: real` rule exposes |
| Files outside the project | Hostile model | Command writes or deletes elsewhere | Enforced backends (D7); cwd pin | Windows default backend does not confine (stated, `best_effort` required) |
| Command allowlist | Hostile repo or model | Planted shim, `git -c`, `npm run` with edited script, wrapper, `.cmd` metacharacters | D4 matching rules and corpus | New bypass shapes; corpus grows with each one found |
| Machine availability | Hostile model | Fork bomb, memory bomb, endless output, hang | D5 limits, caps, timeout, tree-kill | Short spikes inside the limits |
| Operator's attention | Hostile model | Escape sequences that disguise an approval prompt | Escaping in the prompt (D6) | None known |
| Tool decisions | Hostile web page | Injected instructions in fetched text | `external` label and rule (D9), SSRF and redirect checks (D11) | The model may still produce wrong but harmless output |
| Tool decisions | Hostile MCP server | Injected instructions or a tool that misdescribes itself | MCP results `external`; unmapped tools tier 3 (D1); untrusted repo MCP not loaded (D12) | A trusted MCP server that turns hostile later |
| Secrets in git history | Careless operator or model | Commits a key | Staged-diff secret scan (D8) | Secrets the scanner's patterns miss |
| The whole machine | Careless operator | Grants `[python]` or `unrestricted` without thinking | Too-broad rules refused at load (D4); unrestricted needs `max_mode` in a signed grant; loud status line | An operator who signs a wide grant gets a wide grant |
| Data egress | Careless operator | Assumes nothing leaves the machine | `ract doctor --egress` (D11) | Network from commands on unenforced backends |

## Red-team tests

In `tests/security/`, following the named-incident tests: forged, unsigned,
expired, rebound and wrong-key grants; policy edited mid-session; self-signed
approval file; `ract policy sign` and `ract handshakes approve` from a
command; the D4 corpus; environment leak (`OPENAI_API_KEY`,
`RACT_OPERATOR_KEY`, `HTTPS_PROXY`, `LD_PRELOAD`); fork bomb, memory bomb,
giant output, hang, grandchild outliving its parent; escape sequences in an
approval prompt; Invariant A-1; external-taint rule with a fetched page and
an MCP result; `curl ... | sh` requested from a repository file;
`core.fsmonitor` and a `pre-commit` hook in the repository; a staged AWS key;
SSRF to `169.254.169.254`, to `localhost`, and through a redirect; `--yolo`
with and without a grant; untrusted-project hooks and `--bare`.

## Rejected alternatives

- **Flip `RACT_TIER_3_ENABLED`.** Opens tier 3 for every project on every
  machine running that build. The brief rules it out.
- **A runtime flag or environment variable that opens tier 3.** ADR-0012
  rejected this shape, and the named incidents show why: anything the
  process environment can set, a compromised step can set.
- **An unsigned `policy.yaml`.** A cloned repository could ship its own
  allow rules. Backlog item m02-M3 already records that mistake for
  `.ract/sandbox_env.allowlist`.
- **An HMAC key in `.ract/`, as `operator.key` is today.** Readable by the
  commands it is supposed to govern.
- **OS keystores without a passphrase** (DPAPI, Keychain, Secret Service).
  Any process running as the user can ask them to decrypt.
- **Substring or regex command matching.** Matches more than the operator
  meant, and regexes over argv are hard to review.
- **Shell by default.** A shell string is a program; review becomes
  parsing. argv by default keeps the reviewed thing and the executed thing
  identical.
- **Tier by sandbox strength** (tier 2 when enforced, tier 3 when not).
  Attractive on Linux, but the operator's main platform would always land
  in tier 3, and two tier tables for one action make policies harder to
  read. Recorded for a later ADR.
- **Treat every file as `external`.** Allowlist rules would stop working
  after the first read, and operators would switch to blanket approvals.
- **Let the model ask for a mode change.** Even a request the operator must
  confirm trains the operator to click yes. Modes change only from operator
  input.

## Consequences

- RACT can run tests, builds and linters on projects the operator has
  granted, and feed real results into verification.
- The governance boundary moves from "an ADR in this repository" to "an ADR,
  or a signed grant for one project". The operator should ratify that
  change explicitly.
- Every tier-3 action is approved on the terminal, covered by a signed rule
  the operator wrote, or blocked as a handshake that only a signed record
  unlocks.
- Four existing defects get decisions (R1 to R4) instead of staying
  undocumented.
- Windows users get honest reporting where enforcement is missing. WSL2 and
  containers are the enforced paths there.

## Negative and follow-ups

- Windows filesystem confinement is not in the default. Low integrity level
  and AppContainer are evaluated during implementation.
- Landlock and seccomp on Linux need a module of their own.
- Binding command records into the Rootknot needs a sacred-spine ADR (D10);
  schedule it before `ract verify` (B-039).
- Outbound secret scanning on provider requests and transcript redaction
  are section 7.
- Per-server MCP tier mapping is section 5.

## References

- ADR-0004, ADR-0006, ADR-0009, ADR-0011, ADR-0012, ADR-0041, ADR-0047
- `src/ract/security/manifest.py`, `src/ract/security/sandbox.py`,
  `src/ract/security/sandbox_linux.py`, `src/ract/security/sandbox_macos.py`,
  `src/ract/security/sandbox_env.py`, `src/ract/executor/process_group.py`,
  `src/ract/handshake_registry.py`, `src/ract/core/intent_recompile.py`,
  `src/ract/hook_system.py`, `src/ract/core/threat_model.py`
- `docs/RACT_v0.6_BACKLOG.md` (m02-M3, m02-C1)
- `docs/THREAT_MODEL.md`, section "v0.6 agentic execution amendment"
