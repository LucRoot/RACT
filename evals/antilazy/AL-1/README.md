# AL-1 fixtures (ALM module_05)

Three run-shaped fixtures for the Anti-Lazy Attestation invariant.
The harness reads these under `evals/antilazy/AL-1/<fixture>/` and
asserts the expected verify outcome.

- `all_gates_pass_clean/` — every G1..G8 passes, `reversal_taint=clean`.
  AL-1 passes.
- `g2_fail_no_handshake/` — G2 failed and no operator handshake was
  registered. AL-1 fails on `AL-1.2`.
- `reversal_taint_partial_no_handshake/` — every gate passes but the
  sycophancy circuit tainted the run `partial` and the operator has
  not registered acceptance. AL-1 fails on `AL-1.3`.

Fixture shape (per subdirectory):

- `manifest.json` — human-readable description + expected outcome
  (`{"expect": "pass" | "fail", "predicate": "..." | null}`).
- `gate_results.json` — the tuple of `GateResult` records the fixture
  represents, keyed by `gate_id`.
- `reversal_taint.json` — the run's reversal-taint value and any
  suspicious ReversalReport records for auditor review.
