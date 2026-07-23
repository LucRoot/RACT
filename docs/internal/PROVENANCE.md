# RootAct Independence

RootAct is an open, public-facing agentic coding tool. This document records
the boundary between RootAct and the author's proprietary internal tooling so
the two remain legally and architecturally separate.

## What RootAct Is

RootAct is a small-management-LM agentic coding tool built from scratch against
a public research specification. It is designed for public distribution under
the PolyForm Noncommercial License 1.0.0.

## Separation Rules

1. **No shared code.** RootAct does not import from any proprietary system.
2. **No shared design intent.** RootAct's architecture is driven by the public
   research specification, not by any proprietary loop-controller or
   context-management patterns.
3. **No proprietary ideas.** Features that are unique to the author's internal
   tooling are not replicated in RootAct unless they appear in the public
   research specification.
4. **Public research only.** RootAct is built using publicly available research
   and ideas that are already in the open literature. It does not borrow from
   other open-source projects beyond standard libraries and common
   architectural patterns.

## Build Provenance

Every file in this repository is authored against the RootAct specification.
The Coder's Signature (`Rooted[T]` as the assumption-bearing result type) is a
public-facing RootAct concept that also happens to be a personal coding quirk
of Dr. Lucas Root, Ph.D.

## Build Artifacts (`_BUILD/`)

The `_BUILD/` directory contains logs, example banks, spec caches, and loop
outputs produced during development. It is **not part of the RootAct release**,
is excluded from version control via `.gitignore`, and must not be included in
any public distribution archive.

## License

RootAct is released under the PolyForm Noncommercial License 1.0.0: free for
noncommercial use, with commercial licensing available separately. See
`LICENSE` and `COMMERCIAL.md`.
