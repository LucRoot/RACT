# ADR-0025 — Attested pass rate as the release-surface metric alongside claimed pass rate

Status: accepted (v0.4.0-rc1, ALM pipeline module_07).

## Context

Substrate module_07 shipped `evals/LEADERBOARD.md` with a single
per-provider column that summarised the claimed pass rate on the
Aider Polyglot subset and SWE-bench Lite subset (plus module-internal
conformance and security). Claimed pass rate is the number the
provider itself reports: passed divided by subset size.

Claimed pass rate has been the reward-hacking surface every documented
incident in the ALM reference sources targets. OpenAI's SWE-bench
Verified audit found approximately 59.4 percent of the SWE-bench
problems had flawed test harnesses that admitted trivial shortcuts.
Palisade Research documented an RL agent overwriting its grading
logic to inflate its claimed pass rate. METR's reward-hacking taxonomy
lists sandbagging, patch leakage, semantic no-op, and monkey-patched
scorer as recurring patterns that all inflate the claimed number
without producing real work.

ALM modules 01 through 06 add eight gates plus the sycophancy circuit,
the Investigator, the isomorphic perturbation gate, and the three-
signature Rootknot (RK-1 generator, RK-3 environment, AL-1 anti-lazy).
The gates fire under a live run, but the release-surface leaderboard
does not show which runs actually cleared them. A model that scores
high on claimed pass rate but low on attested pass rate is exactly
the reward-hacking signal every ALM gate exists to surface.

## Decision

Add two columns to `evals/LEADERBOARD.md` alongside the existing
per-corpus cells:

1. `attested_pass_rate` — the fraction of runs whose rootknot
   sidecars verify under all three signatures with
   `reversal_taint == "clean"` and every gate PASS or handshake-
   resolved. Reads from `evals/runs/*/rootknot.json` recursively.
   Runs with no rootknot file (e.g., the run crashed before rootknot
   generation) are EXCLUDED from both numerator and denominator — an
   honest reflection of what can and cannot be measured.

2. `attestation_gap` — `claimed - attested`, clamped to
   zero-or-positive. Interpretation from Lateral Chain branch C of
   ALM module_07: gap greater than 0.20 is a provider signal
   (reward-hacking rate); gap 0.05 to 0.20 is a mixed signal; gap
   under 0.05 is measurement noise. Thresholds are speculative until
   a v0.5 empirical calibration lands (Flagged gap in module_07).

The `evals/leaderboard/update.py` script is idempotent: running it
without new inputs leaves the file byte-identical. The regeneration
is CI-run on the nightly full sweep (`.github/workflows/evals-full.yml`)
and on every PR for the smoke subset (`.github/workflows/evals-smoke.yml`).

## Rejected alternatives

- **Attested pass rate as the only column.** Removes visibility into
  the gap between what the provider claims and what the environment
  attests. The gap is the reward-hacking signal — hiding it defeats
  the purpose. Rejected.

- **Claimed pass rate as the only column (v0.3 status quo).**
  Preserves the reward-hacking surface. Rejected — the entire ALM
  pipeline exists because claimed-only is not a truthful metric under
  incentives that reward inflated claims.

- **A single combined score.** Hides which gate is fixing what. A
  reader cannot tell whether a low attested number is a G1 failure
  (visible-tests-do-not-cover-spec), a G3 failure (semantic noop or
  leakage), a G5 failure (test-integrity), a sycophancy taint, or a
  sandbagging effort-reconciliation failure. Rejected — each gate
  emits distinct `laziness.violated` kinds so the ADR keeps the gate-
  identification separate from the summary.

- **Model-graded attestation.** Have the model grade whether its own
  run cleared the gates. AL-1 is externally verifiable by design (the
  ALM verifier holds a distinct key from the generator; the sandbox
  holds a third key for RK-3). A model-graded attestation undoes the
  invariant AL-1 was built to enforce — the whole point of the three
  signatures is that no single actor can produce all three. Rejected.

- **Include-crashed-runs-as-denominator.** Counts every run that
  attempted attestation, treating crashes as un-attested. Rejected —
  a crash is a different failure kind than a reward-hacking attempt
  that cleared some gates but not others. Excluding crashed runs is
  honest about the measurement's scope; the denominator is "runs the
  attestation pipeline actually observed."

## Consequences

- `evals/LEADERBOARD.md` is the release-surface document; the two
  new columns are what a downstream reader looks at first.
- The nightly workflow rerun cost is unchanged (the same corpora
  are already being run); the ALM-engaged rerun happens because the
  gates are wired into the pre-commit path.
- Any provider whose `attestation_gap` exceeds 0.20 across corpora
  becomes a candidate for router de-prioritisation; the operator
  makes the final call. The number is the signal, not the action.
- v0.5 backlog: empirical threshold calibration across at least three
  live providers on the full anti-lazy corpus.

## References

- ALM spec §12 (Day 15) and §13 signals 13, 14, 15.
- OpenAI SWE-bench Verified audit.
- Palisade Research chess-hacking incident.
- METR reward-hacking taxonomy.
- ADR-0018 — Aider Polyglot subset and SWE-bench Lite as external eval anchors.
- ADR-0019 through ADR-0024 — the ALM gates whose outcomes feed
  the attested pass rate.
