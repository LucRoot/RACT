# RootAct Independence from Internal

RootAct is an open, public-facing agentic coding tool. Internal is a proprietary,
context-aware system used to build and operate RootAct. This document records the
boundary between them so the two projects remain legally and architecturally
separate.

## What RootAct Is

RootAct is a small-management-LM agentic coding tool built from scratch against a
public research specification. It is designed to be uploaded to GitHub and
Hugging Face for public distribution under the PolyForm Noncommercial License 1.0.0.

## What Internal Is

Internal is a proprietary, context-aware build orchestration system. It includes:

- A context-aware loop controller with self-review, critique, and reflection.
- A capability-based backend router for local and frontier models.
- Durable build state, outcome memory, and learning journal infrastructure.
- Operator approval queues, distributed tracing, and health dashboards.

Internal is **not** part of RootAct and is **not** included in this repository.

## Separation Rules

1. **No shared code.** RootAct does not import from Internal. Internal may call
   RootAct as a downstream project, but the dependency arrow points only one way.

2. **No shared design intent.** RootAct's architecture is driven by the public
   research specification, not by Internal's proprietary loop-controller or
   context-management patterns.

3. **No proprietary ideas.** Features that are unique to Internal — such as the
   obsessive build-state journal, the Rooted contract validation across
   sub-services, and the operator approval queue — are not replicated in
   RootAct unless they appear in the public research specification.

4. **Public research only.** RootAct is built using publicly available research
   and ideas that are already in the open literature. It does not borrow from
   other open-source projects beyond standard libraries and common architectural
   patterns.

## Build Provenance

RootAct is developed inside Internal for convenience, but every file in this
repository is authored against the RootAct specification. The Coder's Signature
(`Rooted[T]` as the assumption-bearing result type) is a public-facing RootAct
concept that also happens to be a personal coding quirk of Dr. Lucas Root, Ph.D.

## Build Artifacts (`_BUILD/`)

The `_BUILD/` directory contains logs, example banks, spec caches, and loop
outputs produced by the proprietary Internal orchestration loop during development.
It is **not part of the RootAct release**, is excluded from version control via
`.gitignore`, and must not be included in any public distribution archive.

## License

RootAct is released under the PolyForm Noncommercial License 1.0.0: free for
personal use, research, education, and noncommercial organizations. Commercial
use requires a separate agreement with Dr. Lucas Root, Ph.D. See `LICENSE` and
`COMMERCIAL.md` for details.

---

*Dr. Lucas Root, Ph.D.*

<!-- RACT 0.1.1 - Trust and tooling -->
