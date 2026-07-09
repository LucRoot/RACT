# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the OpenAPI spec parser utilities."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path
from typing import Any, cast

import pytest

from rootact.openapi_spec_parser import (
    arg_signature,
    categorize_params,
    class_name_from_spec,
    collect_operations,
    load_spec,
    method_name,
    python_type,
    resolve_base_url,
    safe_name,
    to_snake_case,
    validate_spec,
)


def test_load_spec_json(tmp_path: Path) -> None:
    spec_path = tmp_path / "api.json"
    spec_path.write_text(
        json.dumps({"openapi": "3.0.0", "paths": {}}), encoding="utf-8"
    )
    assert load_spec(spec_path) == {"openapi": "3.0.0", "paths": {}}


def test_load_spec_yaml(tmp_path: Path) -> None:
    spec_path = tmp_path / "api.yaml"
    spec_path.write_text("openapi: '3.0.0'\npaths: {}\n", encoding="utf-8")
    assert load_spec(spec_path)["openapi"] == "3.0.0"


def test_validate_spec_rejects_non_dict() -> None:
    with pytest.raises(ValueError, match="must be a JSON/YAML object"):
        validate_spec("not a dict")


def test_validate_spec_rejects_missing_paths() -> None:
    with pytest.raises(ValueError, match="missing 'paths'"):
        validate_spec({"openapi": "3.0.0"})


def test_validate_spec_rejects_non_openapi_three() -> None:
    with pytest.raises(ValueError, match="Only OpenAPI 3.x"):
        validate_spec({"openapi": "2.0", "paths": {}})


def test_class_name_from_spec_uses_title() -> None:
    spec: dict[str, Any] = {"info": {"title": "My Cool API"}}
    assert class_name_from_spec(spec) == "MyCoolApiClient"


def test_class_name_from_spec_fallback() -> None:
    spec: dict[str, Any] = {"info": {}}
    assert class_name_from_spec(spec) == "GeneratedClient"


def test_resolve_base_url_with_override() -> None:
    assert resolve_base_url({}, "http://override") == "http://override"


def test_resolve_base_url_from_servers() -> None:
    assert resolve_base_url({"servers": [{"url": "http://api"}]}) == "http://api"


def test_resolve_base_url_default() -> None:
    assert resolve_base_url({}) == "https://api.example.com"


def test_collect_operations_skips_non_dict_path_item() -> None:
    spec = {"paths": {"/foo": "not a dict"}}
    assert collect_operations(spec) == []


def test_categorize_params() -> None:
    query, path_params, has_body = categorize_params(
        [
            {"name": "limit", "in": "query"},
            {"name": "id", "in": "path"},
        ],
        {"description": "body"},
    )
    assert len(query) == 1
    assert len(path_params) == 1
    assert has_body is True


def test_method_name_from_operation_id() -> None:
    assert method_name("getUser", "get", "/users/{id}") == "get_user"


def test_method_name_fallback_to_method_and_path() -> None:
    assert method_name(None, "POST", "/users/{id}") == "post_users_id"


def test_arg_signature_required() -> None:
    assert (
        arg_signature(
            {"name": "limit", "required": True, "schema": {"type": "integer"}}
        )
        == "limit: int"
    )


def test_arg_signature_optional() -> None:
    assert (
        arg_signature({"name": "limit", "schema": {"type": "integer"}})
        == "limit: int | None = None"
    )


def test_python_type_non_dict_schema() -> None:
    assert python_type(cast(dict[str, Any], "not a dict")) == "Any"


def test_python_type_unknown_schema_type() -> None:
    assert python_type({"type": "blob"}) == "Any"


def test_python_type_missing_schema_type() -> None:
    assert python_type({"format": "uuid"}) == "Any"


def test_safe_name_starts_with_digit() -> None:
    assert safe_name("123foo") == "_123foo"


def test_to_snake_case() -> None:
    assert to_snake_case("GetUserProfile") == "get_user_profile"


# RACT 0.1.1 - Trust and tooling
