---
layout: default
title: RACT
---

# RACT (Root Agentic Coding Tool)

Model-agnostic, local-first agentic coding with signed provenance and assumption-driven planning.

## Install

```bash
pip install ract
```

Or scaffold a project in one command:

```bash
ract init --template python-package --provider local
```

## What makes RACT different

- **Model-agnostic** — use local models, OpenAI, Anthropic, Z.ai, Moonshot, OpenRouter, or any OpenAI-compatible endpoint.
- **Provenance-anchored artifacts** — every generated file carries a signed rootknot that binds it to the plan step, assumption, and generator that produced it.
- **Assumption-driven programming** — every plan step declares the assumptions that justify it; violated assumptions propagate and trigger targeted re-planning.
- **Milestone-halting recursion** — the loop continues only while measurable progress is being made; it stops on completion, regression, budget exhaustion, or provenance violation.
- **Operator Handshake** — high-risk actions queue for review instead of pausing the loop.

## Quick links

- [Quickstart](QUICKSTART.md)
- [CHANGELOG (v0.5.1)](../CHANGELOG.md)
- [Release notes v0.2.0](RELEASE_NOTES_v0.2.0.md)
- [Provider setup](PROVIDER_SETUP.md)
- [Skill authoring](SKILL_AUTHORING.md)
- [Architecture](ARCHITECTURE.md)
- [Threat model](THREAT_MODEL.md)
- [Provenance](PROVENANCE.md)
- [Events schema](EVENTS.md)
- [Philosophy](PHILOSOPHY.md)
- [Hugging Face Demo](https://huggingface.co/spaces/LucRoot/RACT)

## License

RACT is licensed under the **PolyForm Noncommercial License 1.0.0** — free for personal use, research, education, and noncommercial organizations.

Commercial use requires a separate agreement. See [`COMMERCIAL.md`](../COMMERCIAL.md) for details.

<!-- RACT 0.5.1 -->
