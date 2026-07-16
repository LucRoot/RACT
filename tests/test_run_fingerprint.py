__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
from rootact.run_fingerprint import fingerprint_run, diff_fingerprints


def test_identical_receipts():
    receipt1 = {
        "intent": "Test task",
        "plan_steps": ["Step 1", "Step 2"],
        "provider_model": "openai",
        "artifact_hashes": ["hash1", "hash2"],
    }
    receipt2 = {
        "intent": "Test task",
        "plan_steps": ["Step 1", "Step 2"],
        "provider_model": "openai",
        "artifact_hashes": ["hash1", "hash2"],
    }
    assert fingerprint_run(receipt1) == fingerprint_run(receipt2)


def test_changed_step_model():
    receipt1 = {
        "intent": "Test task",
        "plan_steps": ["Step 1", "Step 2"],
        "provider_model": "openai",
        "artifact_hashes": ["hash1", "hash2"],
    }
    receipt2 = {
        "intent": "Test task",
        "plan_steps": ["Step 1", "Step 3"],
        "provider_model": "ollama",
        "artifact_hashes": ["hash1", "hash2"],
    }
    assert diff_fingerprints(receipt1, receipt2) == ["plan_steps", "provider_model"]
