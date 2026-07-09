# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Shared OpenAPI 3 parsing utilities for RACT code generators."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

VALID_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def load_spec(spec_path: Path) -> dict[str, Any]:
    text = Path(spec_path).read_text(encoding="utf-8")
    if spec_path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    return json.loads(text)


def validate_spec(spec: Any) -> None:
    if not isinstance(spec, dict):
        raise ValueError("OpenAPI spec must be a JSON/YAML object")
    version = spec.get("openapi") or spec.get("swagger")
    if not version or not str(version).startswith("3."):
        raise ValueError(f"Only OpenAPI 3.x specs are supported; got {version}")
    if "paths" not in spec:
        raise ValueError("OpenAPI spec is missing 'paths'")


def class_name_from_spec(spec: dict[str, Any], suffix: str = "Client") -> str:
    title = spec.get("info", {}).get("title", "Generated")
    name = "".join(part.capitalize() for part in re.split(r"[^a-zA-Z0-9]+", title))
    name = re.sub(r"[^a-zA-Z0-9]", "", name)
    return f"{name}{suffix}" if name else f"Api{suffix}"


def resolve_base_url(spec: dict[str, Any], override: str | None = None) -> str:
    if override:
        return override
    servers = spec.get("servers", [])
    if servers and isinstance(servers, list):
        return servers[0].get("url", "https://api.example.com")
    return "https://api.example.com"


def collect_operations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    paths = spec.get("paths", {})
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in VALID_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            operations.append({"method": method, "path": path, "operation": operation})
    return operations


def categorize_params(
    params: list[dict[str, Any]], body: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    query: list[dict[str, Any]] = []
    path: list[dict[str, Any]] = []
    for p in params:
        loc = p.get("in")
        if loc == "query":
            query.append(p)
        elif loc == "path":
            path.append(p)
    has_body = isinstance(body, dict)
    return query, path, has_body


def method_name(operation_id: str | None, method: str, path: str) -> str:
    if operation_id:
        return to_snake_case(safe_name(operation_id))
    parts = [method.lower()] + [
        part for part in re.split(r"[^a-zA-Z0-9]+", path) if part
    ]
    return safe_name("_".join(parts))


def arg_signature(param: dict[str, Any]) -> str:
    name = safe_name(param["name"])
    required = param.get("required", False)
    raw_schema = param.get("schema")
    schema: dict[str, Any] = raw_schema if isinstance(raw_schema, dict) else {}
    py_type = python_type(schema)
    if required:
        return f"{name}: {py_type}"
    return f"{name}: {py_type} | None = None"


def python_type(schema: dict[str, Any]) -> str:
    if not isinstance(schema, dict):
        return "Any"
    type_map = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list[Any]",
        "object": "dict[str, Any]",
    }
    schema_type = schema.get("type")
    if not isinstance(schema_type, str):
        return "Any"
    return type_map.get(schema_type, "Any")


def safe_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if safe and safe[0].isdigit():
        safe = f"_{safe}"
    return safe or "operation"


def to_snake_case(name: str) -> str:
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


# RACT 0.1.1 - Trust and Tooling
