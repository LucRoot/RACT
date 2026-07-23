__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
from ract.mutation_merge_gate import MutationMergeGateEngine, MergePolicy


class TestMutationMergeGateEngine:
    def setup_method(self):
        self.policies = [
            MergePolicy(
                id="auth_policy",
                description="Any PR modifying auth logic must raise mutation coverage by 5% or block merge",
                trigger_pattern=r".*auth.*",
                condition="mutation_delta >= 5",
                threshold=5.0,
                action="block",
            ),
            MergePolicy(
                id="core_policy",
                description="Core modules must maintain mutation score above 90",
                trigger_pattern=r".*core.*",
                condition="mutation_score >= 90",
                threshold=90.0,
                action="warn",
            ),
        ]
        self.engine = MutationMergeGateEngine(self.policies)

    def test_policy_not_triggered(self):
        result = self.engine.evaluate(
            "auth_policy", ["src/utils/helper.py"], 80.0, 80.0, 90.0, 90.0
        )
        assert result.passed is True
        assert "not triggered" in result.reason

    def test_policy_triggered_and_passed(self):
        result = self.engine.evaluate(
            "auth_policy", ["src/auth/login.py"], 85.0, 80.0, 95.0, 90.0
        )
        assert result.passed is True
        assert "Condition met" in result.reason
        assert result.receipt is None

    def test_policy_triggered_and_blocked(self):
        result = self.engine.evaluate(
            "auth_policy", ["src/auth/login.py"], 80.0, 80.0, 90.0, 90.0
        )
        assert result.passed is False
        assert "Condition failed" in result.reason
        assert result.receipt is not None
        assert "BLOCKED" in result.receipt

    def test_policy_triggered_and_warned(self):
        result = self.engine.evaluate(
            "core_policy", ["src/core/engine.py"], 80.0, 80.0, 85.0, 90.0
        )
        assert result.passed is False
        assert "Condition failed" in result.reason
        assert result.receipt is None  # Warn action doesn't generate receipt

    def test_invalid_policy_id(self):
        result = self.engine.evaluate(
            "nonexistent_policy", ["src/auth/login.py"], 80.0, 80.0, 90.0, 90.0
        )
        assert result.passed is False
        assert "not found" in result.reason

    def test_invalid_condition_syntax(self):
        bad_policy = MergePolicy(
            id="bad_policy",
            description="Bad condition",
            trigger_pattern=r".*",
            condition="invalid syntax",
            threshold=0.0,
            action="block",
        )
        engine = MutationMergeGateEngine([bad_policy])
        result = engine.evaluate("bad_policy", ["src/file.py"], 80.0, 80.0, 90.0, 90.0)
        assert result.passed is False
        assert "Invalid condition syntax" in result.reason

    def test_evaluate_all(self):
        results = self.engine.evaluate_all(
            ["src/auth/login.py", "src/core/engine.py"], 80.0, 80.0, 90.0, 90.0
        )
        assert len(results) == 2
        auth_result = next(r for r in results if r.policy_id == "auth_policy")
        core_result = next(r for r in results if r.policy_id == "core_policy")
        assert auth_result.passed is False
        assert core_result.passed is False

    def test_receipt_structure(self):
        result = self.engine.evaluate(
            "auth_policy", ["src/auth/login.py"], 80.0, 80.0, 90.0, 90.0
        )
        assert result.receipt is not None
        receipt_data = json.loads(result.receipt)
        assert "policy_id" in receipt_data
        assert "signature" in receipt_data
        assert receipt_data["status"] == "BLOCKED"


class TestMergeGateCli:
    """CLI wiring: 'ract merge-gate' must dispatch and gate correctly."""

    def _policy_file(self, tmp_path, action="block"):
        policy = [
            {
                "id": "cov_guard",
                "description": "coverage must not drop",
                "trigger_pattern": r".*\.py$",
                "condition": "coverage_delta >= 0",
                "threshold": 0.0,
                "action": action,
            }
        ]
        path = tmp_path / "policies.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        return path

    def test_cli_pass_returns_zero(self, tmp_path, capsys):
        from ract.cli import main

        code = main(
            [
                "merge-gate",
                "--policy",
                str(self._policy_file(tmp_path)),
                "--files",
                "src/foo.py",
                "--coverage-current",
                "90",
                "--coverage-previous",
                "88",
            ]
        )
        assert code == 0
        assert "PASS" in capsys.readouterr().out

    def test_cli_blocking_failure_returns_one(self, tmp_path, capsys):
        from ract.cli import main

        code = main(
            [
                "merge-gate",
                "--policy",
                str(self._policy_file(tmp_path)),
                "--files",
                "src/foo.py",
                "--coverage-current",
                "85",
                "--coverage-previous",
                "88",
            ]
        )
        assert code == 1
        assert "FAIL" in capsys.readouterr().out

    def test_cli_warn_action_does_not_block(self, tmp_path):
        from ract.cli import main

        code = main(
            [
                "merge-gate",
                "--policy",
                str(self._policy_file(tmp_path, action="warn")),
                "--files",
                "src/foo.py",
                "--coverage-current",
                "85",
                "--coverage-previous",
                "88",
            ]
        )
        assert code == 0

    def test_cli_missing_policy_file_returns_one(self, tmp_path, capsys):
        from ract.cli import main

        code = main(["merge-gate", "--policy", str(tmp_path / "nope.json")])
        assert code == 1
        assert "not found" in capsys.readouterr().err
