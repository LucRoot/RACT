from __future__ import annotations


"""Operator Handshake Registry.

High-risk milestones never pause the loop. Instead, the MilestoneOracle returns a
"handshake" verdict, the loop continues with other work, and the milestone is
recorded here for operator review. The operator can approve, reject, or defer
each handshake after the fact.

**v0.4 substrate change (SUBSTRATE §3.5).** High-risk steps under the
transactional executor still record here — but resolution now blocks the
step's *commit* at the git layer, not just the plan-level milestone
acknowledgement. See ``ract.executor.loop.SubstrateLoop._finalize``: a
step whose ``handshake_ids`` include any pending id returns
``BLOCKED_ON_HANDSHAKE`` and leaves its worktree intact for operator
inspection; the parent snapshot does not advance and no dependent step
can commit past it. The blast radius is bounded by git.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ract.workspace_state import check_state_path


@dataclass(frozen=True)
class HandshakeItem:
    """A single operator-handshake request.

    ``depends_on`` names other handshake ids whose resolution this
    handshake waits on. It is a display / diagnostic aid; the git-layer
    block enforced by ``SubstrateLoop`` reads the ``handshake_ids`` on
    each step spec and cross-references ``pending()``.
    """

    id: str
    description: str
    acceptance: str
    timestamp: str
    status: str = "pending"
    metadata: dict[str, Any] | None = None
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"pending", "approved", "rejected", "deferred"}:
            raise ValueError(f"Invalid handshake status: {self.status}")


_FIELDS = {
    "id",
    "description",
    "acceptance",
    "timestamp",
    "status",
    "metadata",
    "depends_on",
}
_TEXT_FIELDS = ("id", "description", "acceptance", "timestamp", "status")
_STATUSES = {"pending", "approved", "rejected", "deferred"}


def _item_ok(raw: object) -> bool:
    """True for an item of the shape ``_save`` writes; others are ignored."""
    if not isinstance(raw, dict) or not set(raw) <= _FIELDS:
        return False
    if any(not isinstance(raw.get(name), str) for name in _TEXT_FIELDS):
        return False
    if raw["status"] not in _STATUSES:
        return False
    if raw.get("metadata") is not None and not isinstance(raw["metadata"], dict):
        return False
    deps = raw.get("depends_on", [])
    return isinstance(deps, list) and all(isinstance(d, str) for d in deps)


def _approval_digest(item: HandshakeItem) -> str:
    """What the operator approved: the item's id, text and time."""
    fields = [item.id, item.description, item.acceptance, item.timestamp]
    return hashlib.sha256(json.dumps(fields).encode("utf-8")).hexdigest()


class HandshakeRegistry:
    """Persist and manage operator handshakes for a project.

    LR:: ``.ract/handshakes.json`` is in the workspace, so a cloned
    repository can ship one, with items already marked ``approved``
    (B-075, S-035). The file still records the handshakes, but an approval
    widens a manifest only when this machine recorded it: ``update_status``
    writes a mark in the user state directory holding the approved item's
    digest, and ``widen_manifest_for`` checks the mark against the item.

    A shipped item can also carry an id RACT uses later (B-082). ``add``
    writes a request mark the same way, and every decision about an id
    (``update_status``, ``blocks_commit``, ``is_approved``) reads the item
    with this machine's request mark, or the last item with that id when
    none has one. A shipped copy ahead of it can neither take the approval
    nor keep the step blocked.
    """

    def __init__(self, project_dir: Path | str) -> None:
        self.project_dir = Path(project_dir)
        self.registry_path = self.project_dir / ".ract" / "handshakes.json"

    def _approvals_dir(self) -> Path:
        from ract.core.keys import _default_state_dir
        from ract.undo_backup import repository_key

        key = repository_key(self.project_dir)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return _default_state_dir() / "handshakes" / digest

    def _mark(self, milestone_id: str, kind: str) -> Path:
        """This machine's ``approved`` or ``requested`` mark for an id."""
        name = hashlib.sha256(milestone_id.encode("utf-8")).hexdigest()[:32]
        return self._approvals_dir() / f"{name}.{kind}"

    def _read_mark(self, milestone_id: str, kind: str) -> str | None:
        """The digest this machine recorded for an id, or None.

        Mark storage is these two methods only (B-088), the way ``_load`` and
        ``_save`` are for the registry file, so a registry kept in memory
        overrides them together.
        """
        mark = self._mark(milestone_id, kind)
        if mark.is_symlink() or not mark.is_file():
            return None
        try:
            return mark.read_bytes()[:128].decode("ascii").strip()
        except (OSError, UnicodeDecodeError):
            return None

    def _write_mark(self, milestone_id: str, kind: str, digest: str | None) -> None:
        """Record *digest* as this machine's mark for an id; None removes it."""
        mark = self._mark(milestone_id, kind)
        if digest is None:
            mark.unlink(missing_ok=True)
            return
        check_state_path(mark)  # B-213: never through a link
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(digest, encoding="ascii")

    def _marked(self, item: HandshakeItem, kind: str) -> bool:
        return self._read_mark(item.id, kind) == _approval_digest(item)

    def _approved_here(self, item: HandshakeItem) -> bool:
        """True only for this machine's mark signed by the pinned operator key (R2)."""
        return signed_approval_holds(
            item.id, self._read_signed_mark(item.id), _approval_digest(item)
        )

    def unsigned_reason(self, milestone_id: str) -> str | None:
        """Why an approved item still blocks, and what to do; None when it does not (W5)."""
        from ract.policy.operator_key import pinned

        item = self.current(milestone_id)
        if item is None or item.status != "approved" or self._approved_here(item):
            return None
        if pinned() is None:
            return (
                f"{milestone_id} was approved without the operator's signature; "
                "`ract policy init --guided` creates the key, then approve again"
            )
        return (
            f"{milestone_id} was approved without a signature that holds now (another "
            "key, expired, or the item changed); approve it again: "
            f"`ract handshakes approve {milestone_id}`"
        )

    def approval_state(self, item: HandshakeItem) -> str:
        """``signed``, ``unsigned`` (shown, unlocks nothing) or ``none`` (B-111, R2)."""
        if self._approved_here(item):
            return "signed"
        if self._marked(item, "approved") or self._read_signed_mark(item.id):
            return "unsigned"
        return "none"

    def _read_signed_mark(self, milestone_id: str) -> dict[str, Any] | None:
        mark = self._mark(milestone_id, "approved.sig")
        if mark.is_symlink() or not mark.is_file():
            return None
        try:
            if mark.stat().st_size > 4096:
                return None
            data = json.loads(mark.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[handshakes] the signed approval cannot be read: {exc}", flush=True)
            return None
        return data if isinstance(data, dict) else None

    def _current_index(
        self, items: list[HandshakeItem], milestone_id: str
    ) -> int | None:
        """The item that stands for *milestone_id* (B-082), or None.

        The one this machine requested, else the last one with the id.
        """
        found = [i for i, item in enumerate(items) if item.id == milestone_id]
        for i in found:
            if self._marked(items[i], "requested"):
                return i
        return found[-1] if found else None

    def current(self, milestone_id: str) -> HandshakeItem | None:
        """The handshake item that stands for *milestone_id*, or None."""
        items = self.entries()
        index = self._current_index(items, milestone_id)
        return items[index] if index is not None else None

    def is_approved(self, milestone_id: str) -> bool:
        """True when the id's item is approved and this machine recorded it."""
        item = self.current(milestone_id)
        return (
            item is not None and item.status == "approved" and self._approved_here(item)
        )

    def _load(self) -> list[dict[str, Any]]:
        from ract.untrusted_file import UntrustedFileRefused, read_untrusted

        try:
            raw = read_untrusted(self.registry_path, root=self.project_dir)
        except UntrustedFileRefused:
            return []
        if raw is None:
            return []
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if _item_ok(item)]

    def _save(self, items: list[HandshakeItem]) -> None:
        check_state_path(self.registry_path)  # B-213: never through a link
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for item in items:
            raw = asdict(item)
            # asdict turns None metadata into {"metadata": None}; strip it to keep
            # the on-disk format clean and backward-compatible.
            if raw.get("metadata") is None:
                raw.pop("metadata", None)
            # An empty depends_on carries no information; strip it so v0.3
            # readers see the exact on-disk shape they expect.
            if not raw.get("depends_on"):
                raw.pop("depends_on", None)
            else:
                raw["depends_on"] = list(raw["depends_on"])
            payload.append(raw)
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def entries(self) -> list[HandshakeItem]:
        """Return all handshake items."""
        items: list[HandshakeItem] = []
        for raw in self._load():
            # ``depends_on`` is v0.4 and may be absent from v0.3 registry
            # files; normalize the deserialization so old files still load.
            raw = dict(raw)
            deps = raw.pop("depends_on", ())
            if isinstance(deps, list):
                deps = tuple(str(d) for d in deps)
            items.append(HandshakeItem(depends_on=tuple(deps), **raw))
        return items

    def pending(self) -> list[HandshakeItem]:
        """Return only pending handshake items."""
        return [item for item in self.entries() if item.status == "pending"]

    def add(
        self,
        milestone_id: str,
        description: str,
        acceptance: str,
        metadata: dict[str, Any] | None = None,
        depends_on: tuple[str, ...] = (),
    ) -> HandshakeItem:
        """Record a new pending handshake."""
        items = self.entries()
        item = HandshakeItem(
            id=milestone_id,
            description=description,
            acceptance=acceptance,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="pending",
            metadata=metadata,
            depends_on=tuple(depends_on),
        )
        items.append(item)
        self._save(items)
        self._write_mark(item.id, "requested", _approval_digest(item))
        # module_05: emit at the request site so the log is complete
        # regardless of who called ``add`` (compiler group requests,
        # handshake CLI, MilestoneOracle escalations).
        _emit_handshake_event(
            "handshake.requested",
            item,
            reason="",
        )
        return item

    # ------------------------------------------------------------------
    # v0.4: git-layer blocking
    # ------------------------------------------------------------------

    def blocks_commit(self, handshake_ids: tuple[str, ...] | list[str]) -> list[str]:
        """Return the subset of ``handshake_ids`` that are currently pending.

        A non-empty result means the caller (a ``SubstrateLoop`` step) must
        return ``BLOCKED_ON_HANDSHAKE`` rather than commit — SUBSTRATE §3.5.
        Empty result means the step is free to commit its worktree.
        """
        items = self.entries()
        blocked = []
        for hid in handshake_ids:
            index = self._current_index(items, hid)
            if index is None:
                continue
            item = items[index]
            # B-111 (R2): an approval without the operator's signature was not
            # given with authority, so it blocks as a pending one does.
            if item.status == "pending" or (
                item.status == "approved" and not self._approved_here(item)
            ):
                blocked.append(hid)
        return blocked

    def widen_manifest_for(self, manifest_widen: object, milestone_id: str) -> object:
        """Apply an approved handshake's widen to the run's capability manifest.

        SUBSTRATE §4.3 + module_03 step 6. A handshake widens the manifest
        for the specific action and only for the duration of the approved
        step; the sandbox re-reads the (widened) manifest at the next
        ``enter`` call. This method is the harness-facing hook: it takes
        the base manifest (typed ``object`` so the module has no import-
        time dependency on ``ract.security``) and returns a widened copy.

        The widen is bounded by the manifest's own ``yolo_widen`` field —
        an approved handshake cannot lift a policy the manifest did not
        pre-declare could be widened. Tier 3 remains denied even under
        an approved handshake (compile-time hard-off; see ADR-0012).
        """
        # Local import to avoid the security → handshake → security cycle.
        from ract.security.manifest import CapabilityManifest

        if not isinstance(manifest_widen, CapabilityManifest):
            raise TypeError(
                "widen_manifest_for expected a CapabilityManifest; got "
                f"{type(manifest_widen).__name__}"
            )
        # Verify the handshake is approved, and approved on this machine
        # (a mark in the user state directory), before applying any widen.
        if not self.is_approved(milestone_id):
            return manifest_widen
        # Apply the widen: union filesystem read + write, union network hosts.
        widened = manifest_widen.model_copy(
            update={
                "filesystem": manifest_widen.filesystem.model_copy(
                    update={
                        "read": manifest_widen.filesystem.read
                        + manifest_widen.yolo_widen.extra_read,
                        "write": manifest_widen.filesystem.write
                        + manifest_widen.yolo_widen.extra_write,
                    }
                ),
                "network": manifest_widen.network.model_copy(
                    update={
                        "allow_hosts": manifest_widen.network.allow_hosts
                        + manifest_widen.yolo_widen.extra_hosts,
                    }
                ),
            }
        )
        return widened

    def update_status(
        self, milestone_id: str, status: str, *, signer: Any = None
    ) -> HandshakeItem:
        """Approve, reject, or defer a handshake by milestone id.

        B-111 (ADR-0048 R2): an approval unlocks only with *signer*, the
        unlocked operator key, which signs the id, the approved digest and an
        expiry. Without it the approval is recorded and shown, and unlocks
        nothing.
        """
        if status not in {"approved", "rejected", "deferred"}:
            raise ValueError(f"Invalid status transition: {status}")
        items = self.entries()
        i = self._current_index(items, milestone_id)
        if i is None:
            raise KeyError(f"Handshake not found: {milestone_id}")
        item = items[i]
        items[i] = HandshakeItem(
            id=item.id,
            description=item.description,
            acceptance=item.acceptance,
            timestamp=item.timestamp,
            status=status,
            metadata=item.metadata,
            depends_on=item.depends_on,
        )
        self._save(items)
        _record_approval_mark(self, items[i], signer)
        # module_05: emit at the resolve site so the log carries
        # every terminal transition.
        _emit_handshake_event("handshake.resolved", items[i], reason="")
        return items[i]


def _record_approval_mark(
    registry: HandshakeRegistry, item: HandshakeItem, signer: Any = None
) -> None:
    """Record on this machine that the operator approved *item*, or clear it.

    With *signer*, the mark also holds the operator's signature (R2),
    written atomically; a decision other than approve removes it.
    """
    import os

    digest = _approval_digest(item) if item.status == "approved" else None
    registry._write_mark(item.id, "approved", digest)
    signed = registry._mark(item.id, "approved.sig")
    if digest is None or signer is None:
        signed.unlink(missing_ok=True)
        return
    record = sign_approval(item.id, digest, signer)
    check_state_path(signed)  # B-213: never through a link
    signed.parent.mkdir(parents=True, exist_ok=True)
    temp = signed.with_name(signed.name + ".tmp")
    temp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(temp, signed)


APPROVAL_DAYS = 30
_APPROVAL_DOMAIN = b"ract-handshake-approval/1\n"


def _approval_message(milestone_id: str, digest: str, expires: str) -> bytes:
    from ract.canonical import dumps_jcs

    return _APPROVAL_DOMAIN + dumps_jcs(
        {"id": milestone_id, "digest": digest, "expires": expires}
    )


def sign_approval(milestone_id: str, digest: str, signer: Any) -> dict[str, Any]:
    """The signed approval record: id, digest, expiry, key id, signature (R2).

    *signer* is ``(key_id, private_key)``, the operator key unlocked at the
    terminal.
    """
    import base64
    from datetime import timedelta

    key_id, private_key = signer
    expires = (datetime.now(timezone.utc) + timedelta(days=APPROVAL_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    signature = private_key.sign(_approval_message(milestone_id, digest, expires))
    return {
        "format": "ract-handshake-approval/1",
        "id": milestone_id,
        "digest": digest,
        "expires": expires,
        "key_id": key_id,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def signed_approval_holds(
    milestone_id: str, record: dict[str, Any] | None, digest: str
) -> bool:
    """True when *record* is this approval, unexpired, signed by the pinned key."""
    import base64

    from ract.policy.operator_key import pinned

    if not record or record.get("format") != "ract-handshake-approval/1":
        return False
    if record.get("id") != milestone_id or record.get("digest") != digest:
        return False
    key = pinned()
    if key is None or record.get("key_id") != key.key_id:
        return False
    try:
        expires = datetime.strptime(
            str(record["expires"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        signature = base64.b64decode(str(record["signature"]), validate=True)
    except (KeyError, ValueError):
        return False
    if datetime.now(timezone.utc) >= expires:
        return False
    return key.verify(
        signature, _approval_message(milestone_id, digest, str(record["expires"]))
    )


def _emit_handshake_event(kind: str, item: HandshakeItem, *, reason: str) -> None:
    """Emit a handshake lifecycle event to the run's event log.

    module_05 (SUBSTRATE §6.3). Local import so this module has no
    top-level dependency on ``ract.trace``.
    """
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            kind,  # type: ignore[arg-type]
            {
                "milestone_id": item.id,
                "status": item.status,
                "description": item.description,
                "reason": reason,
            },
        )
    except Exception:  # noqa: BLE001
        pass


# RACT 0.1.1 - Trust and tooling
