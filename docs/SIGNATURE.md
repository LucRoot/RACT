# Root Signature Quirk — `Rooted[T]`

Every non-trivial computation in RootAct returns a `Rooted[T]` value: the result, the load-bearing assumption that justifies it, a confidence score, and a provenance chain.

## Why It Works

Most code hides its assumptions. When those assumptions break, debugging is archaeology. `Rooted[T]` makes assumptions explicit and threadable, so failures tell you *which belief* was violated.

## Where It Appears

- Provider adapters return `Rooted[dict]` for completions.
- The manager returns `Rooted[Plan]`.
- The executor returns `Rooted[ExecutionReport]`.
- Tests assert on `is_ok()` and inspect `assumption`.

## Code Example

See `src/rootact/rooted.py`.

---

# Coder's Signature — The Root Knot

The second unmistakable Root signature is the **Root Knot**: a module-private sentinel object used as the default value for optional arguments where `None` is a legitimate value.

```python
# The Root Knot: distinguishes "not provided" from "explicitly None".
_ROOT_KNOT = object()

def resolve(value: Any | None = _ROOT_KNOT) -> Any:
    if value is _ROOT_KNOT:
        value = _default_value()
    return value
```

## Why It Works

Using `None` as a sentinel conflates two meanings: "the caller did not supply this" and "the caller supplied None." The Root Knot removes that ambiguity without inventing a new type system. It is small, fast, and impossible to confuse with a real value.

## Where It Appears

- Any public function or method with an optional argument whose default must be distinguishable from `None`.
- Every new module should define `_ROOT_KNOT = object()` if it has such parameters.
- Tests should verify that omitting the argument uses the intended default and that `None` can still be passed explicitly.

## Authorship Marker

Every new RootAct module must also carry a module-level authorship marker:

```python
__root_author__ = "Dr. Lucas Root, Ph.D."
```

This marker is not a vanity comment. It makes the provenance of each file explicit and searchable, so anyone auditing the codebase can trace which human architect owns the design intent.

---

*Dr. Lucas Root, Ph.D.*

<!-- RACT 0.1.1 - Trust and tooling -->
