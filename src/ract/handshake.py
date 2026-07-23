__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _get_queue_path() -> Path:
    return Path(os.environ.get("RACT_HANDSHAKE_QUEUE", "handshake_queue.jsonl"))


def raise_request(question: str, context: Dict[str, Any]) -> str:
    """Append a pending entry to the JSONL queue. Returns the request ID."""
    request_id = str(uuid.uuid4())
    entry = {
        "id": request_id,
        "question": question,
        "context": context,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "answer": None,
        "signer": None,
        "answered_at": None,
    }
    queue_path = _get_queue_path()
    with open(queue_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return request_id


def list_pending() -> List[Dict[str, Any]]:
    """Return all entries with status 'pending'."""
    queue_path = _get_queue_path()
    if not queue_path.exists():
        return []

    pending_entries = []
    with open(queue_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("status") == "pending":
                    pending_entries.append(entry)
            except json.JSONDecodeError:
                continue
    return pending_entries


def answer(id: str, response: str, signer: str) -> bool:
    """
    Mark a request as answered by appending a signed attestation line.
    Returns True if the request was found and answered, False otherwise.
    """
    queue_path = _get_queue_path()
    if not queue_path.exists():
        return False

    entries = []
    found = False
    with open(queue_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("id") == id and entry.get("status") == "pending":
                    entry["status"] = "answered"
                    entry["answer"] = response
                    entry["signer"] = signer
                    entry["answered_at"] = datetime.now(timezone.utc).isoformat()
                    found = True
                entries.append(entry)
            except json.JSONDecodeError:
                entries.append(None)  # Keep invalid lines as is or handle appropriately

    if not found:
        return False

    # Rewrite the file with updated entries
    with open(queue_path, "w") as f:
        for entry in entries:
            if entry is not None:
                f.write(json.dumps(entry) + "\n")

    return True
