# The Philosophy Behind RACT

RACT is not just another CLI wrapper around a language model. It is a deliberate answer to a question I've been asking for years:

> How do we build agentic software that stays accountable, auditable, and genuinely useful — without pretending the human is optional?

## Every plan is Rooted

In RACT, every plan and every result carries three things: an **assumption**, a **confidence**, and **provenance**. This is the `Assumed[T]` idea. It means the system is never allowed to say "trust me" without also saying "here is what I assumed, how sure I am, and where this came from."

When a model hallucinates, the damage is usually not the wrong answer. The damage is the wrong answer delivered with false certainty. `Assumed[T]` makes uncertainty a first-class citizen.

## The Rootknot

Every file RACT writes carries a signed provenance capability called a **Rootknot**. It records the plan step, assumption, generator, parent artifacts, and artifact digest, and it can be cryptographically verified. If the recursion loop ever produces an artifact whose Rootknot is missing or invalid, the loop halts with a provenance violation rather than compounding unsigned work.

The Rootknot is the boundary between machine output and project truth: a verifiable answer to the question "where did this come from?"

## Model-agnostic by design

RACT does not lock you to one provider. You can run it against a local `llama-server`, a cheap frontier endpoint, or a cloud API. The goal is to give you ownership of your pipeline — your data, your models, your costs.

This matters because the real lock-in risk in AI tooling is not the code; it is the habit. Once you delegate thinking to a single vendor's interface, you stop noticing how much you have outsourced. RACT keeps the interface yours.

## Anti-rot guardrails

Most agentic tools optimize for speed. RACT optimizes for *sustainable* speed. The duplication guard, refactor tax ledger, error-mask detector, novelty budget, Chesterton's Fence, Dead Code Auction, and Legacy Whisperer are not features for their own sake. They are answers to the question: what does a codebase look like after an agent has been working on it for six months?

The answer, without guardrails, is usually a mess. The answer with RACT is a codebase that still makes sense to a human.

## v0.4.0-rc1: environment as thorough verifier

Every previous version of RACT still let the model decide when it was
done. The management LM chose the moment to stop iterating, chose which
tests counted, and chose whether to skip a hard case with `pytest.skip`
and call the run "passing". The guardrails caught the loudest mistakes,
but the *decision authority* still lived with the model.

v0.4.0-rc1 moves that authority out of the model and into the
environment. Two combined pipelines land in this tag:

- **Substrate.** Every plan step runs in its own git worktree, inside an
  OS-enforced sandbox derived from a signed capability manifest. Every
  model action is a member of a closed Pydantic union validated at the
  provider boundary. Every run emits a hash-chained event log the
  environment (not the model) reads to decide T1 completion: *every
  required predicate evaluates true against the final snapshot*.
  `Rootknot` gains an `environment_signature` (Invariant RK-3) — the
  origin the sidecar attests shifts from author to environment.

- **Anti-Lazy Module (ALM).** Eight gates run at the pre-commit boundary:
  held-out predicates the model never sees, mutation-kill against the
  test suite, patch differentiation, coverage delta, test-integrity AST
  diff, symbol-graph under-edit, companion red-team from a distinct
  provider, and effort reconciliation. A sycophancy circuit forces
  evidence on suspicious reversals. `Rootknot` gains a third signature
  (`antilazy_signature`) held by an ALM-verifier key distinct from the
  sandbox key. Invariant AL-1 (Anti-Lazy Attestation) raises the
  verification bar: `strict=True` verifies only when every gate passed
  (or its handshake was approved) AND the run's `reversal_taint` is
  clean.

The naming convention matters. The tag is `v0.4.0-rc1` — the `rc1`
suffix is honest about the fact that the ALM code is new and the
combined shape warrants a release-candidate cycle before a `v0.4.0`
final tag. Substrate alone would have shipped as `v0.4.0`; substrate
plus ALM ships as a candidate.

The word "attested" appears in a run report only when all three
signatures land. The word "done" is no longer the model's to say.

## The longer story

If this line of thinking interests you, I explore it in much more depth in my [AI Agent Playbook](https://lucasroot.pro/ai-agent-playbook-thanks). The first chapter is free, and subscribers get behind-the-scenes notes on builds like RACT, early drafts, and the occasional rant about tools that pretend to be magic.

No pressure. Use RACT however it helps you build better software. The philosophy is there if you want it.

— Dr. Lucas Root, Ph.D.

<!-- RACT 0.4.0-rc1 -->
