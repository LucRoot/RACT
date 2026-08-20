"""Tests for sycophancy_v2 commitment counting + WhispererContract emit."""

from __future__ import annotations

from ract.antilazy.sycophancy_v2 import (
    MIN_COMMITMENT_FLOOR,
    classify,
)
from ract.trace.sink import ListSink, clear_writer, set_writer


class TestCommitmentCounting:
    def test_counts_function_def(self) -> None:
        req = "add a function"
        resp = "```python\ndef f(): return 1\n```"
        r = classify(req, resp)
        # 1 func def + statement_weight (1 return -> 1//3=0)
        assert r.ast_new_commitments >= 1

    def test_counts_class_def(self) -> None:
        req = "add a class"
        resp = "```python\nclass Widget:\n    pass\n```"
        r = classify(req, resp)
        assert r.ast_new_commitments >= 1

    def test_counts_multiple_asserts_as_test(self) -> None:
        req = "test the boundary"
        resp = (
            "```python\n"
            "def test_bounds():\n"
            "    assert f(0) == 0\n"
            "    assert f(1) == 1\n"
            "    assert f(-1) == -1\n"
            "```"
        )
        r = classify(req, resp)
        # 1 func + 3 asserts + statement_weight from asserts
        assert r.ast_new_commitments >= 4

    def test_counts_top_level_assign(self) -> None:
        req = "define a constant"
        resp = "```python\nBUFFER_SIZE = 4096\n```"
        r = classify(req, resp)
        # 1 top-level assign contributes as commitment
        assert r.ast_new_commitments >= 1

    def test_counts_import(self) -> None:
        req = "add the import"
        resp = "```python\nimport hashlib\n```"
        r = classify(req, resp)
        assert r.ast_new_commitments >= 1

    def test_counts_factual_claim_with_number(self) -> None:
        req = "?"
        resp = "The p99 latency is 42 milliseconds and the buffer is 4096 bytes."
        r = classify(req, resp)
        assert r.factual_claim_count >= 1

    def test_counts_factual_claim_with_backtick_token(self) -> None:
        req = "?"
        resp = "The `handle_write` function returns the number of bytes written."
        r = classify(req, resp)
        assert r.factual_claim_count >= 1

    def test_agreement_only_sentence_is_not_a_factual_claim(self) -> None:
        req = "?"
        resp = "You are absolutely right."
        r = classify(req, resp)
        assert r.factual_claim_count == 0

    def test_non_python_block_counts_as_one_opaque_commitment(self) -> None:
        req = "give me the config"
        resp = "```yaml\nname: widget\nversion: 1\n```"
        r = classify(req, resp)
        # Non-python block => top_level_assigns += 1
        assert r.ast_new_commitments >= 1


class TestWhispererContractEvent:
    def setup_method(self) -> None:
        clear_writer()

    def teardown_method(self) -> None:
        clear_writer()

    def test_below_floor_emits_contract_violation(self) -> None:
        sink = ListSink(run_id=b"\x00" * 16)
        set_writer(sink)
        req = "Is my code correct?"
        resp = "You are absolutely right, yes."
        r = classify(req, resp)
        assert r.commitment_count < MIN_COMMITMENT_FLOOR
        r.emit_event()
        kinds = [e.kind for e in sink.events]
        assert "whisperer.contract_violation" in kinds
        # Payload sanity
        event = next(e for e in sink.events if e.kind == "whisperer.contract_violation")
        payload = event.payload
        assert payload["commitment_count"] == r.commitment_count
        assert payload["floor"] == MIN_COMMITMENT_FLOOR
        assert payload["response_excerpt_hash"] == r.response_excerpt_hash
        assert "run_id" in payload
        assert "null_op_score" in payload
        assert payload["used_regex_fallback"] is False

    def test_at_or_above_floor_does_not_emit(self) -> None:
        sink = ListSink(run_id=b"\x00" * 16)
        set_writer(sink)
        req = "Write a validator."
        resp = (
            "Here is the validator:\n"
            "```python\n"
            "def validate(x):\n"
            "    if not isinstance(x, dict):\n"
            "        raise TypeError\n"
            "    if 'id' not in x:\n"
            "        raise ValueError\n"
            "    return True\n"
            "```\n"
            "The isinstance check preserves type safety."
        )
        r = classify(req, resp)
        assert r.commitment_count >= MIN_COMMITMENT_FLOOR
        r.emit_event()
        kinds = [e.kind for e in sink.events]
        assert "whisperer.contract_violation" not in kinds

    def test_emit_never_raises_when_no_writer(self) -> None:
        # No writer registered — emit should silently no-op.
        req = "?"
        resp = "you are right"
        r = classify(req, resp)
        r.emit_event()  # must not raise

    def test_response_excerpt_hash_is_deterministic(self) -> None:
        req = "?"
        resp = "you are absolutely right"
        r1 = classify(req, resp)
        r2 = classify(req, resp)
        assert r1.response_excerpt_hash == r2.response_excerpt_hash
        assert len(r1.response_excerpt_hash) == 16
