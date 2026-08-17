"""Author-name-free module identity attestation.

Load-time attestation that a module was imported through the shipped
distribution rather than substituted at runtime. Each module registered
here holds a fresh :class:`object` — a *knot* — whose identity is
unique to that import. Callers may pass their knot across trust
boundaries; the receiving side checks membership against the process's
registry of known knots.

The mechanism is deliberately identity-based (``is``) rather than
value-based: an attacker who replaces a module cannot forge the
identity of the object bound at the original module's import time,
because :class:`object` instances have no publicly forgeable id.

No author names, byline strings, or descriptive tokens participate.
The knot is an opaque process-local reference. See
``docs/RACT_v0.3.1_HARDENING_SPEC.md`` for the surrounding hardening
context.
"""

from __future__ import annotations


def _module_knot() -> object:
    """Return a fresh, opaque identity object.

    Each call returns a new object. A module records the return value
    once at import time and treats it as that module's identity.
    """
    return object()


# Process-local registry mapping qualified module name to its knot.
# Populated at module import via :func:`register_module_knot`.
MODULE_KNOT_REGISTRY: dict[str, object] = {}


def register_module_knot(module_name: str, knot: object) -> None:
    """Record ``knot`` as the identity for ``module_name``.

    Called at the top of each participating module. Safe to call more
    than once per name (later calls overwrite, which supports test
    reload scenarios).
    """
    MODULE_KNOT_REGISTRY[module_name] = knot


def verify_module_knot(observed: object, expected: object) -> bool:
    """Return ``True`` iff ``observed`` and ``expected`` are the same object."""
    return observed is expected


def is_registered_knot(observed: object) -> bool:
    """Return ``True`` iff ``observed`` is a knot in the registry."""
    for knot in MODULE_KNOT_REGISTRY.values():
        if observed is knot:
            return True
    return False


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)
