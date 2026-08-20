import hashlib
from typing import Dict, List

from ract.canonical import dumps_jcs


def fingerprint_run(receipt: Dict) -> str:
    # v0.5.1 module_03: RFC 8785 JCS canonical form.
    canonical = dumps_jcs(
        {
            "intent": receipt["intent"],
            "plan_steps": receipt["plan_steps"],
            "provider_model": receipt["provider_model"],
            "artifact_hashes": sorted(receipt["artifact_hashes"]),
        }
    )
    return hashlib.sha256(canonical).hexdigest()


def diff_fingerprints(a: Dict, b: Dict) -> List:
    diff = []
    for key in sorted(set(a.keys()) | set(b.keys())):
        if key in a and key in b:
            if a[key] != b[key]:
                diff.append(key)
        elif key in a:
            diff.append(key)
        else:
            diff.append(key)
    return diff
