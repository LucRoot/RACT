__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import pytest
from rootact.config_validation import validate_config

def test_valid_config():
    config = {"title": "Configuration Validation and Pre-Flight Check", "description": "RootAct validates the user's rootact.yaml, provider reachability, and required tools before starting work.", "tags": ["core", "ux", "low-complexity", "high-priority"]}
    assert validate_config(config)

def test_missing_title():
    config = {"description": "RootAct validates the user's rootact.yaml, provider reachability, and required tools before starting work.", "tags": ["core", "ux", "low-complexity", "high-priority"]}
    assert not validate_config(config)

def test_missing_description():
    config = {"title": "Configuration Validation and Pre-Flight Check", "tags": ["core", "ux", "low-complexity", "high-priority"]}
    assert not validate_config(config)

def test_missing_tags():
    config = {"title": "Configuration Validation and Pre-Flight Check", "description": "RootAct validates the user's rootact.yaml, provider reachability, and required tools before starting work."}
    assert not validate_config(config)

def test_invalid_tags_type():
    config = {"title": "Configuration Validation and Pre-Flight Check", "description": "RootAct validates the user's rootact.yaml, provider reachability, and required tools before starting work.", "tags": "not a list"}
    assert not validate_config(config)
