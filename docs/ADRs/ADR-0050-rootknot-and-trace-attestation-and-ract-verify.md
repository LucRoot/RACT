# ADR-0050: What the Rootknot and the trace chain attest, and `ract verify`

## Status

Proposed (draft by the BUILDER, 2026-10-30, card B-150). Not accepted: only the operator accepts an ADR. It answers the deferral in ADR-0048 D10 ("the Rootknot field ADR is scheduled before `ract verify`") and gives board card B-039 its acceptance.

## Context

A run leaves two kinds of evidence:
- a signed Rootknot beside each file it wrote (S-015b), with a row in `.ract/rootknots.db`;
- a hash-chained event trace for the run (ADR-0015), which also holds the command records (ADR-0048 D10).

Users and reviewers ask one question, "can I trust what this run did?", and today the answer is spread over `ract provenance verify` (one file) and `ract trace verify` (one run). Neither says what the other covers, and neither says what no signature can prove. Decision F's ratification requires that wherever the verdict or `ract verify` speaks, command records are said to be in the trace and not in the Rootknot.

## Decision (proposed)

### D1. What a Rootknot attests

A v4 Rootknot is signed by the session key (and by the run's sandbox and verifier keys for RK-3 and AL-1). It attests one file's bytes as a step wrote them:
- `artifact_digest`: the SHA-256 of the file's bytes on disk when the step wrote them;
- the step that wrote it: `plan_id`, `step_id`, and the `assumption_digest` that justified the step;
- the inputs, by digest: `parent_digests` (the files it derives from), the acceptance suite's `prompt_digest`, the workspace snapshot;
- the environment: `manifest_digest` (the capability manifest, bound to the sandbox key id), `environment_signature`, `predicate_results`;
- the generator: model name and version, session id, and the public key id that resolves the session key.

### D2. What the trace chain attests

The run's event log (`evals/runs/<run_id>/events.jsonl`) is hash-chained from GENESIS. It attests the order and content of every recorded event:
- plans, steps, approvals and refusals, tool calls and their results;
- every command run under tier 3, with the fields of ADR-0048 D10 (argv, executable digest, cwd, environment names, grant digest, rule id, approver, sandbox backend and `enforced`, exit code, output digests).

A command record is in the trace. It is not inside any Rootknot. That stays so until a later ADR adds an optional, signed `commands_digest` field to the payload. That would be a sacred-spine change, and this ADR does not make it.

### D3. What neither attests

No signature proves:
- that a command was safe, or did only what its rule describes (the sandbox claim is `enforced` or `best_effort`, as recorded);
- that a model's claim in its answer is true ("the tests pass" is a claim until a verifier run says so);
- that the operator read what they approved;
- anything about a file no run wrote, or about content after it was changed.

The verdict and `ract verify` say these in plain words; they never print "attested" for any of them.

### D4. `ract verify` (the command B-039 builds)

One offline command checks both kinds of evidence for a range of commits or a run. It reads only local files and opens no socket. Proposed form:

```text
ract verify [--run <run_id>] [<from-commit>..<to-commit>] [--json]
```

What it checks, in order:
1. **Every changed line is attributed.** Each line changed between the two commits is attributed to a recorded step: its file has a Rootknot whose `artifact_digest` matches the bytes at `<to-commit>`.
2. **Each such Rootknot verifies.** RK-1 is always checked; RK-3 and AL-1 where the sidecar carries them, exactly as `ract provenance verify` does for one file.
3. **The run's trace chain verifies from GENESIS,** as `ract trace verify --cold` does.
4. **Each verifier run named in the trace matches the output digest stored in its command record.**

What it prints when only one kind holds:
- "files: signed and verified; trace: broken at event N", or the reverse, never a single "verified".
- Every report ends with: "command records are in the trace; they are not part of the signed Rootknot".
- Exit code: 0 only when everything checked holds. 1 when any check fails. 2 when there is nothing to check (no run, no knots).

### D5. Key custody

| Key | Where | Rotation |
|---|---|---|
| Session key | the user state folder (`keys/<id>.pem`) | one per repository per UTC day (G-237 L4); the day's key is kept, so older knots resolve |
| Sandbox and verifier keys | per run, created in the repository's state folder outside the project and archived at once (ADR-0048 R3) | per run |
| Operator key | the user config folder, encrypted, passphrase at a terminal only | signs grants and handshakes, never a Rootknot |

`ract verify` needs only public keys, and never unlocks anything.

### D6. Failure modes and what is printed

| Case | What `ract verify` (and `ract provenance verify`) says |
|---|---|
| A missing sidecar and no index row | "unsigned": cannot be told apart from a removed record; not evidence of tampering either way (AUD-013) |
| The file changed after signing | the digest does not match: "changed since it was signed", with the step that signed the earlier bytes |
| A rotated or missing public key | the key id is named; "cannot be checked: key <id> not found" (never "invalid") |
| A broken trace chain | the first event whose hash does not chain, and that later events are not trusted |
| A sidecar format RACT does not know | refused at read (RootknotUnknownSidecarFormat), named |

## Alternatives Considered

- **Bind the command records into each Rootknot now:** rejected for this ADR. It changes the signed payload (a sacred-spine change, ADR-0048 D10), and every existing v4 knot would need a reader for two shapes. Open question 3 keeps it for a separate decision.
- **One combined "verified" verdict:** rejected. It hides which evidence failed. A reviewer must see "files verified, trace broken" as two facts (D4).
- **Verify against a server or a public log:** rejected. RACT's evidence is checked offline with local public keys only; nothing leaves the machine (D4, D5).
- **Fail on every unattributed line:** rejected as the default. The operator's own edits are normal; `--strict` is proposed for those who want it (open question 2).

## Consequences

- B-039 gets its acceptance (below). `ract provenance verify` and `ract trace verify` stay as the per-file and per-run commands; `ract verify` composes them.
- The verdict line of a turn keeps saying "signed" only when every changed file's knot verifies (S-015b), and adds the D2 sentence wherever it speaks about commands.

Acceptance line proposed for B-039:

> `ract verify <from>..<to> --run <id>` checks every changed line's Rootknot and the run's trace chain offline. It prints which held and which did not, never one "verified" for both. It ends with the D2 sentence. Its exit code is 0 only when all hold. Tests cover each row of D6.

## Commands quoted here that exist today

```console
ract provenance verify <file>
ract trace verify <run_id>
ract trace verify --cold <run_id>
ract doctor --tier3
```

## Open questions for the operator

1. **Range or run first.** Should `ract verify` take a commit range first (attribution) or a run first (the trace)? This draft takes both and needs at least one.
2. **Lines no step wrote.** Should a changed line with no Rootknot fail `ract verify`, or be reported as "not written by RACT"? The operator's own edits are normal. This draft proposes reporting them and failing only with `--strict`.
3. **`commands_digest`.** Is the optional signed `commands_digest` field in the Rootknot payload wanted at all (a sacred-spine ADR)? Or is the trace chain the lasting home of command records?
4. **Day keys.** Do day keys need a published list (a key ring file) so a reviewer on another machine can check old knots? Or is "copy the user state folder's `keys/`" enough for v0.6?
