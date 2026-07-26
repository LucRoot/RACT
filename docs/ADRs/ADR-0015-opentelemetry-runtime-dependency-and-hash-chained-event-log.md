# ADR-0015 — OpenTelemetry runtime dependency + hash-chained event log as the durable trace

- Status: Accepted
- Date: 2026-07-26
- Deciders: RACT v0.4.0 substrate rebuild pipeline
- Supersedes: none
- Related: ADR-0011 (worktree-per-step), ADR-0012 (capability manifest +
  OS-enforced sandbox), ADR-0013 (Pydantic runtime dependency),
  ADR-0014 (closed action union + conformance gate).

## Context

In v0.3 the run's story was a summary — `RunReporter` collected a small
dictionary of counts and timings and rendered it as text/HTML/markdown.
A summary is what you show a manager; SUBSTRATE §6 pointed out that
what an architect needs is a **trace**: an append-only, replayable,
forkable, diffable, hash-chained record of every load-bearing decision
the run made. The v0.3 report was derived data — but the source data
lived only in the executor's memory, so replay, fork, diff, and
regression-test-emission were impossible.

Two coupled decisions fell out of that framing:

1. Every executor path must emit into a **closed** event vocabulary; the
   log is the source of truth; the reporter becomes a projection.
2. The log must mirror through OpenTelemetry so a run's story is
   portable to any conformant collector (Jaeger, Tempo, honeycomb,
   otel-collector, etc.) — and so the RACT-specific JSONL is not the
   only readable form of the trace.

## Decision

Two coupled decisions:

1. **`opentelemetry-api`, `opentelemetry-sdk`, and
   `opentelemetry-exporter-otlp-proto-http` are promoted to
   `[project.dependencies]` in `pyproject.toml`, pinned as
   `>=1.20,<2`.** The exporter package name is the current stable
   OTLP-HTTP export path; the version range is permissive so v0.4 does
   not ossify against a specific patch. OTLP export is opt-in per run
   via `otlp_endpoint` in `ract.yaml`; a run with no endpoint
   configured still writes the JSONL log — the runtime dependency is
   only actually loaded when the exporter is installed. This means CI
   without an OTLP sink still runs the module's tests green.

2. **The closed `EventKind` vocabulary + hash-chained JSONL at
   `evals/runs/<run_id>/events.jsonl` is the durable substrate; the
   `RunReporter` is a projection over that log.** Each event carries a
   SHA-256 of its canonical JSON payload and a `prev_hash` reference to
   the tip hash at append time; a bit-flip anywhere in the middle of
   the log surfaces as a mismatch on load. The vocabulary is closed —
   adding a kind is a schema-version bump in `docs/EVENTS.md`. The
   trace CLI verbs `ract trace replay|fork|diff|to-test` operate on
   that log.

## Rejected alternatives

- **Keep the derivative `RunReporter` as the source of truth (SUBSTRATE
  §6.1 baseline).** Rejected — the reporter can only summarise what
  the executor happened to hand it in-memory; replay, fork, diff, and
  regression-test emission are all impossible on that shape. The
  reporter's shape *is* the failure mode this ADR closes.

- **Custom span format that ignores the OpenTelemetry GenAI Semantic
  Conventions.** Rejected — the conventions cover exactly the shape
  RACT emits (tasks, actions, agent teams, memory, artifact tracking).
  A private span format would be portable to no collector; SUBSTRATE
  §6.2 explicitly names the conventions as the target.

- **Synchronous OTLP without a fallback exporter.** Rejected — an OTLP
  endpoint outage would brick runs. The JSONL log is the always-on
  substrate; OTLP is a mirror.

- **Hash-chain the log with something lighter than SHA-256.** Rejected
  as premature optimization — SHA-256 over a run's ~10³ to ~10⁵ events
  is measured in seconds, not minutes. The hash-chain latency is not
  the bottleneck; keeping the chain a well-understood primitive is
  worth more than a marginal cycle count.

- **Skip the redaction profile.** Rejected — `prompt.sent` payloads
  can carry operator content. The writer supports a shallow
  pattern-scrub loaded from `ract.yaml` (off by default; opt-in for
  shared logs). Deeper entity-aware redaction is v0.5 hardening.

## Consequences

- New event kinds require a `docs/EVENTS.md` schema-version bump and
  an addition to `LEGAL_EVENT_KINDS` in `ract.trace.events`; the
  friction is intentional.
- OTLP export is opt-in. The runtime dep is declared but only imported
  when `OtlpExporter.install()` is called; a run with no endpoint
  configured pays no OpenTelemetry cost beyond the import-time
  resolution.
- The `RunReporter` migration removes its direct-executor-state
  ownership: it reads the JSONL log and computes counts / timings /
  halt cause. Existing reporter tests migrate to feeding synthetic
  event logs; behavioural signature preserved.
- `EmitEventAction` (module_04) now has a real sink — the closed
  null-sink gap from module_04's flagged gaps is closed.

## Follow-ups (v0.5 hardening)

- Live OTLP-collector integration test in CI (module_05 ships the
  exporter but does not prove it end-to-end against a live collector;
  CI runs the JSONL path only).
- Deeper redaction (entity-aware masking; per-provider prompt-content
  parsers).
- Provider-side `prompt.sent` emit for the live adapters (module_05
  wires the conformance harness; live-provider CLI path is module_08
  work).

## Reference sources

- SUBSTRATE spec §6 (Substrate Layer 5: The Trace is the Product) and
  §11 signals 9, 10, 11.
- Temporal durable-execution model, event-history replay:
  `https://docs.temporal.io/`.
- OpenTelemetry Python API/SDK/OTLP exporter public repository:
  `https://github.com/open-telemetry/opentelemetry-python`.
- OpenTelemetry GenAI Semantic Conventions SIG (multi-agent
  conventions covering tasks, actions, agent teams, memory, artifact
  tracking):
  `https://github.com/open-telemetry/semantic-conventions`.
- OpenHands SDK per-iteration tracing pattern:
  `https://github.com/All-Hands-AI/OpenHands`.
- JSON Schema Draft 2020-12 for the canonical event payload
  serialization: `https://json-schema.org/`.

<!-- ADR-0015 — module_05 v0.4.0 substrate rebuild -->
