# ADR-0040 - T8 PROMPT_DRIFT termination cause

## Status

Accepted (v0.5.1, module_04).

## Context

Module_02 (v0.5.1) extended the Rootknot canonical bytes with three
new fields -- ``workspace_digest``, ``prompt_digest``, ``run_id`` --
and populated ``AcceptanceSuite.prompt_digest`` via
``IntentCompiler.compile``. This bound each signed artifact to the
operator's compile-time intent text.

Module_02 only staged the field. Nothing at runtime *enforced* that
the loop kept authoring against the intent that was compiled. Over
a long run (the "200-compaction" scenario in DEEPSEEK_REVIEW_5 §G3),
an injected prompt could arrive through poisoned tool output, an
IDE-side hijack of the intent variable, or a compaction that pulled
in a mutated intent buffer. The gates (G1-G8) run against the
*compiled* suite, so a subtly redirected run can look clean:

- generator signature verifies (the payload is well-formed);
- environment signature verifies (the sandbox accepted the write);
- all gates pass (structural laziness is absent);
- assumption registry is happy (no violations).

The RUN has drifted into a different domain, but the trust chain
gives no evidence because no signed field commits to the ORIGINAL
prompt.

## Decision

Add termination cause ``T8 PROMPT_DRIFT`` to
``ract.core.loop.TerminationCause`` (the existing enum previously
carried T1-T7). Wire a per-iteration hook in
``ract.loop_controller.LoopController`` that:

1. Computes ``compute_prompt_digest(current_intent_text)`` at the
   start of every iteration, BEFORE the iteration runs its planner
   / executor.
2. Compares the digest bit-exact against
   ``state.suite.prompt_digest``.
3. On match, continues normally.
4. On mismatch:
   - Emits a ``run.completed`` event with payload
     ``{"reason": "T8_PROMPT_DRIFT", "expected_prompt_digest":
     "<hex>", "actual_prompt_digest": "<hex>", "iteration": <n>,
     "run_id": "<hex>"}``.
   - Forces the on-disk workspace back to
     ``state.last_known_good_workspace`` (the snapshot recorded
     before the drift was observed). The rollback compensator uses
     the same primitive the transaction path uses in module_02.
   - Halts the loop with
     ``TerminationCause.PROMPT_DRIFT`` and surfaces a
     CLI-visible diagnostic line.

Backward-compat: when ``state.suite.prompt_digest is None`` (a
pre-v0.5.1 suite compiled by an older ``IntentCompiler``), the
per-iteration hook LOGS a WARN and skips the check. This preserves
the historical behaviour of running against a v0.5.0-compiled suite
so a partial upgrade window does not brick every existing run.

Legitimate intent evolution -- operator refines the spec mid-run --
is supported via a new CLI verb: ``ract intent recompile <run_id>
[--intent-file <path> | --intent-text <str>]``. The verb:

1. Requires an operator key (either marker file
   ``.ract/operator.key`` OR environment variable
   ``RACT_OPERATOR_KEY``); refuses with a clear error when both are
   absent.
2. Loads the current suite from the run's ``suite.json``.
3. Compiles a new ``AcceptanceSuite`` from the new intent text; its
   ``prompt_digest`` is populated by ``IntentCompiler.compile``.
4. Signs the recompile action as a Rootknot v4 whose signed payload
   commits to the new suite as artifact + carries the new
   ``prompt_digest`` + preserves the original ``run_id``.
5. Appends a single line to
   ``.ract/runs/<run_id>/suite_chain.jsonl`` recording
   ``{timestamp_ns, prompt_digest, suite_digest,
   rootknot_signature}``.

The loop controller compares the current intent against the LATEST
suite in the chain (not just the initial ``suite.json``). Attacker
intent change WITHOUT the recompile signature never reaches the
chain -- T8 fires. Operator-signed recompile appends a suite version
and the loop continues under it.

## Rejected alternatives

1. **Cryptographic prompt-hash tied only to the Rootknot canonical
   bytes.** Module_02 already binds ``prompt_digest`` into the signed
   canonical bytes. That closes the *provenance* leak (a Rootknot
   cannot claim it was authored under a different intent than it
   actually was) but does NOT close the *drift* leak (the loop can
   still author fresh Rootknots against a mutated intent, each one
   internally consistent, and only cross-Rootknot comparison reveals
   the shift). T8 is the runtime enforcement that closes the
   drift leak; module_02's field is what makes T8 possible.
2. **Semantic drift detector (F2 in the review chain).** A layered
   semantic check (embedding similarity + safety-property invariance)
   would catch injections that leave the raw prompt intact but
   redirect the model via poisoned tool outputs. This is v0.6+ work
   per the review chain's defense-in-depth ordering; T8 covers the
   canonical raw-text substitution path, which is the bulk of the
   attack surface.
3. **Silently rollback without a termination cause.** Rejected --
   the loop halting silently would hide the security event from the
   operator's post-run inspection. T8 fires as a top-level
   termination cause + emits a ``run.completed`` event with
   evidence, giving operators the same audit surface T1-T7 already
   provide.
4. **Replace the suite on drift instead of halting.** Rejected --
   silent replacement is exactly what the attacker wants. Suite
   evolution goes through the operator-signed recompile path or it
   does not happen.

## Consequences

- ``TerminationCause`` gains one enum member. Every test that
  enumerates the closed vocabulary (see
  ``tests/property/test_loop_termination.py`` +
  ``tests/unit/test_termination_cause_t8.py``) picks up the new
  member automatically.
- ``LoopState`` gains two optional fields (``current_intent_text``
  and ``last_known_good_workspace``); both default to ``None`` so
  existing constructors keep working.
- ``.ract/operator.key`` becomes a security-load-bearing marker
  file. Operators generate it once (any random 32-byte key
  suffices; the key is compared for presence + used as a signing
  input for the recompile Rootknot). The env-var fallback
  ``RACT_OPERATOR_KEY`` supports CI environments where the marker
  file is inconvenient.
- The suite-chain file ``.ract/runs/<run_id>/suite_chain.jsonl``
  is append-only. A recompile NEVER truncates or replaces prior
  entries.

## References

- ``_BUILD/ract_v0.5.1_external_review/DEEPSEEK_REVIEW_5.md`` §"G3
  deeper dive" (verbatim reviewer design).
- ``_BUILD/ract_v0.5.1_external_review_response/module_02.md``
  (staging that made T8 possible).
- ``_BUILD/ract_v0.5.1_external_review_response/module_04.md``
  (build fragment for this ADR).
- ``docs/RACT_v0.5.1_EXTERNAL_REVIEW_RESPONSE_SPEC.md`` §4
  module_04.
- ``src/ract/core/loop.py`` (``TerminationCause.PROMPT_DRIFT`` +
  ``check_t8``).
- ``src/ract/core/suite_chain.py`` (append-only chain).
- ``src/ract/cli.py`` (``ract intent recompile`` verb).
