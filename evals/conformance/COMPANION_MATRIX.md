# Companion Matrix

**ALM module_04 (G7).** Every registered provider mapped to the set of providers eligible as its companion. Eligibility (ALM §3.7): different training family, anti-lazy conformance score >= 0.70, schema conformance score >= 0.90. Regenerated idempotently by ``evals/leaderboard/update_companion_matrix.py``.

## Scored providers

| Provider | Family | Anti-lazy | Schema | Eligible-companion count |
|---|---|---|---|---|
| _(none)_ | _(no scored providers)_ | - | - | 0 |

## Eligible pairs

| Primary | Eligible companions |
|---|---|
| _(none)_ | _(no scored providers)_ |

## Notes

- Providers with a missing ``anti_lazy`` or ``schema_compliance`` category are excluded from both roles.
- Training family is a coarse substring match against known identifiers (openai, anthropic, google, gemini, mistral, nvidia, nemotron, deepseek, qwen, minimax); unknown providers are treated as their own singleton family.
- Same-family pairings are refused even when scores clear the floor — shared training regimes share blind spots (ALM §3.7 rejected alternative: same-provider companion).
- The `single_provider_advisory` deployment mode (lateral chain branch D) opts a run into advisory-only companion findings without changing this matrix.

RACT 0.4.0
