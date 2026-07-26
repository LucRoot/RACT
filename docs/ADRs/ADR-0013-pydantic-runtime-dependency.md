# ADR-0013: Promote Pydantic v2 to a Runtime Dependency

## Status

Accepted

## Context

Through v0.3, ``pydantic`` appeared only in
``[project.optional-dependencies].dev`` — the test suite and a handful
of optional developer features used it, but the shipping runtime did
not. The v0.4 SUBSTRATE spec's Non-negotiable invariant #3 requires
that any new runtime dependency arrive with an ADR that considers the
rejected alternatives.

Module_03's ``CapabilityManifest`` (``src/ract/security/manifest.py``)
is a structured schema with cross-field validation, sub-model
composition, and a canonical serialization used as a stable digest for
downstream modules (module_05 event log, module_06 extended Rootknot).
The schema is authored as YAML for operator readability and consumed as
JSON for digesting; both endpoints need the same model definitions.

Module_04's typed action union (Pydantic discriminated union across
provider adapters) will reuse the same model layer without another
promotion event — this ADR is the single Pydantic-runtime-dep event
for the v0.4 substrate rebuild.

## Decision

``pydantic>=2.0`` moves from ``[project.optional-dependencies].dev`` to
``[project].dependencies``. The dev-only extras list drops the
duplicate entry.

The dependency is v2 (``pydantic>=2.0``), matching the version the dev
suite already exercised. No pinning below the ``2.0`` floor — Pydantic
v2 maintains API stability for the model / validator surface this ADR
consumes.

The Pydantic import is confined to ``src/ract/security/`` and
downstream security-adjacent modules. The rest of the substrate
(``ract.core.*``, ``ract.executor.*``) continues to use
``dataclasses`` — the promotion is intentional and bounded.

## Rejected alternatives

- **Continue with dataclasses.** The manifest is nested, has cross-
  field validators (``NetworkPolicy.deny_default`` must be ``True``,
  ``TierPolicy.allow_tier_3`` gated on the compile-time constant), and
  needs a canonical JSON serialization the digest layer trusts.
  Reimplementing that with ``dataclasses`` + hand-rolled validators
  duplicates well-established primitives, adds a class of hand-rolled-
  validator defects Pydantic already avoids, and produces a bespoke
  serialization no downstream tool recognizes. Rejected.
- **Roll bespoke validation.** The v0.3 ``handshake_registry`` did
  something similar (``if self.status not in {...}: raise ValueError``);
  extending that pattern across the manifest's ten sub-fields is O(N)
  hand-rolled code with no upside over Pydantic. Rejected — this is
  exactly the case Pydantic exists for.
- **Add a lighter model library (``msgspec``, ``attrs``).** ``msgspec``
  is faster but less mature on the discriminated-union axis
  module_04 will need. ``attrs`` does not derive JSON schemas the way
  the module_05 event schema will consume. Rejected — the operational
  cost of a second serialization library later would exceed Pydantic's
  cost today.
- **Import Pydantic lazily under a ``try / except ImportError`` guard.**
  Would let the security module still ship the type declarations while
  making the dependency optional. Rejected because a security module
  whose enforcement layer is optionally installable is a security
  regression, not a feature. The dependency is a first-class runtime
  requirement.

## Consequences

Positive:

- The manifest gains type-safe cross-field validation and JSON-schema
  derivation for free.
- Module_04's typed action union has a home for its models the second
  it lands — no second-round dep-promotion friction.
- The dev-only extras list shrinks by one entry, so the split between
  "runtime deps" and "dev deps" is honest.

Negative / follow-ups:

- **Install footprint grows.** Pydantic v2 pulls
  ``pydantic-core`` (a compiled Rust extension) and
  ``annotated-types``. On the shipping ``requires-python = ">=3.11"``
  target, both have wheels for every supported platform. Users on
  exotic architectures may face a sdist build; the doc footprint
  argument is bounded.
- **Import time.** Pydantic v2 imports faster than v1 but is still
  measurable. The security module imports Pydantic at module load; the
  rest of the substrate does not. Import-time budget is the same order
  as the existing ``cryptography`` import.
- **Model migrations.** Any future incompatible change to the manifest
  bumps the ``version`` field and requires a migration path (see
  module_03 depth-chain "Core dependency" clause). Pydantic makes
  version-bumped model coexistence straightforward; the migration path
  is a v0.5+ concern.

## References

- ``docs/RACT_v0.4.0_SUBSTRATE_SPEC.md`` — Non-negotiable invariant #3.
- Pydantic v2 documentation: ``https://docs.pydantic.dev/``.
- ADR-0012 (capability manifest as allowlist enforced at the OS layer)
  — the primary consumer of this dependency.

<!-- RACT 0.4.0 -->
