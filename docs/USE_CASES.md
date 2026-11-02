# RACT use cases

This page renders `docs/USE_CASES.jsonl`, the catalog of what RACT is for.
The jsonl is the record of truth: `tests/test_use_cases_catalog.py` gates it
against the CLI verb surface, so every accepted title below starts with a
shipped verb and no refused title collides with one. Regenerate this page
from the jsonl when the catalog changes.

## Accepted goals

| Title | What it is for | Why it is accepted |
|---|---|---|
| `run` | Execute an intent as a planned-and-verified RACT run. | Canonical execute-an-intent verb; every downstream flag applies. |
| `skills` | List and inspect builtin and installed skills. | Skill registry surface exposed to operators. |
| `mcp` | Manage and invoke MCP tools registered with RACT. | MCP adapter surface for external tool servers. |
| `retrieval` | Query the retrieval adapter over the current workspace. | Retrieval adapter operator surface. |
| `diff` | Show and apply RACT-authored diffs against the workspace. | Diff apply and inspection surface. |
| `explain` | Explain a plan, step, or artifact with its provenance chain. | Provenance-first explanation surface. |
| `report` | Render run reports in markdown or HTML. | Run reporter surface. |
| `handshakes` | List, approve, reject, defer, or review pending operator handshakes. | Deferred-approval operator surface (ADR-0006). |
| `refactor` | Run a scoped refactor over a named target. | Refactor mode surface. |
| `rename` | Rename a symbol project-wide through the symbol renamer. | Symbol renamer surface. |
| `docs` | Generate or regenerate documentation for the workspace. | Documentation generator surface. |
| `init` | Initialize a new RACT project from a template. | Project initializer surface. |
| `openapi` | Generate an OpenAPI client or server scaffold. | OpenAPI generator surface. |
| `plan` | Load, save, or replay a serialized plan. | Plan serializer and replay surface. |
| `doctor` | Diagnose RACT installation, config, and workspace state. | Health-check surface. |
| `audit` | Audit a workspace or run for anti-rot and provenance issues. | Anti-rot audit surface. |
| `load-bearing` | Inspect or manage load-bearing annotations across the workspace. | Load-bearing guard surface. |
| `novelty` | Report novelty budget usage and scan for overruns. | Novelty budget surface. |
| `coverage` | Report coverage deltas and status. | Coverage delta surface. |
| `quality` | Compute the plan quality scorecard. | Quality scorecard surface. |
| `mutation` | Run the mutation test suite and report kill counts. | Mutation runner surface. |
| `whisper` | Run the Legacy Whisperer over a target module. | Legacy whisperer contract surface (ADR-0017). |
| `auction` | Run the Dead Code Auction sweep and inspect proposals. | Dead code auction contract surface (ADR-0017). |
| `fence` | Enforce or inspect Chesterton's Fence records over the workspace. | Chesterton's Fence contract surface (ADR-0017). |
| `marketplace` | Browse and install skills from the skills marketplace. | Skill marketplace surface. |
| `consolidate` | Scan, apply, or rollback consolidation proposals over the workspace. | Consolidation scanner surface. |
| `release` | Prepare and publish a GitHub release for the current tag. | GitHub release client surface. |
| `merge-gate` | Evaluate the merge gate over pending changes. | Mutation-merge-gate surface. |
| `rot-report` | Render the anti-rot report. | Anti-rot reporting surface. |
| `receipt-export` | Export a bundle of signed receipts for downstream verification. | Receipt export surface. |
| `rot` | Run anti-rot scans and inspect results. | Anti-rot scanner surface. |
| `operator-queue` | Inspect the operator queue of pending requests. | Operator queue surface. |
| `receipt` | Load, verify, or inspect a signed receipt or receipt chain. | Receipt verification surface. |
| `policy-gate` | Evaluate the policy gate against pending changes. | Policy gate surface. |
| `run-fingerprint` | Compute or diff run fingerprints for reproducibility checks. | Run fingerprint surface. |
| `ai-sbom` | Emit an AI-SBOM for the current run. | AI-SBOM emission surface. |
| `calibrate` | Run the experimental calibration harness. | Experimental calibration surface. |
| `infer` | Run the experimental inference harness. | Experimental inference surface. |
| `repro-manifest` | Emit an experimental reproducibility manifest. | Experimental reproducibility surface. |
| `config` | Inspect, diff, or validate the ract.yaml configuration. | Configuration surface. |
| `provider` | Inspect provider presets and routing. | Provider routing surface. |
| `cost` | Report cost accumulation across a run or session. | Cost accounting surface. |
| `router` | Inspect provider router state and complexity routing. | Router surface. |
| `self-audit` | Run RACT's self-audit checks over its own installation. | Self-audit surface. |
| `status` | Report current session status and outstanding blockers. | Session status surface. |
| `leaderboard` | Render the public leaderboard rollup. | Public leaderboard surface. |
| `session` | List, resume, rollback, or inspect saved sessions. | Session store surface. |
| `conformance` | Run the closed-action-union conformance suite (ADR-0014). | Conformance harness surface. |
| `trace` | Inspect the hash-chained event log for a run (ADR-0015). | Event log inspection surface. |
| `provenance` | Inspect and verify Rootknot-signed provenance sidecars. | Provenance verification surface. |
| `source-digest` | Compute or lock the source-tree golden hash over src/ract. | Golden hash lock surface; see src/ract/source_digest.py. |
| `manifest` | v0.1.2-era alias for repro-manifest; emits an experimental reproducibility manifest. | CHANGELOG 0.1.2 named this verb explicitly; the alias restores the historical surface. |
| `memory` | Manage the memory substrate: three indexes (symbol / graph / semantic), retrieve primitive, four function contracts (intake / research / plan / edit), and three self-adjustment probes (needle / coherence / adherence). | Memory Discipline module_09 landed the memory substrate CLI surface (v0.5.0); this entry pairs the top-level `memory` verb with its dispatch subverbs (`memory init`, `memory apply-narrowings`). |
| `intent` | Manage the intent surface of an existing run. One subverb ships in v0.5.1: `intent recompile <run_id>` performs an operator-signed recompile of a run's intent under a new AcceptanceSuite, appending a suite version to <run_dir>/suite_chain.jsonl so the loop's T8 PROMPT_DRIFT check accepts the new intent text. Requires `--intent-file` XOR `--intent-text`; loads the operator key from `.ract/operator.key` OR the `RACT_OPERATOR_KEY` env var; exit codes 2 (usage) / 3 (key missing) / 4 (suite.json missing) / 5 (compile failure). | v0.5.1 module_04 distinguishes legitimate intent evolution from attacker injection: operator possesses the .ract/operator.key marker file (or RACT_OPERATOR_KEY env var); attacker does not. Silent intent mutation trips T8; signed recompile lets the loop continue. Entry pairs the top-level `intent` verb with its dispatch subverb (`intent recompile`). |
| `manifest ledger verify` | Run verify_chain over the historical manifest ledger and print valid/broken-at. v0.5.1 wiring module_10 (Lens A M1) added this subverb; the ledger library shipped in v0.5.1 module_07 but had no CLI surface until now. | Operator needs a shell-level way to detect manifest-ledger tamper without writing Python; wire-in of ManifestLedger.verify_chain (with the module_09 entry_index density check). |
| `manifest ledger inspect` | List entries in append order with --start / --limit slicing (default: first 20). v0.5.1 wiring module_10. | Operator triage of a ledger break -- lets the shell walk entries in order. |
| `manifest ledger show` | Print one entry's full payload (all fields). v0.5.1 wiring module_10. | Deep-dive into a single entry when verify or inspect flag it. |
| `manifest ledger proof` | Emit the Merkle proof (forward-hash chain) for an entry so an offline verifier confirms inclusion. v0.5.1 wiring module_10. | Wire-in of ManifestLedger.proof_of; lets audit tooling export inclusion proofs without a Python-level import. |
| `repl` | Open an interactive RACT session in the current directory (`ract repl [--config PATH]`, also what bare `ract` does on a terminal). Plain text runs as an intent; lines starting with `/` are commands (`/plan`, `/loop`, `/set`, `/settings`, `/session`, `/providers`, `/doctor`, `/report`, and every other verb). Settings and a session id carry context between turns. It dispatches through the same entry point as the one-shot CLI, adds no dependency, and refuses to start without a terminal (exit 3). | Operators expect an in-app prompt like other agentic CLIs, not one shell invocation per task. The session is a front end over ract.cli.main, so it adds no new execution path and no new capability: tier policy, handshakes and approval modes apply exactly as on the command line. |
| `trust` | Trust this repository's own commands and endpoints (hooks, MCP servers, gates), or list and remove trust. | A cloned repository could make RACT run its commands with no question (S-025). |
| `policy` | The operator key and the signed tier-3 grant: keygen, sign, status, revoke. | Tier 3 opens only through a grant the operator signs with a key kept outside every workspace (ADR-0048 D2, D3). |
| `setup` | Check this machine, choose a local or cloud model, and write a working ract.yaml. | A first-time user had to know a preset, a URL, a key variable and a model size before RACT would run (B-015). |
| `undo` | Reverse the last RACT turn: restore the files it replaced, remove the files it created. | The turn summary named the previous versions and nothing used them (B-049). |
| `redo` | Reverse the last undo. | An undo can itself be a mistake; it is reversible once (B-049). |
| `verify` | Check a commit range and/or a run: every changed line attributed to a signed step, each Rootknot verified, the trace chain when the run has one. | One offline provenance check (ADR-0050 D4, D-174). |

## Refused non-goals

Each title names the scenario RACT refuses; a refused entry is the record
of a decision not to build that surface. Removing one needs an ADR.

| Refused surface | What was asked | Why it is refused |
|---|---|---|
| `authorship as identity invariant` | Embedding operator names in module source as a load-bearing identity marker. | Identity attestation is decoupled from author names; the module-knot registry (src/ract/core/module_identity.py) provides load-time attestation without coupling module identity to any person's name. |
| `operator-machine training pipeline` | Training a first-party model inside the RACT toolchain from operator interaction traces. | Out of scope; RACT is a claim-and-verify agentic coding tool, not a model-training platform. |
| `declarative script-first workflow layer` | A YAML- or DSL-driven workflow engine that replaces the plan-and-execute loop. | Plans stay first-class; workflow-DSL would obscure assumption, confidence, and provenance which are the load-bearing invariants. |
| `package-registry publish without handshake` | Publishing to PyPI, npm, or crates.io from a RACT run without an operator-signed handshake. | Refused by ADR-0007 threat model; requires --allow-tier-3 and an operator handshake. |
| `workspace escape` | Writing or modifying files outside the configured workspace root. | Refused by ADR-0007 threat model; sandbox refuses at the executor boundary. |
| `bulk workspace exfiltration` | Sending the full workspace to a remote provider in a single request above the chunk threshold. | Refused by ADR-0007 threat model; default 1 MiB chunk threshold prevents whole-tree upload. |
| `sensitive-file read` | Reading credential files like .env, *.pem, id_rsa, or ~/.ssh/** during a run. | Refused by ADR-0007 threat model; path patterns denied at the executor boundary. |
| `model as done-decider` | Letting the management LM choose the moment to stop iterating and mark a milestone complete. | Refused by v0.4.0 SUBSTRATE + ALM; the environment (not the model) evaluates predicates against the final snapshot before 'done' is spoken. |
