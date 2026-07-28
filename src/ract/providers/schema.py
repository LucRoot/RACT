"""Provider-facing schema converters for the closed action union.

SUBSTRATE §5.2. Three provider surfaces are supported:

- **OpenAI Structured Outputs.** Response-shaped: the model returns a
  single JSON object whose shape is the ``PlannedStep`` schema. The
  wire format is
  ``response_format = {"type": "json_schema", "json_schema": {...}}``
  per the public OpenAI Structured Outputs documentation
  (https://platform.openai.com/docs/guides/structured-outputs).
- **Anthropic tool use.** Turn-shaped: each legal action becomes a
  separate tool definition; the model calls the tool whose name matches
  the ``kind`` it wants to propose. The wire format is
  ``tools=[{"name", "description", "input_schema"}, ...]`` per Anthropic's
  public tool-use documentation
  (https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview).
- **JSON Schema fallback.** For providers without either primitive; the
  model is prompted with a plain JSON Schema and its raw text response
  is parsed with the same validator. Conformance scores are worse on
  average (lateral chain branch B); the router gate will refuse the
  provider if it drops below threshold.

These converters are hand-written; no ``instructor``-style adapter is
imported. The union enumeration lives in
``ract.core.actions.ACTION_MEMBERS`` so the converters do not reflect
into Pydantic v2 internals.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, TypeAdapter

from ract.core.actions import ACTION_MEMBERS, Action, PlannedStep


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _strict_planned_step_schema() -> dict[str, Any]:
    """Return the JSON Schema for ``PlannedStep`` in a strict shape.

    Pydantic v2's default JSON schema is close to but not exactly what
    OpenAI Structured Outputs wants; ``additionalProperties=false`` must
    hold at every object level, every field must be in ``required``, and
    the discriminator ``kind`` must be preserved as a literal enum on
    each union arm.
    """
    schema = PlannedStep.model_json_schema()
    return _harden(schema)


def _harden(schema: Any) -> Any:
    """Walk the schema and enforce strict-object rules recursively.

    - Every ``type: object`` gets ``additionalProperties: false``.
    - Every ``properties`` block has every property in ``required``.
    - ``$defs`` entries get the same treatment; ``$ref`` links are left
      alone since the referent is walked separately.
    """
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            props = schema.get("properties")
            if isinstance(props, dict):
                schema["additionalProperties"] = False
                schema["required"] = sorted(props.keys())
        # Recurse into every nested structural key.
        for key in ("properties", "$defs", "definitions"):
            child = schema.get(key)
            if isinstance(child, dict):
                for sub_key, sub in list(child.items()):
                    child[sub_key] = _harden(sub)
        for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            child = schema.get(key)
            if isinstance(child, list):
                schema[key] = [_harden(item) for item in child]
        for key in ("items", "additionalProperties", "not"):
            child = schema.get(key)
            if isinstance(child, dict):
                schema[key] = _harden(child)
    elif isinstance(schema, list):
        return [_harden(item) for item in schema]
    return schema


def _action_json_schema(cls: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for a single action class."""
    schema = cls.model_json_schema()
    return _harden(schema)


# ---------------------------------------------------------------------------
# OpenAI Structured Outputs
# ---------------------------------------------------------------------------


def to_openai_structured_outputs(
    _union: type = PlannedStep,
    *,
    name: str = "planned_step",
) -> dict[str, Any]:
    """Return the ``response_format`` payload for OpenAI Structured Outputs.

    ``_union`` is accepted for API parity with the other converters but is
    always ``PlannedStep`` — the union arms are enumerated inside the
    step's ``action`` field. The returned dict is a valid value for the
    ``response_format`` parameter on ``chat.completions.create``:
    ``{"type": "json_schema", "json_schema": {"name", "schema", "strict"}}``.
    """
    schema = _strict_planned_step_schema()
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": True,
        },
    }


# ---------------------------------------------------------------------------
# Anthropic tool use
# ---------------------------------------------------------------------------


def to_anthropic_tool_use(_union: type = PlannedStep) -> list[dict[str, Any]]:
    """Return an Anthropic ``tools`` list — one tool per action kind.

    Each tool's ``input_schema`` is the JSON Schema of one action arm.
    The model selects a tool by name (``write_file``, ``run_tests``,
    etc.); the validator (``providers/validator.py``) reconstructs the
    ``PlannedStep`` shape from the tool call.
    """
    tools: list[dict[str, Any]] = []
    for cls in ACTION_MEMBERS:
        kind_default = cls.model_fields["kind"].default
        schema = _action_json_schema(cls)
        # Anthropic accepts an object schema for input; drop the top-level
        # title (which Pydantic sets to the class name) so the tool's
        # ``name`` field is the canonical identifier.
        schema.pop("title", None)
        tools.append(
            {
                "name": str(kind_default),
                "description": (cls.__doc__ or "").strip().split("\n\n")[0]
                or f"{kind_default} action",
                "input_schema": schema,
            }
        )
    return tools


# ---------------------------------------------------------------------------
# JSON Schema fallback
# ---------------------------------------------------------------------------


def to_json_schema_fallback(_union: type = PlannedStep) -> dict[str, Any]:
    """Return a plain JSON Schema for the ``PlannedStep`` union.

    Providers without a structured-output or tool-use primitive receive
    this schema in the prompt. The model is expected to reply with a
    JSON object matching the schema; the validator parses the raw text
    with the same ``ResponseValidator``.
    """
    schema = _strict_planned_step_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


# ---------------------------------------------------------------------------
# Round-trip helper — used by tests and by the fake provider
# ---------------------------------------------------------------------------


_ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


def parse_action_dict(payload: dict[str, Any]) -> Action:
    """Validate a raw dict into a concrete action via the discriminator."""
    return _ACTION_ADAPTER.validate_python(payload)


def parse_planned_step_dict(payload: dict[str, Any]) -> PlannedStep:
    """Validate a raw dict into a ``PlannedStep``."""
    return PlannedStep.model_validate(payload)


__all__ = [
    "parse_action_dict",
    "parse_planned_step_dict",
    "to_anthropic_tool_use",
    "to_json_schema_fallback",
    "to_openai_structured_outputs",
]


# RACT 0.4.0
