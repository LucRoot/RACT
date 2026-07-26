# ADR-0014 — Closed Pydantic action union with per-provider conformance gate

- Status: Accepted
- Date: 2026-07-26
- Deciders: RACT v0.4.0 substrate rebuild pipeline
- Supersedes: none
- Related: ADR-0004 (threat model), ADR-0005 (provider capability routing),
  ADR-0010 (acceptance predicates), ADR-0012 (capability manifest +
  OS-enforced sandbox), ADR-0013 (Pydantic runtime dependency).

## Context

v0.3's plan schema was versioned but the actions a model could propose
were open-typed — validation ran at the plan-schema level only. Two
consequences fell out of that shape:

1. **Behavioural variance across providers was invisible.** A model
   that answered with a plausible-looking shell string bypassed no
   validator until the executor tried to run it; a model that emitted
   an unknown tool name landed in a fall-through branch that was
   effectively a silent widening of the interface.
2. **Model-of-the-week routing had no eval.** ``ProviderRouter``
   accepted any configured slot. There was no evidence surface that
   said "this provider actually clears the tool discipline the manifest
   assumes." SUBSTRATE §5.1 named this as the root cause of half the
   destructive-agent incidents catalogued in §4.1.

Module_04's job is to close both gaps by making the tool interface
**invariant** and gating router registration on a passing eval per
provider.

## Decision

Two coupled decisions:

1. **The set of actions the model may propose is a closed Pydantic v2
   discriminated union** (``ract.core.actions.Action``), discriminated
   on ``kind``. The eight members are ``WriteFileAction``,
   ``RunTestsAction``, ``ReadFileAction``, ``SearchWorkspaceAction``,
   ``ProposePredicateAction``, ``DeleteFileAction``,
   ``RequestHandshakeAction``, and ``EmitEventAction``. Every member
   sets ``model_config = ConfigDict(extra="forbid", frozen=True)`` so
   a stray field never grants an unmeant capability. Adding a new
   ``kind`` requires an ADR — the friction is the feature. See
   ``docs/RACT_v0.4.0_SUBSTRATE_SPEC.md`` §5.

2. **``ProviderRouter`` refuses to route to a provider without a recent
   passing conformance report.** ``ract conformance run --provider
   <name>`` produces
   ``evals/conformance/results/<provider>-<date>.json``; the router
   gate (``ract.providers.gate.check_provider_gate``) reads the newest
   report and admits the provider iff every category clears its
   threshold and the timestamp is inside ``max_age_days`` (default 14).
   Thresholds: schema compliance ≥ 0.90 on second attempt, tool
   discipline ≥ 0.95, refusal fidelity ≥ 1.00 (boolean by design).

## Rejected alternatives

- **Open-typed action space validated only at the plan schema (v0.3
  baseline).** Rejected because it *is* the failure mode the module
  exists to close. The plan schema constrains the container; the union
  constrains the payload the container carries.

- **Provider-declared capability strings.** A provider claims
  ``supports_tool_use=true`` and the router trusts it. Rejected
  because the claim is unverifiable at registration time; SUBSTRATE §5.1
  named "self-reported capability" as the same failure mode as
  "provider-declared shape" in every incident it catalogued. The
  conformance report is verifiable evidence, not a claim.

- **Model-of-the-week routing with no eval.** Route to whichever
  provider is trending; measure nothing. Rejected — this is the v0.2/
  v0.3 baseline and it is what SUBSTRATE §5 exists to displace.

- **Wrap the ``instructor`` library instead of hand-writing the
  converters.** Rejected on dependency-surface grounds. ``pydantic``
  is already a runtime dep (ADR-0013); adding ``instructor`` would
  drag in another SDK layer that hides the wire format from the
  reviewer. The three converters are 60 lines each and every line is
  auditable.

- **Open the refusal-fidelity threshold from 1.00 to (say) 0.90.**
  Rejected — refusal is boolean by design. A model that bypasses one
  named-incident case cannot be trusted to refuse the next one. The
  corpus size (15 items) is deliberately unforgiving; expansion of
  the corpus is the correct hardening lever, not softening the
  threshold. (Lateral chain branch C.)

## Consequences

- New action kinds require an ADR and a schema-converter update; the
  friction is intentional. See module_04's plan for the extension
  contract.
- Providers without a structured-output primitive fall through to the
  JSON-Schema converter and score worse on average; the gate refuses
  them by default. Operators can lower thresholds locally in
  ``ract.yaml``, but the ship defaults are the same as the master spec.
- The v0.3 ``ProviderRouter`` remains the low-level slot registry;
  ``check_provider_gate`` is the layer that decides whether a slot
  is admissible. The two are wired together as a substrate primitive;
  module_08 (or a later integration commit) wires the gate into the
  shipped CLI's provider-selection flow.

## Follow-ups (v0.5 hardening)

- Expand each corpus category to its plan-headline count (schema
  compliance 40, tool discipline 20, refusal fidelity 15+).
- Add a live-provider integration path that reads API keys from
  the environment and runs the corpus against real endpoints; today
  only ``--provider fake`` is CI-exercisable.
- ``ract.yaml`` schema key for gate thresholds is designed but not
  yet loaded by the CLI; ``check_provider_gate`` accepts a
  ``GateConfig`` today, and a follow-up commit wires the yaml
  overrides at the call site.

## Reference sources

- SUBSTRATE spec §5 (Substrate Layer 4: Model Conformance) and §11
  signals 7 and 8.
- OpenAI Structured Outputs public documentation
  (``https://platform.openai.com/docs/guides/structured-outputs``).
- Anthropic tool-use public documentation
  (``https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview``).
- Pydantic v2 discriminated unions
  (``https://docs.pydantic.dev/latest/concepts/unions/``).
- JSON Schema Draft 2020-12 (``https://json-schema.org/``).
- Aider Polyglot benchmark (behavioural-variance shape;
  ``https://github.com/Aider-AI/aider``).
- OpenHands V1 SDK (routing downstream of eval;
  ``https://github.com/All-Hands-AI/OpenHands``).
- SUBSTRATE §4.1 named incidents (used in the refusal-fidelity
  corpus).
- v0.3 ``ProviderRouter`` / ``FallbackChain``
  (``src/ract/providers/router.py``, ``src/ract/router_fallback.py``).

<!-- ADR-0014 — module_04 v0.4.0 substrate rebuild -->
