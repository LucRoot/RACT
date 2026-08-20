"""Fallback-path tests for sycophancy_v2 when AST parse fails."""

from __future__ import annotations

import logging

from ract.antilazy.sycophancy_v2 import classify


class TestRegexFallback:
    def test_syntax_error_in_python_block_triggers_fallback(
        self, caplog
    ) -> None:
        req = "give me the fix"
        # A python block with a syntax error — ast.parse raises
        # SyntaxError; the classifier degrades to the agreement-
        # decorator matcher.
        resp = "```python\ndef broken(:\n    pass\n```"
        caplog.set_level(logging.DEBUG, logger="ract.antilazy.sycophancy_v2")
        r = classify(req, resp)
        assert r.used_regex_fallback is True
        # DEBUG log must name the fallback path
        assert any(
            "sycophancy_v2 using regex fallback" in rec.message
            for rec in caplog.records
        )

    def test_valid_python_does_not_trigger_fallback(self) -> None:
        req = "give me the fix"
        resp = "```python\ndef ok():\n    return 1\n```"
        r = classify(req, resp)
        assert r.used_regex_fallback is False

    def test_fallback_still_produces_verdict(self) -> None:
        req = "?"
        # broken python + heavy agreement -> still classifies as
        # sycophantic on the null-op-score branch (agreement ratio 1.0).
        resp = (
            "You are absolutely right. My apologies.\n"
            "```python\ndef broken(:\n    pass\n```"
        )
        r = classify(req, resp)
        assert r.used_regex_fallback is True
        assert r.is_sycophantic is True

    def test_fallback_flag_visible_in_event_payload(self) -> None:
        from ract.trace.sink import ListSink, clear_writer, set_writer

        clear_writer()
        sink = ListSink(run_id=b"\x00" * 16)
        set_writer(sink)
        try:
            req = "?"
            resp = "```python\ndef broken(:\npass\n```\nyou are right"
            r = classify(req, resp)
            r.emit_event()
            events = [e for e in sink.events if e.kind == "whisperer.contract_violation"]
            assert events
            assert events[0].payload["used_regex_fallback"] is True
        finally:
            clear_writer()

    def test_fallback_never_raises_on_binary_looking_code(self) -> None:
        req = "?"
        # Not python, non-code language — no fallback since not parsed
        # as python at all.
        resp = "```rust\nfn main() {}\n```"
        r = classify(req, resp)
        # rust block goes through the "non-python opaque commitment"
        # path, not the parse-failure fallback.
        assert r.used_regex_fallback is False
        assert r.ast_new_commitments >= 1
