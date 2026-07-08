# Rooted by Dr. Lucas Root, Ph.D.

# The Philosophy Behind RACT

RACT is not just another CLI wrapper around a language model. It is a deliberate answer to a question I've been asking for years:

> How do we build agentic software that stays accountable, auditable, and genuinely useful — without pretending the human is optional?

## Every plan is Rooted

In RACT, every plan and every result carries three things: an **assumption**, a **confidence**, and **provenance**. This is the `Rooted[T]` idea. It means the system is never allowed to say "trust me" without also saying "here is what I assumed, how sure I am, and where this came from."

When a model hallucinates, the damage is usually not the wrong answer. The damage is the wrong answer delivered with false certainty. `Rooted[T]` makes uncertainty a first-class citizen.

## The Root Knot

Every file RACT touches carries a small identity marker: `_ROOT_KNOT = object()`. This is partly a coder signature, but it is also a loop invariant. If the recursion loop ever produces an artifact without the knot, the loop stops immediately rather than compounding unsigned work.

The Root Knot is my answer to a world where generated code can proliferate faster than it can be reviewed. It forces a moment of human accountability at the boundary between machine output and project truth.

## Model-agnostic by design

RACT does not lock you to one provider. You can run it against a local `llama-server`, a cheap frontier endpoint, or a cloud API. The goal is to give you ownership of your pipeline — your data, your models, your costs.

This matters because the real lock-in risk in AI tooling is not the code; it is the habit. Once you delegate thinking to a single vendor's interface, you stop noticing how much you have outsourced. RACT keeps the interface yours.

## Anti-rot guardrails

Most agentic tools optimize for speed. RACT optimizes for *sustainable* speed. The duplication guard, refactor tax ledger, error-mask detector, novelty budget, Chesterton's Fence, Dead Code Auction, and Legacy Whisperer are not features for their own sake. They are answers to the question: what does a codebase look like after an agent has been working on it for six months?

The answer, without guardrails, is usually a mess. The answer with RACT is a codebase that still makes sense to a human.

## The longer story

If this line of thinking interests you, I explore it in much more depth in my [AI Agent Playbook](https://lucasroot.pro/ai-agent-playbook-thanks). The first chapter is free, and subscribers get behind-the-scenes notes on builds like RACT, early drafts, and the occasional rant about tools that pretend to be magic.

No pressure. Use RACT however it helps you build better software. The philosophy is there if you want it.

— Dr. Lucas Root, Ph.D.
