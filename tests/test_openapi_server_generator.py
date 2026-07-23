# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the lightweight OpenAPI server generator."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

import pytest
import yaml

from ract.openapi_server_generator import OpenApiServerGenerator


SIMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
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


def test_generate_server_from_json(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SIMPLE_SPEC), encoding="utf-8")
    output = tmp_path / "server.py"
    result = OpenApiServerGenerator(spec_path).generate(output)

    assert result.module_path == output
    assert result.app_name == "PetStoreServer"
    assert result.operation_count == 3

    text = output.read_text(encoding="utf-8")
    assert "from fastapi import FastAPI, Path, Query" in text
    assert 'app = FastAPI(title="PetStoreServer")' in text
    assert '@app.get("/pets")' in text
    assert "def list_items(" not in text  # sanity: this is the server, not client
    assert "def list_pets(" in text
    assert "def get_pet(" in text
    assert "def post_pets(" in text
    assert "limit: int | None = Query(None)" in text
    assert "petId: str = Path(...)" in text
    assert "body: dict[str, Any] | None = None" in text


def test_generate_server_from_yaml(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(SIMPLE_SPEC), encoding="utf-8")
    output = tmp_path / "server.py"
    result = OpenApiServerGenerator(spec_path).generate(output)
    assert result.operation_count == 3
    assert "from fastapi import FastAPI" in output.read_text(encoding="utf-8")


def test_rejects_invalid_spec(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps({"openapi": "2.0", "paths": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        OpenApiServerGenerator(spec_path).generate(tmp_path / "server.py")


# RACT 0.1.1 - Trust and tooling
