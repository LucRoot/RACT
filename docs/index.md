---
layout: default
title: RACT
---

# RACT (Root Agentic Coding Tool)

<p align="center">
  <img src="https://raw.githubusercontent.com/LucRoot/RACT/main/assets/DrLucasRoot-Logo.png" alt="Dr. Lucas Root logo" width="180">
</p>

An Agentic Coding Tool built around a small management LM, by **Dr. Lucas Root, Ph.D.**

RACT keeps the human in the loop while letting a lightweight core manager route work to the right LLM provider. Every operation is anchored to the assumption that justifies it through the `Rooted[T]` signature quirk.

> Want the thinking behind RACT? Dr. Root shares the deeper philosophy — and a free chapter — in the [AI Agent Playbook](https://lucasroot.pro/ai-agent-playbook-thanks).

## Install

```bash
pip install rootact
```

Or scaffold a project in one command:

```bash
rootact init --template python-package --provider local
```

## What makes RACT different

- **Model-agnostic** — use local models, OpenAI, Anthropic, Z.ai, Moonshot, OpenRouter, or any OpenAI-compatible endpoint.
- **Root-Knot-anchored** — every file carries the author's identity markers; unsigned work cannot compound.
- **Self-recursing loop** — the Progress Oracle plans milestones, verifies them, and stops only when the work is done or a regression is detected.
- **Operator Handshake** — high-risk actions queue for review instead of pausing the loop.
- **Anti-rot guardrails** — duplication guard, refactor tax ledger, error-mask detector, novelty budget, Chesterton's Fence, Dead Code Auction, and Legacy Whisperer.

## Quick links

- [Quickstart](QUICKSTART.md)
- [Provider setup](PROVIDER_SETUP.md)
- [Skill authoring](SKILL_AUTHORING.md)
- [Architecture](ARCHITECTURE.md)
- [Audit](AUDIT.md)
- [Philosophy](PHILOSOPHY.md)

## From the author

RACT is the public, standalone expression of ideas I've been developing around assumption-driven programming and model-agnostic agentic tooling. If you want the longer-form thinking behind it — including how to design agentic systems that stay accountable, auditable, and genuinely useful — I share that in my [AI Agent Playbook](https://lucasroot.pro/ai-agent-playbook-thanks). The first chapter is free.

## License

RACT is licensed under the **PolyForm Noncommercial License 1.0.0** — free for personal use, research, education, and noncommercial organizations.

Commercial use requires a separate agreement. See [`COMMERCIAL.md`](../COMMERCIAL.md) for details, or email info@lucasroot.com.
