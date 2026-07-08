__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import tempfile
from pathlib import Path

from rootact.config_loader import ConfigLoader, ConfigEntry


def test_load_from_file():
    loader = ConfigLoader()
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.json"
        config_data = [
            {"key": "model", "value": "gpt-4", "description": "LLM to use"},
            {"key": "timeout", "value": 30, "description": "Request timeout seconds"},
        ]
        config_path.write_text(json.dumps(config_data))
        loader.load_from_file(str(config_path))
        assert loader.get("model") == "gpt-4"
        assert loader.get("timeout") == 30
        assert loader.get("nonexistent", "default") == "default"
        assert "model" in loader


def test_config_entry_attributes():
    entry = ConfigEntry(key="test", value=42, description="A test entry")
    assert entry.key == "test"
    assert entry.value == 42
    assert entry.description == "A test entry"


def test_loader_defaults():
    loader = ConfigLoader()
    assert len(loader) == 0
    assert "nonexistent" not in loader
    assert loader.get("missing", 100) == 100
    assert loader.all() == {}


def test_invalid_json_file():
    loader = ConfigLoader()
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "invalid.json"
        config_path.write_text("not a valid json")
        try:
            loader.load_from_file(str(config_path))
            assert False, "Should have raised an exception"
        except json.JSONDecodeError:
            pass  # Expected
