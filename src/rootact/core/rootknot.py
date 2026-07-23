"""Signed provenance capability for every artifact produced by the recursion loop."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from rootact.core.keys import SessionKey, verify
from rootact.core.types import Digest, PlanId, StepId, make_plan_id, make_step_id


@dataclass(frozen=True)
class GeneratorRef:
    """Identity of the generator that authored an artifact."""

    model_name: str
    model_version: str
    session_id: bytes
    public_key_id: Digest


@dataclass(frozen=True)
class Rootknot:
    """Provenance capability for every artifact produced by the recursion loop.

    A Rootknot is a signed statement that binds an artifact to
    (a) the plan step that produced it,
    (b) the assumption that justified the step,
    (c) the generator that authored it, and
    (d) the upstream artifacts it derives from.

    The signature is ed25519 over the canonical serialization of
    every field except ``signature`` itself.
    """

    plan_id: PlanId
    step_id: StepId
    assumption_digest: Digest
    generator: GeneratorRef
    parent_digests: tuple[Digest, ...]
    workspace_path: str
    artifact_digest: Digest
    created_at_ns: int
    signature: bytes

    def canonical_bytes(self) -> bytes:
        """Return a deterministic serialization of all fields except signature."""
        payload = {
            "plan_id": self.plan_id.hex(),
            "step_id": self.step_id.hex(),
            "assumption_digest": self.assumption_digest.hex(),
            "generator": {
                "model_name": self.generator.model_name,
                "model_version": self.generator.model_version,
                "session_id": self.generator.session_id.hex(),
                "public_key_id": self.generator.public_key_id.hex(),
            },
            "parent_digests": [d.hex() for d in self.parent_digests],
            "workspace_path": self.workspace_path,
            "artifact_digest": self.artifact_digest.hex(),
            "created_at_ns": self.created_at_ns,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sign(self, key: SessionKey) -> Rootknot:
        """Return a new Rootknot signed with ``key``."""
        return Rootknot(
            plan_id=self.plan_id,
            step_id=self.step_id,
            assumption_digest=self.assumption_digest,
            generator=self.generator,
            parent_digests=self.parent_digests,
            workspace_path=self.workspace_path,
            artifact_digest=self.artifact_digest,
            created_at_ns=self.created_at_ns,
            signature=key.sign(self.canonical_bytes()),
        )

    def verify(self, pubkey: bytes) -> bool:
        """Verify the stored signature against ``pubkey``."""
        return verify(self.canonical_bytes(), self.signature, pubkey)


def make_rootknot(
    key: SessionKey,
    workspace_path: str,
    artifact_digest: Digest,
    assumption_digest: Digest,
    model_name: str = "unknown",
    model_version: str = "0",
    plan_id: PlanId | None = None,
    step_id: StepId | None = None,
    parent_digests: tuple[Digest, ...] = (),
) -> Rootknot:
    """Construct and sign a Rootknot for ``workspace_path``."""
    session_id = key.public_key_id()[:16]
    generator = GeneratorRef(
        model_name=model_name,
        model_version=model_version,
        session_id=session_id,
        public_key_id=key.public_key_id(),
    )
    return Rootknot(
        plan_id=plan_id or make_plan_id(),
        step_id=step_id or make_step_id(),
        assumption_digest=assumption_digest,
        generator=generator,
        parent_digests=parent_digests,
        workspace_path=workspace_path,
        artifact_digest=artifact_digest,
        created_at_ns=time.time_ns(),
        signature=b"",
    ).sign(key)


# RACT 0.2.0
