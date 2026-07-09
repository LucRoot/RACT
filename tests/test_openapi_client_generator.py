# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the lightweight OpenAPI client generator."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

import pytest
import yaml

from rootact.openapi_client_generator import OpenApiClientGenerator


SIMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "servers": [{"url": "https://pets.example.com"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List pets",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "summary": "Create a pet",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"},
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            }
        },
    },
}


def test_generate_client_from_json(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SIMPLE_SPEC), encoding="utf-8")
    output = tmp_path / "client.py"
    result = OpenApiClientGenerator(spec_path).generate(output)

    assert result.module_path == output
    assert result.class_name == "PetStoreClient"
    assert result.operation_count == 3

    text = output.read_text(encoding="utf-8")
    assert "class PetStoreClient:" in text
    assert "def list_pets(" in text
    assert "def get_pet(" in text
    assert "def post_pets(" in text
    assert "limit: int | None = None" in text
    assert "petId: str" in text
    assert "body: dict[str, Any] | None = None" in text
    assert 'self.client("GET", f"{self.base_url}/pets"' in text
    assert 'self.client("POST", f"{self.base_url}/pets", json=body)' in text


def test_generate_client_from_yaml(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(SIMPLE_SPEC), encoding="utf-8")
    output = tmp_path / "client.py"
    result = OpenApiClientGenerator(spec_path).generate(output)
    assert result.operation_count == 3
    assert "class PetStoreClient:" in output.read_text(encoding="utf-8")


def test_override_base_url(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SIMPLE_SPEC), encoding="utf-8")
    output = tmp_path / "client.py"
    OpenApiClientGenerator(spec_path, base_url="http://localhost:8000").generate(output)
    text = output.read_text(encoding="utf-8")
    assert "http://localhost:8000" in text


def test_rejects_unsupported_openapi_version(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"openapi": "2.0", "paths": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        OpenApiClientGenerator(spec_path).generate(tmp_path / "client.py")


def test_rejects_missing_paths(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"openapi": "3.0.0", "info": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        OpenApiClientGenerator(spec_path).generate(tmp_path / "client.py")


def test_rejects_non_object_spec(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(ValueError):
        OpenApiClientGenerator(spec_path).generate(tmp_path / "client.py")


def test_fallback_base_url_when_no_servers(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "No Servers", "version": "1.0.0"},
        "paths": {
            "/items": {
                "get": {
                    "operationId": "listItems",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    output = tmp_path / "client.py"
    OpenApiClientGenerator(spec_path).generate(output)
    text = output.read_text(encoding="utf-8")
    assert "https://api.example.com" in text


def test_skips_non_object_path_items(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Bad Path", "version": "1.0.0"},
        "paths": {"/items": "not-a-path-item"},
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    result = OpenApiClientGenerator(spec_path).generate(tmp_path / "client.py")
    assert result.operation_count == 0


def test_python_type_with_missing_schema() -> None:
    gen = OpenApiClientGenerator.__new__(OpenApiClientGenerator)
    assert gen._python_type(None) == "Any"  # type: ignore[arg-type]
    assert gen._python_type("string") == "Any"  # type: ignore[arg-type]


def test_python_type_with_non_string_schema_type() -> None:
    gen = OpenApiClientGenerator.__new__(OpenApiClientGenerator)
    assert gen._python_type({"type": ["string"]}) == "Any"


def test_safe_name_prefixes_leading_digit() -> None:
    gen = OpenApiClientGenerator.__new__(OpenApiClientGenerator)
    assert gen._safe_name("123abc") == "_123abc"


# RACT 0.1.1 - Trust and tooling
