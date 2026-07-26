# schema_compliance

SUBSTRATE §5.2. The scorer asks: did the provider's response validate
against `PlannedStep`'s closed union on first submission? On second
submission with a corrective prompt naming the offending field? The
category metric is the second-attempt pass fraction.

- **Metric:** `passed / total` where `passed` is the count of intents
  that validated on either attempt.
- **Threshold:** 0.90 (see `src/ract/providers/gate.py`
  `DEFAULT_SCHEMA_COMPLIANCE_THRESHOLD`).
- **Source:** SUBSTRATE §5 (behavioural variance is only observable
  when the vocabulary is invariant).

## Coverage

Each fixture pairs an operator-shaped `intent.txt` with an
`expected.json` naming which action `kind` the plan should validate to
(and, where meaningful, the fields the scorer notices).

The plan target is 40 intents. The v0.4 ship holds representative
coverage across the eight action shapes (`write_file`, `run_tests`,
`read_file`, `search_workspace`, `propose_predicate`, `delete_file`,
`request_handshake`, `emit_event`) with meaningful variations per
shape. Full 40-item expansion tracked in module_04 Flagged gaps.
