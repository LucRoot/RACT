__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()


def build_statement(ai_manifest: dict) -> dict:
    return {
        "_type": "https://in-toto.io/Statement/v0.1",
        "subject": ai_manifest.get("subject", []),
        "predicateType": "https://in-toto.io/attestation/release/v0.1",
        "predicate": {
            "name": ai_manifest.get("name", ""),
            "created": ai_manifest.get("created", ""),
            "manifest": ai_manifest,
        },
    }
