"""Tests for :mod:`ract.memory.summary` — AST-deterministic chunk
summary body.

Source-spec audit `_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md`
finding 4 (MEDIUM): ``format_chunk(SUMMARY, ...)`` returned
``"summary unavailable"`` when no provider was supplied. Module_05
closes that gap by shipping an AST-deterministic body via
:func:`ract.memory.summary.summarize_chunk_deterministic`. Bonsai-
council model-based summarizer path deferred to v0.6 per ADR-0046.

Gate: `docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md` §5 row
"SUMMARY format returns real content".
"""

from __future__ import annotations

from ract.memory.chunk import Chunk, ChunkFormat, format_chunk
from ract.memory.summary import (
    DOCSTRING_MAX_CHARS,
    MAX_EXTERNAL_CALLS,
    summarize_chunk_deterministic,
)


def _chunk(**overrides) -> Chunk:
    base = dict(
        chunk_id="cid",
        symbol_id=1,
        symbol_name="fn",
        file_path="/repo/mod.py",
        language="python",
        kind="function_body",
        signature="def fn(a, b) -> int:",
        body='def fn(a, b) -> int:\n    """Do a thing.\n\n    Longer text."""\n    return a + b\n',
        content_hash="h",
        token_count=8,
        oversize=False,
        chunk_locator="0/1",
        start_line=1,
        end_line=5,
    )
    base.update(overrides)
    return Chunk(**base)


class TestPythonDeterministicSummary:
    def test_signature_first_line(self) -> None:
        summary = summarize_chunk_deterministic(_chunk())
        assert summary.splitlines()[0] == "def fn(a, b) -> int:"

    def test_docstring_line_present(self) -> None:
        summary = summarize_chunk_deterministic(_chunk())
        assert "doc: Do a thing." in summary

    def test_control_flow_line_present_even_when_none(self) -> None:
        summary = summarize_chunk_deterministic(_chunk())
        assert any(
            line.startswith("control:") for line in summary.splitlines()
        )

    def test_control_flow_counts_for_and_if(self) -> None:
        body = (
            "def loop(items):\n"
            "    total = 0\n"
            "    for x in items:\n"
            "        if x > 0:\n"
            "            total += x\n"
            "    return total\n"
        )
        chunk = _chunk(
            body=body,
            signature="def loop(items) -> int:",
        )
        summary = summarize_chunk_deterministic(chunk)
        control = [
            line for line in summary.splitlines() if line.startswith("control:")
        ][0]
        assert "for=1" in control
        assert "if=1" in control

    def test_calls_line_lists_targets(self) -> None:
        body = (
            "def orchestrate(x):\n"
            "    y = helper(x)\n"
            "    z = other.calc(y)\n"
            "    return combine(y, z)\n"
        )
        chunk = _chunk(body=body, signature="def orchestrate(x):")
        summary = summarize_chunk_deterministic(chunk)
        calls_line = [
            line for line in summary.splitlines() if line.startswith("calls:")
        ][0]
        assert "helper" in calls_line
        assert "other.calc" in calls_line
        assert "combine" in calls_line

    def test_calls_line_caps_at_max_external_calls(self) -> None:
        body_lines = ["def big():"]
        for i in range(MAX_EXTERNAL_CALLS + 20):
            body_lines.append(f"    fn{i}(1)")
        body = "\n".join(body_lines) + "\n"
        chunk = _chunk(body=body, signature="def big():")
        summary = summarize_chunk_deterministic(chunk)
        calls_line = [
            line for line in summary.splitlines() if line.startswith("calls:")
        ][0]
        call_names = calls_line[len("calls: ") :].split(", ")
        assert len(call_names) <= MAX_EXTERNAL_CALLS

    def test_docstring_capped_at_max_chars(self) -> None:
        long_doc = "X" * (DOCSTRING_MAX_CHARS + 200)
        body = f'def x():\n    """{long_doc}"""\n    return 1\n'
        chunk = _chunk(body=body, signature="def x():")
        summary = summarize_chunk_deterministic(chunk)
        doc_line = [
            line for line in summary.splitlines() if line.startswith("doc: ")
        ][0]
        assert len(doc_line) - len("doc: ") <= DOCSTRING_MAX_CHARS

    def test_deterministic_across_calls(self) -> None:
        chunk = _chunk()
        a = summarize_chunk_deterministic(chunk)
        b = summarize_chunk_deterministic(chunk)
        assert a == b


class TestNonPythonHeuristicSummary:
    def test_typescript_regex_control_flow(self) -> None:
        body = (
            "function loop(items: number[]): number {\n"
            "  let total = 0;\n"
            "  for (const x of items) {\n"
            "    if (x > 0) {\n"
            "      total += x;\n"
            "    }\n"
            "  }\n"
            "  return total;\n"
            "}\n"
        )
        chunk = _chunk(
            body=body,
            signature="function loop(items: number[]): number",
            language="typescript",
        )
        summary = summarize_chunk_deterministic(chunk)
        control = [
            line for line in summary.splitlines() if line.startswith("control:")
        ][0]
        assert "for=1" in control
        assert "if=1" in control

    def test_rust_regex_control_flow_and_match(self) -> None:
        body = (
            "fn dispatch(x: i32) -> i32 {\n"
            "    match x {\n"
            "        0 => 0,\n"
            "        _ => x + 1,\n"
            "    }\n"
            "}\n"
        )
        chunk = _chunk(
            body=body,
            signature="fn dispatch(x: i32) -> i32",
            language="rust",
        )
        summary = summarize_chunk_deterministic(chunk)
        control = [
            line for line in summary.splitlines() if line.startswith("control:")
        ][0]
        assert "match=1" in control

    def test_go_regex_control_flow_and_defer(self) -> None:
        body = (
            "func Handle(w Writer) error {\n"
            "\tdefer w.Close()\n"
            "\tfor i := 0; i < 10; i++ {\n"
            "\t\tif i == 5 {\n"
            "\t\t\treturn nil\n"
            "\t\t}\n"
            "\t}\n"
            "\treturn nil\n"
            "}\n"
        )
        chunk = _chunk(
            body=body,
            signature="func Handle(w Writer) error",
            language="go",
        )
        summary = summarize_chunk_deterministic(chunk)
        control = [
            line for line in summary.splitlines() if line.startswith("control:")
        ][0]
        assert "for=1" in control
        assert "defer=1" in control


class TestFormatChunkSummaryReplacement:
    def test_format_chunk_summary_no_longer_returns_placeholder(self) -> None:
        """Direct assertion of the Lens 1C finding 4 closure.

        Before module_05: ``format_chunk(SUMMARY, provider=None)``
        returned ``body="summary unavailable"`` and
        ``summary_pending=True``. After module_05: real content and
        ``summary_pending=False``.
        """
        chunk = _chunk()
        got = format_chunk(chunk, ChunkFormat.SUMMARY)
        assert got.body != "summary unavailable"
        assert "summary unavailable" not in got.body
        assert got.summary_pending is False

    def test_format_chunk_summary_provider_still_wins(self) -> None:
        """v0.6 provider hook (ADR-0046 slot) is preserved."""

        class FakeProvider:
            def summarize(self, chunk_arg: Chunk) -> str:
                return "model-generated: " + chunk_arg.symbol_name

        chunk = _chunk()
        got = format_chunk(chunk, ChunkFormat.SUMMARY, provider=FakeProvider())
        assert got.body == "model-generated: fn"
        assert got.summary_pending is False


class TestSummaryDegenerateCases:
    def test_empty_body_still_emits_control_line(self) -> None:
        chunk = _chunk(body="", signature="def empty():")
        summary = summarize_chunk_deterministic(chunk)
        assert "control: none" in summary

    def test_empty_signature_and_body_produces_control_none_only(
        self,
    ) -> None:
        chunk = _chunk(body="", signature="")
        summary = summarize_chunk_deterministic(chunk)
        assert summary == "control: none"

    def test_partial_parse_body_falls_back_gracefully(self) -> None:
        """Python body that would fail ``ast.parse`` still produces a
        summary via the regex fallback path."""
        body = "for x in items:\n    yield x  # closing brace missing\n)"
        chunk = _chunk(body=body, signature="", language="python")
        summary = summarize_chunk_deterministic(chunk)
        # Just requires we don't crash and we surface a control line.
        assert "control:" in summary


# RACT 0.5.1
