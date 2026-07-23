"""Eval harness runner for RACT."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class EvalResult:
    """Outcome of one eval run."""

    task: str
    provider: str
    passed: bool
    checks: list[dict[str, Any]]
    errors: list[str]
    seed: str
    run_dir: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _mock_run(task_dir: Path, workspace: Path, seed: int) -> None:
    """Deterministic mock agent that makes the minimal edits each task needs."""
    task_name = task_dir.name
    if task_name == "refactor-function":
        src = workspace / "src" / "orders.py"
        if src.is_file():
            src.write_text(
                '"""Order processing module (refactored)."""\n\n'
                "from __future__ import annotations\n\n\n"
                "def _validate_items(items):\n"
                "    if not isinstance(items, list):\n"
                '        raise ValueError("items must be a list")\n'
                "    validated = []\n"
                "    for item in items:\n"
                '        if item["price"] < 0:\n'
                '            raise ValueError("price cannot be negative")\n'
                "        validated.append(item)\n"
                "    return validated\n\n"
                "def _apply_discounts(total, member, coupon):\n"
                "    discounts = 0.0\n"
                "    if member and total > 50.0:\n"
                "        discounts += total * 0.05\n"
                '    if coupon == "SAVE10":\n'
                "        discounts += total * 0.10\n"
                "    return discounts\n\n"
                "def _calculate_tax(taxable, region):\n"
                '    rates = {"US": 0.08, "EU": 0.20, "CA": 0.13}\n'
                "    return taxable * rates.get(region, 0.10)\n\n"
                "def _shipping(total, kind):\n"
                '    if kind == "express":\n'
                "        return 0.0 if total > 200.0 else 15.0\n"
                "    return 0.0 if total > 100.0 else 5.0\n\n"
                "def process_order(raw):\n"
                '    items = _validate_items(raw["items"])\n'
                '    total = sum(i["price"] * i["qty"] for i in items)\n'
                '    discounts = _apply_discounts(total, raw.get("member"), raw.get("coupon"))\n'
                "    taxable = total - discounts\n"
                '    tax = _calculate_tax(taxable, raw.get("region", "US"))\n'
                '    shipping = _shipping(total, raw.get("shipping", "standard"))\n'
                "    return {\n"
                '        "items": items,\n'
                '        "subtotal": round(total, 2),\n'
                '        "discounts": round(discounts, 2),\n'
                '        "tax": round(tax, 2),\n'
                '        "shipping": round(shipping, 2),\n'
                '        "total": round(taxable + tax + shipping, 2),\n'
                '        "region": raw.get("region", "US"),\n'
                '        "member": bool(raw.get("member")),\n'
                "    }\n",
                encoding="utf-8",
            )
    elif task_name == "fastapi-validation":
        src = workspace / "src" / "main.py"
        if src.is_file():
            src.write_text(
                '"""FastAPI app with validation."""\n\n'
                "from __future__ import annotations\n\n"
                "from fastapi import FastAPI, HTTPException, Request\n"
                "from fastapi.exceptions import RequestValidationError\n"
                "from fastapi.responses import JSONResponse\n"
                "from pydantic import BaseModel, EmailStr, Field\n\n"
                "app = FastAPI()\n\n"
                "class UserCreate(BaseModel):\n"
                "    name: str = Field(..., min_length=1)\n"
                "    email: EmailStr\n"
                "    age: int = Field(..., ge=0, le=150)\n\n"
                '@app.post("/users/")\n'
                "def create_user(payload: UserCreate) -> dict:\n"
                '    return {"id": 1, "name": payload.name, "email": payload.email, "age": payload.age}\n'
                "\n"
                "@app.exception_handler(RequestValidationError)\n"
                "async def validation_handler(request: Request, exc: RequestValidationError):\n"
                '    return JSONResponse(status_code=400, content={"detail": exc.errors()})\n',
                encoding="utf-8",
            )
        tests = workspace / "tests" / "test_validation.py"
        tests.write_text(
            '"""Validation tests."""\n\n'
            "from fastapi.testclient import TestClient\n"
            "from main import app\n\n"
            "client = TestClient(app)\n\n"
            "def test_invalid_email_returns_400():\n"
            '    r = client.post("/users/", json={"name": "A", "email": "bad", "age": 30})\n'
            "    assert r.status_code == 400\n\n"
            "def test_negative_age_returns_400():\n"
            '    r = client.post("/users/", json={"name": "A", "email": "a@b.com", "age": -1})\n'
            "    assert r.status_code == 400\n",
            encoding="utf-8",
        )
    elif task_name == "file-watcher":
        watcher = workspace / "watch.py"
        watcher.write_text(
            '"""Simple file watcher."""\n\n'
            "from __future__ import annotations\n\n"
            "import signal\n"
            "import sys\n"
            "import time\n"
            "from pathlib import Path\n\n"
            "running = True\n\n"
            "def _handle_sigint(signum, frame):\n"
            "    global running\n"
            "    running = False\n\n"
            "signal.signal(signal.SIGINT, _handle_sigint)\n"
            'if sys.platform == "win32":\n'
            "    signal.signal(signal.SIGBREAK, _handle_sigint)\n\n"
            'src = Path("src/page.md")\n'
            'out = Path("site/index.html")\n'
            "last = src.stat().st_mtime if src.exists() else 0\n\n"
            "while running:\n"
            "    current = src.stat().st_mtime if src.exists() else 0\n"
            "    if current != last:\n"
            "        last = current\n"
            "        out.parent.mkdir(parents=True, exist_ok=True)\n"
            '        body = src.read_text(encoding="utf-8")\n'
            '        out.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")\n'
            "    time.sleep(0.05)\n",
            encoding="utf-8",
        )


def run_task(task_dir: Path, provider: str = "mock", seed: int = 42) -> EvalResult:
    """Run one eval task and return the result."""
    task_dir = Path(task_dir)
    task_name = task_dir.name
    success_script = task_dir / "success.py"

    with tempfile.TemporaryDirectory(prefix=f"ract-eval-{task_name}-") as tmp:
        workspace = Path(tmp) / "workspace"
        shutil.copytree(task_dir, workspace)

        if provider == "mock":
            _mock_run(task_dir, workspace, seed)

        if not success_script.is_file():
            return EvalResult(
                task=task_name,
                provider=provider,
                passed=False,
                checks=[],
                errors=["success.py not found"],
                seed=str(seed),
            )

        proc = subprocess.run(
            [sys.executable, str(success_script), str(workspace)],
            capture_output=True,
            text=True,
        )
        try:
            outcome = json.loads(proc.stdout)
        except json.JSONDecodeError:
            outcome = {
                "passed": False,
                "checks": [],
                "errors": [proc.stdout, proc.stderr],
            }

        passed = bool(outcome.get("passed", False)) and proc.returncode == 0
        result = EvalResult(
            task=task_name,
            provider=provider,
            passed=passed,
            checks=outcome.get("checks", []),
            errors=outcome.get("errors", []),
            seed=str(seed),
        )

        run_dir = (
            Path("evals/runs") / f"{date.today().isoformat()}-{task_name}-{provider}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        result.run_dir = run_dir
        result.metadata = {
            "task": task_name,
            "provider": provider,
            "seed": seed,
            "passed": passed,
        }

        run_json = run_dir / "run.json"
        run_json.write_text(
            json.dumps(
                {
                    "task": task_name,
                    "provider": provider,
                    "seed": seed,
                    "passed": passed,
                    "checks": outcome.get("checks", []),
                    "errors": outcome.get("errors", []),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        md_lines = [
            f"# Eval Run: {task_name}",
            "",
            f"- **Provider:** {provider}",
            f"- **Seed:** {seed}",
            f"- **Passed:** {passed}",
            "",
            "## Checks",
            "",
        ]
        for check in outcome.get("checks", []):
            status = "✅" if check.get("passed") else "❌"
            md_lines.append(f"- {status} {check.get('name')}")
        if outcome.get("errors"):
            md_lines.extend(["", "## Errors", ""])
            for error in outcome["errors"]:
                md_lines.append(f"- {error}")
        (run_dir / "run.md").write_text("\n".join(md_lines), encoding="utf-8")

        return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the eval runner."""
    argv = argv or sys.argv[1:]
    if not argv:
        print(
            "Usage: python -m ract.eval.runner <task-dir> [--provider mock] [--seed 42]"
        )
        return 1

    task_dir = Path(argv[0])
    provider = "mock"
    seed = 42
    idx = 1
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--provider" and idx + 1 < len(argv):
            provider = argv[idx + 1]
            idx += 2
        elif arg == "--seed" and idx + 1 < len(argv):
            seed = int(argv[idx + 1])
            idx += 2
        else:
            idx += 1

    result = run_task(task_dir, provider=provider, seed=seed)
    print(json.dumps(result.metadata, indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
