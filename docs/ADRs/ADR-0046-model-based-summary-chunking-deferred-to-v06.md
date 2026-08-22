# ADR-0046 -- Model-based SUMMARY chunking (Bonsai council) deferred to v0.6

## Status

Accepted 2026-08-21. Authored under the v0.5.1 spec-completeness
pipeline (`docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`, module_05).
Supersedes the implicit "will land in v0.5.x" reading of the
Memory Discipline spec's §Chunk Overflow item 2 (Summary chunking
via a Bonsai council model). Complements the AST-deterministic
SUMMARY fallback shipped in the same module.

## Context

The Memory Discipline spec
(`docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`) §Chunk Overflow names
two alternative strategies for oversize chunks:

1. **Semantic sub-chunking** at logical AST boundaries (for/while/if/
   try) — landed in this module (module_05); previously a self-
   declared Flagged gap 2 in `src/ract/memory/chunker.py`.
2. **Summary chunking** — invoke a small local council model
   (Bonsai-scale, `bge-small`-adjacent) to produce a one-line
   representation of the region, and store the summary in place of
   the raw body.

Alternative (1) shipped in this module. Alternative (2) — the
model-invoked path — did not. The 2026-08-21 source-spec audit
(`_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md` finding 4,
severity MEDIUM) surfaced the placeholder in `src/ract/memory/chunk.py`
lines 272-279 (`format_chunk(SUMMARY, ...)` returned
`"summary unavailable"` + `summary_pending=True` when no provider
was supplied). Module_05 replaces that placeholder with a
deterministic summary derived from the AST (signature + first-line
docstring + control-flow region counts + external-call name list up
to 10), so the body is never `"summary unavailable"` on the shipped
code path. The `provider` hook is preserved unchanged so a v0.6
Bonsai integration can slot in without another API change.

The 2026-08-21 pre-build audit surfaced concretely why a Bonsai
integration cannot land in v0.5.1 without inventing the dependency:

- Grep across `src/ract/` for
  `bonsai|council|local_model|small_model|LocalModel|SmallModel` returns
  four files:
  - `src/ract/cli.py` — cites `ract.experimental.council_self_audit`,
    an external operational surface, not a summarizer.
  - `src/ract/dead_code_auction.py` — dead-code exception list
    comments naming an external council loop.
  - `src/ract/experimental/provider_cost_index.py` — the string
    `"bonsai"` appears as a key in a static cost-lookup table with
    zero call sites in a shipping code path (a per-token cost stub,
    not a provider adapter).
  - `src/ract/memory/embedding.py` — hosts `bge-small-en-v1.5`,
    which is an **embedding** model (384-dim vector output), not a
    **summarizer** (natural-language output).
- No provider client, no adapter class with a `summarize(chunk)`
  method, no config surface loading one.
- No shipping runtime call site that would invoke such a
  summarizer.

Inventing a Bonsai dependency in v0.5.1 would be the primitive-
without-wiring trap (Ox Alpha adversarial review 2026-08-21 §1),
pre-committed for a point release. The honest move is to ship the
AST-deterministic path — which is genuinely useful, deterministic,
and requires no new dependencies — and defer the model-based path
to v0.6, exactly as ADR-0043 defers DSPy and ADR-0044 defers LeWM.

## Decision

Defer the Bonsai-council-model-based SUMMARY generation path to
v0.6. Ship v0.5.1 with:

- **AST-deterministic SUMMARY** as the `format_chunk(SUMMARY, ...)`
  default body producer (module_05): signature + first-line
  docstring + control-flow region counts + up-to-ten external call
  targets. Deterministic, no model call, no external dependency.
  `summary_pending` becomes `False` when the deterministic summary
  produces a non-empty body.
- **Provider hook preserved.** The `provider` parameter on
  `format_chunk` still accepts an object exposing `summarize(chunk)`;
  when supplied, provider output takes precedence over the
  deterministic body. This is the v0.6 slot for a Bonsai adapter
  (or any other summarizer). No shipping caller passes a provider
  today.

Every consumer-facing surface describes the deferral explicitly:

- `CHANGELOG.md` `[0.5.1]` — the "Not yet shipped in v0.5.1
  (deferred to v0.6)" section reframes the SUMMARY-format bullet:
  the AST-deterministic body IS shipped; the Bonsai council model
  is the deferred piece.
- `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` — §Chunk Overflow
  item 2 (Summary chunking) callout notes AST-deterministic path
  shipped v0.5.1 (module_05); model-based path deferred to v0.6
  per ADR-0046.
- `docs/ROADMAP.md` — v0.6 backlog entry for Bonsai-council
  summarizer cross-referencing this ADR.

## Rationale

Implementing a model-based SUMMARY summarizer at v0.5.1 would
require, at minimum:

1. **Introduce a summarizer model surface.** Not present anywhere
   in `src/ract/`. Would require either a new local-inference
   adapter (llama.cpp / candle / ONNX runtime on a bundled small
   model), an OpenRouter / provider client for a small hosted model,
   or a stubbed protocol that is honest about being unusable
   (rejected — see ADR-0043 rationale on stub surfaces).
2. **Author or ship model weights.** Bonsai-scale local weights
   (`bge-small`-adjacent, per spec) are ~130-500MB per model. RACT
   currently ships only embedding weights on-demand via
   `RACT_EMBED_MODEL_ROOT` env var, not summarizer weights. A
   packaging + license + Windows-ARM64 wheel review is required.
3. **Wire the summarizer into the retrieve primitive.** The
   `format_chunk(SUMMARY, provider)` hook exists; the missing piece
   is the shipping caller that constructs a provider and passes it.
   That caller lives at the retrieve-composition layer, which today
   never passes a provider.
4. **Prove non-degradation.** A model-based summary that
   hallucinates would harm retrieval fidelity. A regression harness
   comparing summary-based vs full-body retrieval quality (needle
   test, coherence test, adherence test) would be required before
   shipping the summarizer.

That is multi-week work with a new dependency stack. The v0.5.1
spec-completeness pipeline's operator directive is "get it right",
not "invent a Bonsai integration"; the audit's finding is that the
placeholder is a lie, not that a model is missing. Replacing
`"summary unavailable"` with a deterministic AST-derived body
closes the honesty gap AND provides a genuinely useful summary
today; a model-based summarizer becomes a v0.6 slot-in that
supersedes the deterministic body when the operator wires a
provider.

## Alternatives considered

1. **Ship a model-based summarizer in v0.5.1.** Rejected. Cost is
   multi-week (dependency, weights, packaging, wiring, regression
   harness); scope is not what the operator directive names
   ("close the audit's docs-honesty gap"). Ox Alpha adversarial
   review 2026-08-21 §1 identified pre-commit of unwired subsystems
   as the primitive-without-wiring trap; adding a Bonsai adapter
   with no summarizer-quality regression would be the same trap.
2. **Leave `"summary unavailable"` in place until v0.6.** Rejected.
   The audit surfaced the placeholder as a MEDIUM defect; the
   placeholder is a lie the retrieve cascade emits every time a
   caller asks for SUMMARY format without a provider (which today
   is every caller). The deterministic body closes the honesty gap
   in v0.5.1 without waiting for the model integration.
3. **Ship a stub summarizer** that echoes the signature or returns
   a fixed message. Rejected on the same principle as ADR-0043
   alternative (4): a stub is a runtime lie in different packaging.
   The deterministic AST-derived body is not a stub — it carries
   genuine signal (control-flow shape + external calls) that a
   caller can reason about.
4. **Use OpenRouter as the summarizer provider.** Rejected for
   v0.5.1 as a shipping default. RACT's retrieve path today does
   not hold provider credentials; adding a per-chunk network call
   would break the offline-first + deterministic-hash properties
   the semantic index relies on (`chunk_id` is
   `sha256(file, name, kind, locator, content_hash)` — including a
   network-generated summary in `body` would make `content_hash`
   depend on remote model responses). A local model can preserve
   determinism (weights + inputs → outputs); a remote call cannot
   in general. If an operator wires an OpenRouter provider via the
   preserved `provider` hook, the summary flows through, but v0.5.1
   ships no such caller by default.
5. **Use `bge-small-en-v1.5` (the embedding model already shipped)
   as the summarizer.** Rejected as a category error. `bge-small` is
   an embedding model — 384-dim vector output — not a natural-
   language generator. It cannot produce a summary body.

## Consequences

- **v0.5.1 does not ship a Bonsai council model, a summarizer
  adapter, summarizer weights, or a shipping caller that passes a
  provider to `format_chunk(SUMMARY, ...)`.** The AST-deterministic
  summary produces the SUMMARY body on every call path in v0.5.1.
- **The `provider` parameter on `format_chunk` is the v0.6 slot.**
  Any adapter object with a `summarize(chunk) -> str` method plugs
  in; provider output takes precedence over the deterministic body
  when supplied. This ADR pins that surface as the extension point.
- **The Memory Discipline spec's §Chunk Overflow item 2 is now
  formally scoped to v0.6 for the model-based path only.** The
  AST-deterministic path is shipped and lives under alternative
  (1) — semantic sub-chunking — with §Chunk Overflow item 2
  providing a compressed body for oversize regions.
- **Deterministic bodies keep `chunk_id` stable** because the
  summary body is a pure function of the source region. A future
  Bonsai integration that produces the SUMMARY body via a model
  will flip `content_hash` (and therefore `chunk_id`); this is
  expected — the v0.6 pipeline that wires the summarizer will
  re-issue the semantic index during rollout.
- **Reopens when v0.6 pipeline includes Bonsai council adoption.**
  At that point this ADR gets a "Superseded by ADR-XXXX" header
  and the Status flips.

## References

- Memory Discipline spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  §Chunk Overflow item 2 (Summary chunking).
- Source-spec audit finding:
  `_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md` §7 finding 4
  (SUMMARY chunking fallback — MEDIUM severity).
- Spec-completeness pipeline: `docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`
  §4 module_05 brief.
- Ox Alpha adversarial review authorizing the honest-implement-vs-defer
  discipline: `_BUILD/ract_v0.5.1_spec_completeness/ox_alpha_reviews/pipeline_challenge_2026-08-21.md`
  §1.
- Companion deferral ADRs (same pattern): ADR-0043 (DSPy),
  ADR-0044 (LeWM).
- Shipped code: `src/ract/memory/summary.py` (AST-deterministic
  summarizer), `src/ract/memory/chunk.py::format_chunk`
  (SUMMARY branch replacement).
- Test gate:
  `tests/unit/test_summary_chunk_deterministic.py` (no
  `"summary unavailable"` on shipped Python path).

## Flagged gaps (v0.6+)

- The v0.6 pipeline that ships the Bonsai council summarizer should
  bump `content_hash` deliberately (re-index) and document the
  transition — because the SUMMARY body will flow through a model
  instead of the AST, the `chunk_id` for oversize sub-chunks will
  change even for source that has not changed.
- A summarizer-quality regression harness (needle / coherence /
  adherence over a summary-vs-full-body corpus) should land BEFORE
  the summarizer is wired as a shipping caller.
- Non-Python AST sub-chunker paths (TypeScript / Rust / Go) ship in
  v0.5.1 as blank-line heuristic fallbacks with explicit
  `sub_chunk_method` metadata. Full AST boundary support for
  TS/Rust/Go remains v0.6 alongside the five deferred language
  chunkers (Java / Kotlin / C# / C / C++).
