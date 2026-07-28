import hashlib
import json
from typing import Dict, List


def fingerprint_run(receipt: Dict) -> str:
    canonical = json.dumps(
        {
            "intent": receipt["intent"],
            "plan_steps": receipt["plan_steps"],
            "provider_model": receipt["provider_model"],
            "artifact_hashes": sorted(receipt["artifact_hashes"]),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


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
