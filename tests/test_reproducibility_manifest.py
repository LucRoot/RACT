from __future__ import annotations


from ract.reproducibility_manifest import build_manifest, _canonical_json, _sha256_hex


def test_build_manifest_structure_and_markers():
    manifest = build_manifest(
        intent="test intent",
        plan={"steps": ["a", "b"]},
        config={"model": "qwen"},
        fingerprint="fp-123",
    )
    assert manifest["intent"] == "test intent"
    assert manifest["fingerprint"] == "fp-123"
    assert "plan_hash" in manifest
    assert "config_hash" in manifest
    assert "manifest_hash" in manifest
    env = manifest["environment"]
    assert "python_version" in env
    assert "platform" in env
    assert "machine" in env
    assert "processor" in env


def test_manifest_hash_is_stable():
    args = {
        "intent": "stable test",
        "plan": {"b": 2, "a": 1},
        "config": {"z": True, "y": False},
        "fingerprint": "fp-stable",
    }
    m1 = build_manifest(**args)
    m2 = build_manifest(**args)
    assert m1["manifest_hash"] == m2["manifest_hash"]
    assert m1["plan_hash"] == m2["plan_hash"]
    assert m1["config_hash"] == m2["config_hash"]


def test_different_inputs_yield_different_hashes():
    base = {
        "intent": "base",
        "plan": {"steps": ["x"]},
        "config": {"temp": 0.7},
        "fingerprint": "fp",
    }
    m_base = build_manifest(**base)
    m_diff_plan = build_manifest(**{**base, "plan": {"steps": ["y"]}})
    m_diff_config = build_manifest(**{**base, "config": {"temp": 0.8}})
    m_diff_fp = build_manifest(**{**base, "fingerprint": "fp2"})
    assert m_base["manifest_hash"] != m_diff_plan["manifest_hash"]
    assert m_base["manifest_hash"] != m_diff_config["manifest_hash"]
    assert m_base["manifest_hash"] != m_diff_fp["manifest_hash"]


def test_plan_hash_matches_canonical_sha256():
    plan = {"z": 1, "a": [3, 1, 2]}
    manifest = build_manifest("intent", plan, {}, "fp")
    assert manifest["plan_hash"] == _sha256_hex(_canonical_json(plan))


def test_manifest_hash_excludes_itself():
    plan = {"step": 1}
    config = {"model": "qwen"}
    manifest = build_manifest("intent", plan, config, "fp")
    body_without_hash = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    assert manifest["manifest_hash"] == _sha256_hex(_canonical_json(body_without_hash))


def test_environment_markers_are_populated():
    manifest = build_manifest("intent", {}, {}, "fp")
    env = manifest["environment"]
    assert isinstance(env["python_version"], str) and env["python_version"]
    assert isinstance(env["platform"], str) and env["platform"]
    assert isinstance(env["machine"], str) and env["machine"]
    # platform.processor() may be empty on some hosts; just ensure it's a string.
    assert isinstance(env["processor"], str)


def test_non_ascii_intent_and_keys_survive_canonicalisation():
    manifest = build_manifest(
        intent="résumé",
        plan={"clé": "valeur"},
        config={"温度": 0.5},
        fingerprint="fp",
    )
    assert manifest["intent"] == "résumé"
    round_tripped = _canonical_json(manifest)
    assert "résumé" in round_tripped
