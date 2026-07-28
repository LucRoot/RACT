# Assumption-Bound Values — `Assumed[T]`

Every non-trivial computation in RACT returns an `Assumed[T]` value: the result, the load-bearing assumption that justifies it, a confidence score, and a provenance chain.

## Why It Works

Most code hides its assumptions. When those assumptions break, debugging is archaeology. `Assumed[T]` makes assumptions explicit and threadable, so failures tell you *which belief* was violated.

## Where It Appears

- Provider adapters return `Assumed[dict]` for completions.
- The manager returns `Assumed[Plan]`.
- The executor returns `Assumed[ExecutionReport]`.
- Tests assert on `is_ok()` and inspect `assumption`.

## Code Example

See `src/ract/rooted.py`.

---

# Provenance Capability — The Rootknot

The second unmistakable RACT signature is the **Rootknot**: a signed provenance capability attached to every artifact the loop writes.

```python
from ract.core.rootknot import Rootknot

rootknot = Rootknot.sign(
    artifact_path="src/foo.py",
    plan_step="extract validation logic",
    assumption="validation is side-effect free",
    generator="loop",
    parent_artifacts=["src/orders.py"],
)
assert rootknot.verify()
```

## Why It Works

A file on disk tells you what the code is; a Rootknot tells you where it came from. It binds the artifact to the plan step, assumption, generator, parents, and digest that produced it, and it can be verified without the full tool.

## Where It Appears

- Every artifact written by the executor carries a Rootknot sidecar.
- The loop halts with `TerminationCause.PROVENANCE_VIOLATION` if a Rootknot is missing or invalid.
- Tests verify signing, tamper detection, and key rotation survival.

---

*Dr. Lucas Root, Ph.D.*

<!-- RACT 0.2.0 -->
