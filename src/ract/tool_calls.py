"""Tool-call extraction: turn a model reply into calls, an answer, or a named failure.

LR:: Models emit tool calls in many shapes. A hosted model fills the native
``tool_calls`` field. A local model behind a server without tool support
prints the call as text: inside ``<tool_call>`` tags, as fenced or bare JSON,
as a Python-looking call, or in Harmony channel markup. The agent loop needs
one answer to "what did the model ask for?" no matter which shape it used, and
it must never mistake leftover call markup for a finished answer.

``extract`` walks a fixed ladder and records the rung that worked:

1. ``native``: the response's ``tool_calls`` field.
2. ``tag``: ``<tool_call>{...}</tool_call>`` blocks.
3. ``harmony``: ``to=functions.NAME ... <|message|>{...}`` channel markup.
4. ``fenced_json``: a fenced code block holding a call object.
5. ``envelope``: RACT's own JSON envelope, ``{"tool": ..., "arguments": ...}``
   or ``{"final": ...}``, as the whole message.
6. ``bare_json``: a call object as the whole message, in the common
   ``{"name": ..., "arguments": ...}`` shape.
7. ``pythonic``: ``read_file(path="a.py")`` or ``[f(...), g(...)]`` as the
   whole message.

The two rungs after these need a network round trip, so this module only
names them: ``next_action`` returns ``grammar_retry`` (ask again with a JSON
grammar when the server supports one), then ``reformat_request`` (one message
asking the model to restate the call), then ``fail``.

Nothing here runs a tool, decides a tier, or approves anything. A parsed call
is a request. Reasoning (``reasoning_content`` and ``<think>`` blocks) is
removed before parsing, so a call the model only thought about is never
extracted.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ract.canonical import dumps_jcs
from ract.model_output import describe_output_problem, finish_reason, strip_reasoning
from ract.rooted import Rooted

Rung = Literal[
    "native", "tag", "harmony", "fenced_json", "envelope", "bare_json", "pythonic"
]
RUNGS: tuple[Rung, ...] = (
    "native",
    "tag",
    "harmony",
    "fenced_json",
    "envelope",
    "bare_json",
    "pythonic",
)

Outcome = Literal[
    "tool_calls",
    "final",
    "markup_unparsed",
    "truncated",
    "empty",
    "unknown_tool",
    "invalid_arguments",
    "too_many_calls",
]
NextAction = Literal["grammar_retry", "reformat_request", "fail", "none"]

# More calls than this in one reply are refused as a whole. The loop budget
# would stop execution later, but the list would still reach the renderer and
# the approval prompts.
MAX_CALLS_PER_REPLY = 32

REFORMAT_REQUEST = (
    "Your last reply could not be read as a tool call or a final answer. "
    "Reply again with only one JSON object and nothing else: "
    '{"tool": "<tool name>", "arguments": {...}} to call a tool, or '
    '{"final": "<your answer>"} when you are done.'
)


@dataclass(frozen=True)
class ToolSignature:
    """What extraction needs to know about a tool: its name and argument keys."""

    name: str
    arg_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Repair:
    """One change extraction made to what the model said."""

    kind: Literal["tool_name", "arg_key"]
    original: str
    repaired: str

    def __str__(self) -> str:
        return f"repaired: {self.original} -> {self.repaired}"


@dataclass(frozen=True)
class ToolCall:
    """A tool call as requested by the model, after any repairs."""

    name: str
    arguments: dict[str, Any]
    call_id: str
    rung: Rung
    repairs: tuple[Repair, ...] = ()


@dataclass(frozen=True)
class Extraction:
    """The result of reading one model reply."""

    outcome: Outcome
    calls: tuple[ToolCall, ...] = ()
    final_text: str = ""
    rung: Rung | None = None
    explanation: str = ""
    raw_text: str = ""
    problems: tuple[str, ...] = field(default_factory=tuple)
    # Characters of visible text before the first and after the last parsed
    # call. Non-zero means the calls sat inside prose (for example a fenced
    # example the model quoted from a file it read). Parsing grants nothing;
    # the loop's trust rule (ADR-0048 D9) decides what such a call may do.
    prose_before: int = 0
    prose_after: int = 0


# ---------------------------------------------------------------------------
# Unparsed markup detection (R-142)
# ---------------------------------------------------------------------------

_MARKUP_PATTERNS = (
    re.compile(r"<\s*/?\s*tool_call\b", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(?:\w+:)?invoke\b", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(?:\w+:)?function_calls\b", re.IGNORECASE),
    re.compile(r"<\s*/?\s*tool_use\b", re.IGNORECASE),
    re.compile(r"<\|(?:call|constrain|channel)\|>"),
    re.compile(r"\bto=functions\.[A-Za-z_]"),
    re.compile(r"\[TOOL_CALLS\]"),
    re.compile(r'"tool_calls"\s*:\s*\['),
    # A call object that did not parse (cut off, or wrapped in prose). A final
    # answer that quotes such an object as an example is read the same way
    # and gets one reformat request; that cost is accepted.
    re.compile(r'\{\s*"tool"\s*:\s*"'),
    re.compile(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"(?:arguments|parameters)"\s*:'),
)


def contains_tool_markup(text: str) -> bool:
    """True when text carries tool-call markup that was not parsed as a call."""
    return any(p.search(text) for p in _MARKUP_PATTERNS)


# ---------------------------------------------------------------------------
# Rung parsers. Each returns a list of (name, arguments) or None.
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_HARMONY_RE = re.compile(
    r"to=functions\.([A-Za-z_][\w.-]*)[^\n<]*?(?:<\|constrain\|>\s*json\s*)?<\|message\|>(.*?)(?:<\|call\|>|<\|end\|>|\Z)",
    re.DOTALL,
)
_FENCE_RE = re.compile(
    r"```(?:json|tool_call|tool)?\s*\n(.*?)\n?```", re.DOTALL | re.IGNORECASE
)

ParsedCall = tuple[str, Any]


class _DuplicateKeyError(ValueError):
    """A JSON object names the same key twice.

    ``json.loads`` keeps the last value, so ``{"tool": "read_file", "tool":
    "run_command"}`` would silently become ``run_command``, and another
    reader might keep the first. Such a reply is refused instead.
    """


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _DuplicateKeyError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _loads(text: str) -> Any:
    """``json.loads`` that refuses duplicate keys at any depth."""
    return json.loads(text, object_pairs_hook=_no_duplicates)


# A call form longer than this is not parsed as Python; it is almost certainly
# prose or code, and ``ast.parse`` cost grows with input size.
_PYTHONIC_MAX_CHARS = 20_000


def _call_from_object(
    obj: Any, *, allow_envelope: bool, allow_named: bool = True
) -> ParsedCall | None:
    if not isinstance(obj, dict):
        return None
    if allow_envelope and isinstance(obj.get("tool"), str):
        return obj["tool"], obj.get("arguments", {})
    if not allow_named:
        return None
    name = obj.get("name")
    if isinstance(name, str) and ("arguments" in obj or "parameters" in obj):
        return name, obj.get("arguments", obj.get("parameters", {}))
    function = obj.get("function")
    if isinstance(function, dict) and isinstance(function.get("name"), str):
        return function["name"], function.get("arguments", {})
    return None


def _calls_from_json_text(
    text: str, *, allow_envelope: bool, allow_named: bool = True
) -> list[ParsedCall] | None:
    try:
        data = _loads(text)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None
    items = data if isinstance(data, list) else [data]
    calls = [
        _call_from_object(item, allow_envelope=allow_envelope, allow_named=allow_named)
        for item in items
    ]
    if not calls or any(c is None for c in calls):
        return None
    return [c for c in calls if c is not None]


def _parse_tag(text: str) -> list[ParsedCall] | None:
    bodies = _TAG_RE.findall(text)
    if not bodies:
        return None
    calls: list[ParsedCall] = []
    for body in bodies:
        parsed = _calls_from_json_text(body, allow_envelope=True)
        if parsed is None:
            return None
        calls.extend(parsed)
    return calls


def _parse_harmony(text: str) -> list[ParsedCall] | None:
    matches = _HARMONY_RE.findall(text)
    if not matches:
        return None
    calls: list[ParsedCall] = []
    for name, body in matches:
        try:
            args = _loads(body.strip() or "{}")
        except (json.JSONDecodeError, ValueError, RecursionError):
            return None
        calls.append((name.removeprefix("functions."), args))
    return calls


def _parse_fenced(text: str) -> list[ParsedCall] | None:
    blocks = _FENCE_RE.findall(text)
    if len(blocks) != 1:
        return None
    return _calls_from_json_text(blocks[0].strip(), allow_envelope=True)


def _parse_envelope(text: str) -> list[ParsedCall] | None:
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return None
    return _calls_from_json_text(stripped, allow_envelope=True, allow_named=False)


def _parse_bare(text: str) -> list[ParsedCall] | None:
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return None
    return _calls_from_json_text(stripped, allow_envelope=False)


def _literal(node: ast.AST) -> Any:
    return ast.literal_eval(node)


def _parse_pythonic(text: str) -> list[ParsedCall] | None:
    # The whole message must be one expression: a call or a list of calls.
    # Prose that mentions a call ("I would run f(x=1)") does not parse.
    stripped = text.strip()
    if not stripped or len(stripped) > _PYTHONIC_MAX_CHARS:
        return None
    try:
        tree = ast.parse(stripped, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    nodes = tree.body.elts if isinstance(tree.body, ast.List) else [tree.body]
    calls: list[ParsedCall] = []
    for node in nodes:
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.args
        ):
            return None
        try:
            args = {kw.arg: _literal(kw.value) for kw in node.keywords if kw.arg}
        except (ValueError, SyntaxError, TypeError, RecursionError):
            return None
        if len(args) != len(node.keywords):
            return None
        calls.append((node.func.id, args))
    return calls or None


# ---------------------------------------------------------------------------
# Repairs (R-143)
# ---------------------------------------------------------------------------


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _repair_name(
    name: str, tools: Mapping[str, ToolSignature]
) -> tuple[str | None, Repair | None, str]:
    if name in tools:
        return name, None, ""
    matches = [t for t in tools if _norm(t) == _norm(name)]
    if not matches:
        stripped = name.split(".")[-1]
        matches = [t for t in tools if _norm(t) == _norm(stripped)]
    if len(matches) == 1:
        return matches[0], Repair("tool_name", name, matches[0]), ""
    if len(matches) > 1:
        return (
            None,
            None,
            f"tool name {name!r} matches more than one tool: {sorted(matches)}",
        )
    return None, None, f"no tool named {name!r}; available: {sorted(tools)}"


def _repair_keys(
    args: dict[str, Any], signature: ToolSignature
) -> tuple[dict[str, Any] | None, list[Repair], str]:
    if not signature.arg_keys:
        return args, [], ""
    fixed: dict[str, Any] = {}
    repairs: list[Repair] = []
    for key, value in args.items():
        if key in signature.arg_keys:
            fixed[key] = value
            continue
        unused = [k for k in signature.arg_keys if k not in args]
        candidates = [
            k
            for k in unused
            if _norm(k) == _norm(key)
            or _norm(k).endswith(_norm(key))
            or _norm(key).endswith(_norm(k))
        ]
        if len(candidates) != 1:
            reason = (
                "matches more than one argument" if candidates else "is not an argument"
            )
            return (
                None,
                [],
                (
                    f"argument {key!r} {reason} of {signature.name}; "
                    f"expected keys: {sorted(signature.arg_keys)}"
                ),
            )
        fixed[candidates[0]] = value
        repairs.append(Repair("arg_key", key, candidates[0]))
    return fixed, repairs, ""


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def _message(response: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        return {}
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        return message if isinstance(message, dict) else {}
    return {}


def _native_calls(message: Mapping[str, Any]) -> list[tuple[str, Any, str]] | None:
    raw = message.get("tool_calls")
    if not isinstance(raw, list) or not raw:
        return None
    if len(raw) > MAX_CALLS_PER_REPLY:
        # Signal "too many" without decoding thousands of entries.
        return [("", None, "")] * (MAX_CALLS_PER_REPLY + 1)
    calls = []
    for i, item in enumerate(raw):
        function = item.get("function", {}) if isinstance(item, dict) else {}
        name = function.get("name")
        if not isinstance(name, str) or not name:
            return []
        calls.append(
            (name, function.get("arguments", {}), str(item.get("id") or f"native_{i}"))
        )
    return calls


def _decode_arguments(raw: Any) -> tuple[dict[str, Any] | None, str]:
    """Return (arguments, problem). Problem is empty when arguments is a dict."""
    if isinstance(raw, dict):
        return dict(raw), ""
    if raw is None:
        return {}, ""
    if not isinstance(raw, str):
        return None, f"arguments are a {type(raw).__name__}, not a JSON object"
    if not raw.strip():
        return {}, ""
    try:
        value = _loads(raw)
    except _DuplicateKeyError as exc:
        return None, f"arguments name a key twice ({exc})"
    except (json.JSONDecodeError, RecursionError):
        snippet = raw[:80] + ("..." if len(raw) > 80 else "")
        return None, f"arguments are not valid JSON: {snippet!r}"
    if not isinstance(value, dict):
        return None, f"arguments are a JSON {type(value).__name__}, not an object"
    return value, ""


def _has_duplicate_keys(text: str) -> bool:
    """True when some JSON object in the reply names a key twice."""
    candidates = [text.strip(), *_FENCE_RE.findall(text), *_TAG_RE.findall(text)]
    for candidate in candidates:
        try:
            _loads(candidate.strip())
        except _DuplicateKeyError:
            return True
        except (json.JSONDecodeError, ValueError, RecursionError):
            continue
    return False


def _prose_around(text: str, rung: Rung) -> tuple[int, int]:
    """Visible characters before the first and after the last call span."""
    patterns = {"tag": _TAG_RE, "harmony": _HARMONY_RE, "fenced_json": _FENCE_RE}
    pattern = patterns.get(rung)
    if pattern is None:
        return 0, 0
    spans = [m.span() for m in pattern.finditer(text)]
    if not spans:
        return 0, 0
    before = text[: spans[0][0]]
    after = text[spans[-1][1] :]
    if rung == "harmony":
        # Harmony channel headers before the call are markup, not prose.
        before = re.sub(r"<\|[^|]*\|>[^<]*", "", before)
    return len(before.strip()), len(after.strip())


def explain_truncation(
    response: Mapping[str, Any] | None, *, max_tokens: int | None = None
) -> str:
    """Name a length cut in plain words, with token counts when the server gave them."""
    usage = response.get("usage") if isinstance(response, Mapping) else None
    completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
    message = _message(response)
    reasoning = str(message.get("reasoning_content") or message.get("reasoning") or "")
    if isinstance(completion, int) and max_tokens:
        spent = (
            "reasoning"
            if reasoning
            and not strip_reasoning(str(message.get("content") or "")).strip()
            else "the reply"
        )
        return (
            f"The model stopped at its output limit: {spent} used {completion:,} of "
            f"{max_tokens:,} tokens and no tool call or answer was finished. "
            "RACT will retry once with a higher limit; raise 'max_tokens' for "
            "this provider in ract.yaml to avoid the retry."
        )
    return describe_output_problem(
        dict(response) if isinstance(response, Mapping) else None,
        wanted="tool call or answer",
    )


def extract(
    response: Mapping[str, Any] | None,
    tools: Sequence[ToolSignature] | Iterable[ToolSignature],
    *,
    max_tokens: int | None = None,
) -> Rooted[Extraction]:
    """Read one chat-completion response. Never raises on a malformed one."""
    by_name = {t.name: t for t in tools}
    message = _message(response)
    content = str(message.get("content") or "")
    visible = strip_reasoning(content)

    parsed: list[tuple[str, Any, str]] | None = None
    rung: Rung | None = None
    native = _native_calls(message)
    if native:
        parsed, rung = native, "native"
    elif native == []:
        return _failure(
            "markup_unparsed",
            content,
            "The reply had a tool_calls block with no tool name in it.",
        )
    else:
        text_rungs: tuple[tuple[Rung, Any], ...] = (
            ("tag", _parse_tag),
            ("harmony", _parse_harmony),
            ("fenced_json", _parse_fenced),
            ("envelope", _parse_envelope),
            ("bare_json", _parse_bare),
            ("pythonic", _parse_pythonic),
        )
        for rung_name, parser in text_rungs:
            found = parser(visible)
            if found:
                parsed = [(n, a, f"{rung_name}_{i}") for i, (n, a) in enumerate(found)]
                rung = rung_name
                break

    if parsed is not None and len(parsed) > MAX_CALLS_PER_REPLY:
        native_count = len(message.get("tool_calls") or [])
        count = native_count if rung == "native" else len(parsed)
        return _failure(
            "too_many_calls",
            content,
            f"The reply asked for {count:,} tool calls; RACT reads at most "
            f"{MAX_CALLS_PER_REPLY} per reply. Nothing from it was run.",
        )

    if parsed is None:
        final = _final_from_envelope(visible)
        if final is not None:
            return _ok(
                Extraction(
                    outcome="final", final_text=final, rung="envelope", raw_text=content
                ),
                "The reply was a final answer in the JSON envelope.",
            )
        if contains_tool_markup(visible):
            reason = (
                "The reply contains a JSON object that names the same key twice, "
                "so which tool or argument was meant is ambiguous."
                if _has_duplicate_keys(visible)
                else "The reply contains tool-call markup RACT could not read."
            )
            return _failure(
                "markup_unparsed",
                content,
                reason + " It was not used as an answer. RACT asks the model "
                "to restate it once.",
            )
        if (
            finish_reason(dict(response) if isinstance(response, Mapping) else None)
            == "length"
        ):
            return _failure(
                "truncated",
                content,
                explain_truncation(response, max_tokens=max_tokens),
            )
        if not visible.strip():
            return _failure(
                "empty",
                content,
                describe_output_problem(
                    dict(response) if isinstance(response, Mapping) else None,
                    wanted="tool call or answer",
                ),
            )
        return _ok(
            Extraction(outcome="final", final_text=visible.strip(), raw_text=content),
            "The reply was plain text with no tool-call markup.",
        )

    assert rung is not None
    calls: list[ToolCall] = []
    name_problems: list[str] = []
    arg_problems: list[str] = []
    for name, raw_args, call_id in parsed:
        resolved, name_repair, problem = _repair_name(name, by_name)
        if resolved is None:
            name_problems.append(problem)
            continue
        arguments, problem = _decode_arguments(raw_args)
        if arguments is None:
            arg_problems.append(f"{resolved}: {problem}")
            continue
        fixed, key_repairs, problem = _repair_keys(arguments, by_name[resolved])
        if fixed is None:
            arg_problems.append(problem)
            continue
        repairs = ((name_repair,) if name_repair else ()) + tuple(key_repairs)
        calls.append(ToolCall(resolved, fixed, call_id, rung, repairs))

    if name_problems or arg_problems:
        problems = name_problems + arg_problems
        outcome: Outcome
        if name_problems:
            outcome = "unknown_tool"
            hint = "Use one of the listed tool names exactly."
        else:
            outcome = "invalid_arguments"
            hint = "Arguments must be one JSON object using the listed keys, each key once."
        return Rooted(
            value=Extraction(
                outcome=outcome, rung=rung, raw_text=content, problems=tuple(problems)
            ),
            assumption="Every tool call in the reply names one known tool with valid arguments.",
            confidence=0.0,
            provenance=["tool_calls.extract", f"rung:{rung}"],
            error="; ".join(problems),
            hint=hint,
        )
    if rung == "native":
        before, after = len(visible.strip()), 0
    else:
        before, after = _prose_around(visible, rung)
    return _ok(
        Extraction(
            outcome="tool_calls",
            calls=tuple(calls),
            rung=rung,
            raw_text=content,
            prose_before=before,
            prose_after=after,
        ),
        f"The reply's tool calls were read from the {rung} form.",
        rung=rung,
    )


def _final_from_envelope(text: str) -> str | None:
    stripped = text.strip()
    fenced = _FENCE_RE.findall(stripped)
    candidate = fenced[0].strip() if len(fenced) == 1 else stripped
    if not candidate.startswith("{"):
        return None
    try:
        data = _loads(candidate)
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None
    if (
        isinstance(data, dict)
        and set(data) == {"final"}
        and isinstance(data["final"], str)
    ):
        return data["final"]
    return None


def _ok(
    extraction: Extraction, assumption: str, *, rung: Rung | None = None
) -> Rooted[Extraction]:
    provenance = ["tool_calls.extract"]
    if rung or extraction.rung:
        provenance.append(f"rung:{rung or extraction.rung}")
    return Rooted(
        value=extraction, assumption=assumption, confidence=1.0, provenance=provenance
    )


def _failure(outcome: Outcome, raw: str, explanation: str) -> Rooted[Extraction]:
    hints = {
        "markup_unparsed": "tool-parse-failed",
        "truncated": "output_limit",
        "empty": "empty_output",
        "too_many_calls": "Ask for fewer tool calls per reply.",
    }
    return Rooted(
        value=Extraction(outcome=outcome, raw_text=raw, explanation=explanation),
        assumption="The reply holds a readable tool call or a final answer.",
        confidence=0.0,
        provenance=["tool_calls.extract"],
        error=explanation,
        hint=hints.get(outcome, outcome),
    )


def next_action(
    extraction: Extraction,
    *,
    server_supports_grammar: bool,
    grammar_tried: bool,
    reformat_tried: bool,
) -> NextAction:
    """Which network rung to try after a failed read, or ``fail``.

    Unreadable replies climb the whole ladder. Replies with a readable shape
    but bad arguments, or too many calls, get the reformat request only: a
    grammar retry would constrain the format, which was not the problem.
    Truncation is handled by a retry with a higher limit (see
    ``explain_truncation``) and unknown tools go back to the model as a
    refusal it can correct.
    """
    if extraction.outcome in {"invalid_arguments", "too_many_calls"}:
        return "fail" if reformat_tried else "reformat_request"
    if extraction.outcome != "markup_unparsed" and extraction.outcome != "empty":
        return "none"
    if server_supports_grammar and not grammar_tried:
        return "grammar_retry"
    if not reformat_tried:
        return "reformat_request"
    return "fail"


# ---------------------------------------------------------------------------
# Streaming accumulation
# ---------------------------------------------------------------------------


def accumulate_stream(chunks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Fold streamed chat-completion chunks into one non-streaming response."""
    content: list[str] = []
    reasoning: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    finish = None
    usage = None
    for chunk in chunks:
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        finish = choice.get("finish_reason") or finish
        delta = choice.get("delta") or {}
        if delta.get("content"):
            content.append(delta["content"])
        if delta.get("reasoning_content"):
            reasoning.append(delta["reasoning_content"])
        for tc in delta.get("tool_calls") or []:
            entry = calls.setdefault(
                int(tc.get("index", 0)), {"id": "", "name": "", "arguments": ""}
            )
            entry["id"] = tc.get("id") or entry["id"]
            function = tc.get("function") or {}
            entry["name"] = function.get("name") or entry["name"]
            entry["arguments"] += function.get("arguments") or ""
    message: dict[str, Any] = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if calls:
        message["tool_calls"] = [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": c["arguments"]},
            }
            for _, c in sorted(calls.items())
        ]
    response: dict[str, Any] = {
        "choices": [{"index": 0, "message": message, "finish_reason": finish}]
    }
    if usage is not None:
        response["usage"] = usage
    return response


# ---------------------------------------------------------------------------
# Loop guards (R-119)
# ---------------------------------------------------------------------------


@dataclass
class LoopGuard:
    """Stops a turn that repeats itself.

    ``record_call`` returns a reason on the third identical call (same tool,
    same arguments). ``record_failure`` returns a reason when the same call
    fails twice with the same error. The caller then gives the model one
    turn without tools to summarize.
    """

    repeat_limit: int = 3
    failure_limit: int = 2
    _calls: dict[str, int] = field(default_factory=dict)
    _failures: dict[tuple[str, str], int] = field(default_factory=dict)

    @staticmethod
    def key(call: ToolCall) -> str:
        try:
            canonical = dumps_jcs(call.arguments).decode("utf-8")
        except (TypeError, ValueError):
            # Python-style calls can carry sets or bytes, which JSON lacks.
            canonical = repr(sorted(call.arguments.items(), key=lambda kv: kv[0]))
        return call.name + ":" + canonical

    def record_call(self, call: ToolCall) -> str | None:
        key = self.key(call)
        self._calls[key] = self._calls.get(key, 0) + 1
        if self._calls[key] >= self.repeat_limit:
            return (
                f"{call.name} was called {self._calls[key]} times with the same "
                "arguments. RACT stopped the loop and asks the model to summarize."
            )
        return None

    def record_failure(self, call: ToolCall, error: str) -> str | None:
        key = (self.key(call), error.strip())
        self._failures[key] = self._failures.get(key, 0) + 1
        if self._failures[key] >= self.failure_limit:
            return (
                f"{call.name} failed {self._failures[key]} times with the same error. "
                "RACT stopped the loop and asks the model to summarize."
            )
        return None
