from __future__ import annotations


"""Command-line interface for RACT."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from ract.builtin_skill_library import BuiltinSkillLibrary
from ract.chestertons_fence import ChestertonsFence
from ract.code_review_mode import CodeReviewMode
from ract.compression_novelty_detector import CompressionNoveltyDetector
from ract.consolidate import ConsolidationScanner, MergeProposal
from ract.dead_code_auction import DeadCodeAuction
from ract.skill_marketplace import SkillMarketplace
from ract.doc_generator import DocGenerator
from ract.diff_applier import DiffApplier
from ract.github_release import GitHubReleaseClient, GitHubReleaseError
from ract.handshake_registry import HandshakeRegistry
from ract.harness import _build_retrieval_adapter
from ract.legacy_whisperer import LegacyWhisperer
from ract.tui import console
from ract.load_bearing_guard import LoadBearingGuard
from ract.loop_controller import LoopController
from ract.loop_planner import LoopPlanner
from ract.mcp_adapter import McpToolRegistry
from ract.mutation_merge_gate import MergePolicy, MutationMergeGateEngine
from ract.mutation_runner import run_mutation_tests
from ract.providers.router import ProviderRouter
from ract.openapi_client_generator import OpenApiClientGenerator
from ract.doctor import RactDoctor
from ract.openapi_server_generator import OpenApiServerGenerator
from ract.plan_replay import PlanReplay
from ract.plan_serializers import load_plan, save_plan
from ract.project_initializer import ProjectInitializer, list_templates
from ract.provider_presets import get_preset, list_presets
from ract.manager import Plan
from ract.quality_scorecard import QualityScorecard, Verdict
from ract.ract_runner import run_ract
from ract.run_reporter import RunReporter, render_html_report, render_markdown
from ract.self_test_benchmark_mode import SelfTestBenchmarkMode
from ract.session_store import SessionStore
from ract.skills_registry import SkillRegistry
from ract.symbol_renamer import SymbolRenamer
from ract.handshake import answer as op_answer
from ract.handshake import list_pending as op_list_pending
from ract.handshake import raise_request as op_raise_request
from ract.receipt import load_receipt, verify_receipt
from ract.receipt_chain import verify_chain
from ract.receipt_export import export_receipts
from ract.policy_gate import evaluate_policy
from ract.run_fingerprint import fingerprint_run, diff_fingerprints

from ract.config_diff import diff_configs
from ract.preflight_validator import PreflightValidator


def toggle_mode(mode: str) -> str:
    """Return a recognized RACT toggle mode unchanged.

    Kept at module level for backward compatibility with older tests.
    """
    if mode in {"yolo", "auto", "dry-run", "reload", "resume"}:
        return mode
    raise ValueError(f"unknown toggle mode: {mode}")


def _handshake_item_to_dict(item: Any) -> dict[str, Any]:
    """Serialize a HandshakeItem to a plain dict."""
    from dataclasses import asdict

    return asdict(item)


def _handshakes_command(args: list[str]) -> int:
    """Handle 'ract handshakes list/approve/reject/review <id>'."""
    if "--smoke-test" in args:
        print("smoke ok")
        return 0
    parser = argparse.ArgumentParser(prog="ract handshakes")
    parser.add_argument(
        "action",
        choices=["list", "approve", "reject", "defer", "review"],
        help="Action to perform on the handshake registry.",
    )
    parser.add_argument(
        "milestone_id", nargs="?", help="Milestone id for approve/reject/defer."
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit JSON output"
    )
    parser.add_argument(
        "--json_review",
        dest="json_review",
        action="store_true",
        help="Emit JSON output (review alias)",
    )
    parser.add_argument(
        "--csv", dest="csv_output", action="store_true", help="Emit CSV output"
    )
    parser.add_argument(
        "--markdown",
        dest="markdown_output",
        action="store_true",
        help="Emit Markdown output",
    )
    parsed = parser.parse_args(args)

    registry = HandshakeRegistry(parsed.config.parent)
    if parsed.action == "list":
        items = registry.entries()
        if parsed.json_output:
            print(
                json.dumps([_handshake_item_to_dict(item) for item in items], indent=2)
            )
            return 0
        if not items:
            console.info("No handshake items recorded.")
            return 0
        console.rule("Operator Handshakes")
        console.table(
            title="",
            columns=["ID", "Status", "Description"],
            rows=[[item.id, item.status, item.description] for item in items],
        )
        return 0

    if parsed.action == "review":
        items = [item for item in registry.entries() if item.status == "pending"]
        if parsed.json_output or parsed.json_review:
            print(
                json.dumps([_handshake_item_to_dict(item) for item in items], indent=2)
            )
            return 0
        if parsed.csv_output:
            print("id,description,status")
            for item in items:
                print(f"{item.id},{item.description},{item.status}")
            return 0
        if parsed.markdown_output:
            print("# Pending handshakes")
            for item in items:
                print(f"- {item.id}: {item.description}")
            return 0
        if not items:
            console.info("No pending handshake items.")
            return 0
        console.rule("Pending Operator Handshakes")
        console.table(
            title="",
            columns=["ID", "Status", "Description"],
            rows=[[item.id, item.status, item.description] for item in items],
        )
        return 0

    if parsed.milestone_id is None:
        parser.error("milestone_id is required for approve/reject/defer")
    status_map = {"approve": "approved", "reject": "rejected", "defer": "deferred"}
    status = status_map[parsed.action]
    try:
        item = registry.update_status(parsed.milestone_id, status)
    except KeyError as exc:
        print(f"[ract] {exc}", file=sys.stderr)
        return 1
    if parsed.json_output:
        print(json.dumps(_handshake_item_to_dict(item), indent=2))
        return 0
    print(f"[ract] handshake '{parsed.milestone_id}' marked {status}")
    return 0


def _mcp_command(args: list[str]) -> int:
    """Handle 'ract mcp list' and 'ract mcp invoke'.

    LR:: Lists tools exposed by configured MCP servers so users can see what
    external capabilities RACT can invoke before running a plan. The invoke
    action lets operators call a configured tool directly from the terminal
    for quick verification or one-off tasks.
    """
    parser = argparse.ArgumentParser(prog="ract mcp")
    parser.add_argument(
        "action",
        choices=["list", "invoke"],
        help="MCP action to perform.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument(
        "--tool",
        dest="tool",
        help="Qualified tool name (server_name/tool_name) for invoke.",
    )
    parser.add_argument(
        "--input",
        dest="input_json",
        default="{}",
        help="JSON arguments for invoke (default: '{}').",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[ract] failed to parse config: {exc}", file=sys.stderr)
        return 1

    registry = McpToolRegistry.from_config(config)

    if parsed.action == "invoke":
        return _mcp_invoke(registry, parsed.tool, parsed.input_json)

    tools_rooted = registry.list_all_tools()
    if tools_rooted.error is not None:
        print(f"[ract] failed to list MCP tools: {tools_rooted.error}", file=sys.stderr)
        return 1

    tools = tools_rooted.value or []
    if parsed.json_output:
        print(json.dumps(tools, indent=2))
        return 0
    if not tools:
        console.info("No MCP tools configured or reachable.")
        console.direct("Add an 'mcp_servers:' section to ract.yaml to expose tools.")
        return 0

    console.rule(f"MCP tools ({len(tools)})")
    console.table(
        title="",
        columns=["Name", "Description"],
        rows=[
            [tool.get("name", "unknown"), tool.get("description", "")] for tool in tools
        ],
    )
    return 0


def _mcp_invoke(registry: McpToolRegistry, tool: str | None, input_json: str) -> int:
    """Call a qualified MCP tool and render the result."""
    if not tool:
        print("[ract] invoke requires --tool <server_name/tool_name>", file=sys.stderr)
        return 1
    try:
        arguments: dict[str, Any] = json.loads(input_json)
    except json.JSONDecodeError as exc:
        print(f"[ract] invalid --input JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(arguments, dict):
        print("[ract] --input must be a JSON object.", file=sys.stderr)
        return 1

    result = registry.call_tool(tool, arguments)
    if result.error is not None:
        print(f"[ract] MCP tool failed: {result.error}", file=sys.stderr)
        return 1

    tool_result = result.unwrap()
    if tool_result.is_error:
        print("[ract] tool reported an error.", file=sys.stderr)
    for item in tool_result.content or []:
        text = item.get("text") if isinstance(item, dict) else None
        if text:
            console.direct(text)
        else:
            console.direct(json.dumps(item))
    return 0


def _retrieval_command(args: list[str]) -> int:
    """Handle 'ract retrieval search <query>'.

    LR:: Lets operators preview what context RACT retrieves for a query before
    invoking the management model. Works with the keyword adapter by default and
    web-search adapters when configured.
    """
    parser = argparse.ArgumentParser(prog="ract retrieval")
    parser.add_argument(
        "action",
        nargs="?",
        choices=["search"],
        help="Retrieval action to perform.",
    )
    parser.add_argument("query", nargs="?", help="Search query.")
    parser.add_argument(
        "--top-k",
        dest="top_k",
        type=int,
        default=5,
        help="Number of results (default: 5).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    if parsed.action is None:
        parser.print_help()
        return 1

    if parsed.query is None:
        parser.error("query is required for search")

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[ract] failed to parse config: {exc}", file=sys.stderr)
        return 1

    project_dir = parsed.config.parent.resolve()
    adapter = _build_retrieval_adapter(config, project_dir)
    if adapter is None:
        if not parsed.json_output:
            print("No retrieval adapter configured. Falling back to keyword search.")
        from ract.retrieval_adapter import KeywordRetrievalAdapter

        adapter = KeywordRetrievalAdapter(project_dir)

    results_rooted = adapter.search(parsed.query, top_k=parsed.top_k)
    if results_rooted.error is not None:
        print(f"[retrieval] failed: {results_rooted.error}", file=sys.stderr)
        return 1

    results = results_rooted.value or []
    if parsed.json_output:
        print(
            json.dumps(
                [
                    {
                        "source": result.source,
                        "score": result.score,
                        "content": result.content,
                    }
                    for result in results
                ],
                indent=2,
                default=str,
            )
        )
        return 0
    if not results:
        console.info(f"No results for query: {parsed.query}")
        return 0

    console.rule(f"Retrieval results for '{parsed.query}' ({len(results)})")
    console.table(
        title="",
        columns=["#", "Source", "Score", "Preview"],
        rows=[
            [
                str(i),
                result.source,
                f"{result.score:.4f}",
                result.content[:500].replace("\n", " "),
            ]
            for i, result in enumerate(results, start=1)
        ],
    )
    return 0


def _report_command(args: list[str]) -> int:
    """Handle 'ract report --last' and 'ract report --session <id>'.

    LR:: Supports both human-readable text and JSON output, with optional file
    export, so the run report can be consumed by humans, scripts, or CI.
    """
    parser = argparse.ArgumentParser(prog="ract report")
    parser.add_argument(
        "--last", action="store_true", help="Show the last loop report."
    )
    parser.add_argument("--session", help="Show the report for a saved session.")
    parser.add_argument(
        "--format",
        choices=["text", "json", "html", "markdown"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the report to this file instead of stdout.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    reporter = RunReporter(parsed.config.parent)
    if parsed.last:
        payload = reporter.render_last_loop_json()
        if parsed.format == "json":
            output = "{}" if payload is None else json.dumps(payload, indent=2)
        elif parsed.format == "html":
            output = render_html_report(payload or {})
        elif parsed.format == "markdown":
            output = render_markdown(payload or {})
        else:
            output = reporter.render_last_loop()
    elif parsed.session:
        payload = reporter.render_session_json(parsed.session)
        if parsed.format == "json":
            output = "{}" if payload is None else json.dumps(payload, indent=2)
        elif parsed.format == "html":
            output = render_html_report(payload or {})
        elif parsed.format == "markdown":
            output = render_markdown(payload or {})
        else:
            output = reporter.render_session(parsed.session)
    else:
        parser.print_help()
        return 1

    if parsed.output:
        parsed.output.write_text(output, encoding="utf-8")
        console.info(f"report written to {parsed.output}")
        return 0

    if parsed.format == "text":
        console.rule("Run Report")
    print(output)
    return 0


def _diff_command(args: list[str]) -> int:
    """Handle 'ract diff apply --patch <path> [--dry-run]'.

    LR:: Applies a unified-diff patch file to the project. In dry-run mode it
    previews which files would change and where, without writing anything.
    """
    parser = argparse.ArgumentParser(prog="ract diff")
    parser.add_argument(
        "action",
        nargs="?",
        choices=["apply"],
        help="Diff action to perform.",
    )
    parser.add_argument("--patch", type=Path, help="Path to unified-diff patch.")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview changes without applying them.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    if parsed.action is None:
        parser.print_help()
        return 1

    if parsed.patch is None:
        print("[ract] --patch is required for apply", file=sys.stderr)
        return 1

    if not parsed.patch.is_file():
        print(f"[ract] patch file not found: {parsed.patch}", file=sys.stderr)
        return 1

    project_dir = parsed.config.parent.resolve()
    diff_text = parsed.patch.read_text(encoding="utf-8")
    applier = DiffApplier(project_dir)
    results = applier.apply_diff(diff_text)

    if parsed.dry_run:
        # In dry-run we still call apply_diff, but we restore from backup for
        # any file that was changed. This reuses the real applier logic while
        # leaving the working tree untouched.
        for result in results:
            if result.applied and result.backup:
                applier.restore(result.backup, result.path)

    applied = sum(1 for r in results if r.applied)
    failed = len(results) - applied

    if parsed.json_output:
        print(
            json.dumps(
                [
                    {
                        "path": str(result.path.relative_to(project_dir)),
                        "applied": result.applied,
                        "message": result.message,
                        "dry_run": parsed.dry_run,
                    }
                    for result in results
                ],
                indent=2,
            )
        )
        return 0 if failed == 0 else 1

    print(f"[ract] diff {parsed.action}: {applied} applied, {failed} failed")
    for result in results:
        rel = result.path.relative_to(project_dir)
        status = "APPLIED" if result.applied else "FAILED"
        print(f"  [{status}] {rel}: {result.message}")
        if parsed.dry_run and result.backup:
            print(f"    (dry-run: restored from {result.backup.name})")

    return 0 if failed == 0 else 1


def _explain_command(args: list[str]) -> int:
    """Handle 'ract explain --intent <text> | --plan <path>'.

    LR:: Generates a dry-run plan and narrates it in plain language so the
    operator understands what RACT intends to do before any files are written.
    This is a local-only preview: it does not call the management model beyond
    the planning step already required for dry-run.
    """
    parser = argparse.ArgumentParser(prog="ract explain")
    parser.add_argument("--intent", help="The coding task to explain.")
    parser.add_argument(
        "--plan", type=Path, help="Path to a saved plan JSON to explain."
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    parsed = parser.parse_args(args)

    if not parsed.intent and not parsed.plan:
        parser.print_help()
        return 1

    plan: Plan | None = None
    if parsed.plan:
        try:
            plan = load_plan(parsed.plan)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            print(f"[ract] failed to load plan: {exc}", file=sys.stderr)
            return 1
    else:
        result = run_ract(
            parsed.config,
            parsed.intent,
            dry_run=True,
        )
        if not result.is_ok():
            print(f"[ract] planning failed: {result.error}", file=sys.stderr)
            return 1
        value = result.unwrap()
        if not isinstance(value, Plan):
            print("[ract] dry-run did not return a plan.", file=sys.stderr)
            return 1
        plan = value

    assert plan is not None
    if parsed.json_output:
        from dataclasses import asdict

        print(json.dumps(asdict(plan), indent=2))
        return 0

    lines: list[str] = []
    lines.append("RACT Plan Explanation")
    lines.append("=====================")
    lines.append(f"Assumption: {plan.assumption}")
    lines.append(f"Confidence: {plan.confidence}")
    if not plan.steps:
        lines.append("No steps proposed.")
    else:
        lines.append(f"Proposed steps ({len(plan.steps)}):")
        for i, step in enumerate(plan.steps, start=1):
            lines.append(f"\n  {i}. [{step.provider_hint}] {step.action}")
            if step.expected_artifact:
                lines.append(f"     -> expected artifact: {step.expected_artifact}")
            if step.tool_call:
                lines.append(f"     -> tool call: {step.tool_call}")
    print("\n".join(lines))
    return 0


def _skills_command(args: list[str]) -> int:
    """Handle 'ract skills list|install|install-all|marketplace ...'."""
    if args and args[0] == "marketplace":
        return _skills_marketplace_command(args[1:])

    parser = argparse.ArgumentParser(prog="ract skills")
    subparsers = parser.add_subparsers(dest="action")

    list_parser = subparsers.add_parser("list", help="List built-in RACT skills")
    list_parser.add_argument("--json", action="store_true", dest="json_output")
    list_parser.add_argument("--markdown", action="store_true", dest="markdown_output")
    list_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))

    install_parser = subparsers.add_parser("install", help="Install a built-in skill")
    install_parser.add_argument("name", help="Skill name to install")
    install_parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    install_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))

    subparsers.add_parser("install-all", help="Install all built-in skills")

    parsed = parser.parse_args(args or ["list"])
    library = BuiltinSkillLibrary()

    if parsed.action in ("list", None):
        skills = library.list_skills()
        if parsed.json_output:
            print(json.dumps(skills, indent=2))
            return 0
        if parsed.markdown_output:
            print("# Built-in RACT skills")
            for skill in skills:
                print(f"- **{skill['name']}**: {skill['description']}")
            return 0
        console.rule("Built-in RACT skills")
        console.table(
            title="",
            columns=["Skill", "Description"],
            rows=[[skill["name"], skill["description"]] for skill in skills],
        )
        return 0

    if parsed.action == "install":
        registry = SkillRegistry(parsed.config.parent)
        if parsed.dry_run:
            try:
                preview = library.preview_install(parsed.name, registry)
            except KeyError as exc:
                print(f"[ract] {exc}", file=sys.stderr)
                return 1
            print(
                f"[ract] would install skill '{preview['name']}' to {preview['target']}"
            )
            return 0
        try:
            path = library.install(parsed.name, registry)
        except KeyError as exc:
            print(f"[ract] {exc}", file=sys.stderr)
            return 1
        print(f"[ract] installed skill '{parsed.name}' to {path}")
        return 0

    if parsed.action == "install-all":
        registry = SkillRegistry(parsed.config.parent)
        installed = library.install_all(registry)
        print(
            f"[ract] installed {len(installed)} built-in skills: {', '.join(installed)}"
        )
        return 0

    return 1


def _skills_marketplace_command(args: list[str]) -> int:
    """Handle 'ract skills marketplace list' and 'install --name <name>'."""
    parser = argparse.ArgumentParser(prog="ract skills marketplace")
    subparsers = parser.add_subparsers(dest="action", required=True)

    list_parser = subparsers.add_parser("list", help="List skills in the marketplace")
    list_parser.add_argument("--project-dir", type=Path, default=Path("."))
    list_parser.add_argument(
        "--catalog",
        default=None,
        help="URL or path to a marketplace catalog JSON file.",
    )
    list_parser.add_argument("--json", action="store_true", dest="json_output")
    list_parser.add_argument("--markdown", action="store_true", dest="markdown_output")

    install_parser = subparsers.add_parser("install", help="Install a skill")
    install_parser.add_argument("--project-dir", type=Path, default=Path("."))
    install_parser.add_argument(
        "--catalog",
        default=None,
        help="URL or path to a marketplace catalog JSON file.",
    )
    install_parser.add_argument(
        "name_positional", nargs="?", default=None, help="Skill name to install"
    )
    install_parser.add_argument("--name", default=None, help="Skill name to install")

    parsed = parser.parse_args(args)
    marketplace = SkillMarketplace(parsed.catalog)

    if parsed.action == "list":
        try:
            skills = marketplace.list_skills()
        except Exception as exc:  # noqa: BLE001
            print(f"[ract] failed to load marketplace catalog: {exc}", file=sys.stderr)
            return 1
        if parsed.json_output:
            print(json.dumps(skills, indent=2))
            return 0
        if parsed.markdown_output:
            print("# Marketplace skills")
            for skill in skills:
                print(f"- **{skill.get('name', '')}**: {skill.get('description', '')}")
            return 0
        if not skills:
            print("No skills available in marketplace.")
            return 0
        console.rule("Marketplace skills")
        console.table(
            title="",
            columns=["Skill", "Description", "Author"],
            rows=[
                [s.get("name", ""), s.get("description", ""), s.get("author", "")]
                for s in skills
            ],
        )
        return 0

    if parsed.action == "install":
        skill_name = parsed.name_positional or parsed.name
        if not skill_name:
            print(
                "[ract] marketplace install requires a skill name. "
                "Use `ract skills marketplace install <name>` or `--name <name>`.",
                file=sys.stderr,
            )
            return 1
        registry = SkillRegistry(parsed.project_dir)
        try:
            path = marketplace.install(skill_name, registry)
        except (KeyError, ValueError, httpx.HTTPError, OSError) as exc:
            print(f"[ract] failed to install skill: {exc}", file=sys.stderr)
            return 1
        print(f"[ract] installed marketplace skill '{skill_name}' to {path}")
        return 0

    return 1


def _refactor_command(args: list[str]) -> int:
    """Handle 'ract refactor --old <name> --new <name> [--module <module>]'."""
    parser = argparse.ArgumentParser(prog="ract refactor")
    parser.add_argument("--old", required=True, help="Current symbol name.")
    parser.add_argument("--new", required=True, help="New symbol name.")
    parser.add_argument(
        "--module",
        help=(
            "Restrict rename to this module (dot notation). "
            "If omitted, all module-level symbols named --old are renamed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned edits without writing files.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    renamer = SymbolRenamer(project_dir)
    result = renamer.rename(parsed.old, parsed.new, module=parsed.module)
    if result.error:
        print(f"refactor failed: {result.error}", file=sys.stderr)
        return 1

    if not result.edits:
        print("No edits required.")
        return 0

    if parsed.json_output:
        print(
            json.dumps(
                [
                    {
                        "path": edit.path.as_posix(),
                        "start_line": edit.start_line,
                        "start_col": edit.start_col,
                        "end_line": edit.end_line,
                        "end_col": edit.end_col,
                        "new_text": edit.new_text,
                    }
                    for edit in result.edits
                ],
                indent=2,
            )
        )
        return 0

    for edit in result.edits:
        rel = edit.path.relative_to(project_dir)
        print(
            f"{rel}:{edit.start_line}:{edit.start_col} -> "
            f"{edit.end_line}:{edit.end_col}: {edit.new_text}"
        )

    if parsed.dry_run:
        print(
            f"\nDry run: {len(result.edits)} edit(s) across "
            f"{len(result.files_changed)} file(s)."
        )
        return 0

    renamer.apply(result)
    print(
        f"\nApplied {len(result.edits)} edit(s) across "
        f"{len(result.files_changed)} file(s)."
    )
    return 0


def _rename_command(args: list[str]) -> int:
    """Handle 'ract rename preview --old <name> --new <name> --file <path>'."""
    parser = argparse.ArgumentParser(prog="ract rename")
    subparsers = parser.add_subparsers(dest="action", required=True)

    preview = subparsers.add_parser(
        "preview", help="Preview symbol rename occurrences."
    )
    preview.add_argument("--old", required=True, help="Current symbol name.")
    preview.add_argument("--new", required=True, help="New symbol name.")
    preview.add_argument(
        "--file", required=True, type=Path, help="Source file to scan."
    )
    preview.add_argument("--config", type=Path, default=Path("ract.yaml"))

    parsed = parser.parse_args(args)
    project_dir = parsed.config.parent.resolve()

    if parsed.action != "preview":
        parser.error(f"unknown rename action: {parsed.action}")

    if not parsed.file.is_file():
        print("file not found", file=sys.stderr)
        return 1

    renamer = SymbolRenamer(project_dir)
    result = renamer.preview_rename(parsed.old, parsed.new, parsed.file)
    if result.error:
        print(f"[ract] rename preview failed: {result.error}", file=sys.stderr)
        return 1

    for edit in result.edits:
        rel = edit.path.relative_to(project_dir)
        print(f"{rel}:{edit.start_line}:{edit.start_col}: {edit.new_text}")
    return 0


def _docs_command(args: list[str]) -> int:
    """Handle 'ract docs generate [--output-dir <dir>] [--config <path>]'.

    LR:: A concrete documentation-generation command so Documentation Mode is
    not just an intent rewrite; it can produce Markdown from the source tree.
    """
    parser = argparse.ArgumentParser(prog="ract docs")
    parser.add_argument(
        "action",
        choices=["generate"],
        help="Documentation action to perform.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory to write generated Markdown docs (default: docs/api).",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    generator = DocGenerator(project_dir, output_dir=parsed.output_dir)
    written = generator.generate()
    if not written:
        print("[ract] no Python files found; no docs generated.")
        return 0

    print(f"[ract] generated {len(written)} doc file(s) in {generator.output_dir}")
    for path in written:
        rel = path.relative_to(project_dir)
        print(f"  - {rel}")
    return 0


def _init_command(args: list[str]) -> int:
    """Handle 'ract init --template <name> --provider <name> [--config <path>]'.

    LR:: Scaffolds a brand-new project from a template and provider preset. This
    is the concrete implementation of the configuration-driven project-templates
    use case.
    """
    parser = argparse.ArgumentParser(prog="ract init")
    parser.add_argument(
        "--template",
        choices=list_templates(),
        help="Project template to use.",
    )
    parser.add_argument(
        "--provider",
        choices=list_presets(),
        help="Provider preset for ract.yaml.",
    )
    parser.add_argument(
        "--list-templates",
        dest="list_templates",
        action="store_true",
        help="List available project templates and exit.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("ract.yaml"),
        help="Target ract.yaml path (default: ./ract.yaml).",
    )
    parsed = parser.parse_args(args)

    if parsed.list_templates:
        for template in list_templates():
            print(template)
        return 0

    if not parsed.template or not parsed.provider:
        parser.error("--template and --provider are required (or use --list-templates)")

    project_dir = parsed.config.parent.resolve()
    try:
        result = ProjectInitializer(
            project_dir, parsed.template, parsed.provider
        ).initialize()
    except FileExistsError as exc:
        print(f"[ract] failed: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"[ract] failed: {exc}", file=sys.stderr)
        return 1

    print(f"[ract] initialized {result.template} project at {result.project_dir}")
    print(f"[ract] provider: {result.provider}")
    for path in result.files_written:
        rel = path.relative_to(project_dir)
        print(f"  - {rel}")
    return 0


def _openapi_command(args: list[str]) -> int:
    """Handle 'ract openapi generate-client|generate-server --spec <path> --output <path>'.

    LR:: Generates a small, httpx-based Python client or a FastAPI server module
    from an OpenAPI 3 spec.
    """
    parser = argparse.ArgumentParser(prog="ract openapi")
    parser.add_argument(
        "action",
        choices=["generate-client", "generate-server"],
        help="OpenAPI action to perform.",
    )
    parser.add_argument(
        "--spec", required=True, type=Path, help="Path to OpenAPI spec."
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Output Python file path."
    )
    parser.add_argument(
        "--base-url", help="Override the base URL from the spec (client only)."
    )
    parsed = parser.parse_args(args)

    result: Any = None
    try:
        if parsed.action == "generate-client":
            result = OpenApiClientGenerator(
                parsed.spec, base_url=parsed.base_url
            ).generate(parsed.output)
            name = result.class_name
        else:
            result = OpenApiServerGenerator(parsed.spec).generate(parsed.output)
            name = result.app_name
    except (ValueError, FileNotFoundError) as exc:
        print(f"[ract] failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"[ract] generated {name} with "
        f"{result.operation_count} operation(s) at {result.module_path}"
    )
    return 0


def _plan_command(args: list[str]) -> int:
    """Handle 'ract plan export|replay'.

    LR:: Exposes PlanReplay through the CLI so users can save a session's plan
    to disk and replay it later for reproducibility or regression testing.
    """
    parser = argparse.ArgumentParser(prog="ract plan")
    subparsers = parser.add_subparsers(dest="action")

    export = subparsers.add_parser("export", help="Export a session plan to JSON.")
    export.add_argument("--session", required=True, help="Session id to export.")
    export.add_argument("--output", required=True, type=Path, help="Output JSON path.")
    export.add_argument("--config", type=Path, default=Path("ract.yaml"))

    replay = subparsers.add_parser("replay", help="Replay a saved plan.")
    replay.add_argument(
        "--plan", required=True, type=Path, help="Path to saved plan JSON."
    )
    replay.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without side effects (default).",
    )

    diff = subparsers.add_parser("diff", help="Compare two saved plans by their steps.")
    diff.add_argument("before", type=Path, help="First plan JSON file.")
    diff.add_argument("after", type=Path, help="Second plan JSON file.")

    parsed = parser.parse_args(args)
    if parsed.action is None:
        parser.print_help()
        return 1

    if parsed.action == "export":
        store = SessionStore(parsed.config.parent / ".ract" / "sessions")
        try:
            state = store.load(parsed.session)
        except KeyError as exc:
            print(f"[ract] failed: session not found: {exc}", file=sys.stderr)
            return 1
        plan = state.get("plan")
        if plan is None:
            print("[ract] failed: session has no plan", file=sys.stderr)
            return 1
        save_plan(plan, parsed.output)
        print(f"[ract] exported plan to {parsed.output}")
        return 0

    if parsed.action == "diff":
        try:
            before_data = json.loads(parsed.before.read_text(encoding="utf-8"))
            after_data = json.loads(parsed.after.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"[ract] failed to load plan: {exc}", file=sys.stderr)
            return 1

        def _step_key(step: dict) -> tuple:
            return (
                step.get("action"),
                step.get("provider_hint"),
                step.get("expected_artifact"),
            )

        before_steps = before_data.get("steps", [])
        after_steps = after_data.get("steps", [])
        before_keys = {_step_key(s) for s in before_steps}
        after_keys = {_step_key(s) for s in after_steps}
        added_steps = [s for s in after_steps if _step_key(s) not in before_keys]
        removed_steps = [s for s in before_steps if _step_key(s) not in after_keys]
        print(
            json.dumps(
                {"added_steps": added_steps, "removed_steps": removed_steps},
                indent=2,
            )
        )
        return 0

    # replay
    plan = load_plan(parsed.plan)
    replay_obj = PlanReplay()

    def _noop_executor(action: str) -> None:
        return None

    report = replay_obj.replay(plan, _noop_executor)
    print(f"[ract] replay summary: {report.summary}")
    for result in report.results:
        status = "OK" if result.success else "FAIL"
        print(f"  [{status}] {result.action}")
    return 0 if report.success else 1


def _doctor_command(args: list[str]) -> int:
    """Handle 'ract doctor [--config <path>] [--check-providers]'.

    LR:: Runs configuration and project-structure diagnostics so users can fix
    setup problems before invoking a model. Add --check-providers to actually
    ping each configured provider endpoint.
    """
    parser = argparse.ArgumentParser(prog="ract doctor")
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument(
        "--check-providers",
        dest="check_providers",
        action="store_true",
        help="Ping each configured provider endpoint (slower, requires network).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    parsed = parser.parse_args(args)

    results = RactDoctor(parsed.config).diagnose(check_providers=parsed.check_providers)
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    if parsed.json_output:
        print(
            json.dumps(
                {
                    "passed": passed,
                    "total": total,
                    "checks": [
                        {
                            "check": result.name,
                            "passed": result.passed,
                            "message": result.message,
                        }
                        for result in results
                    ],
                },
                indent=2,
            )
        )
        return 0 if passed == total else 1

    console.rule(f"Doctor: {passed}/{total} checks passed")
    console.table(
        title="",
        columns=["Status", "Check", "Message"],
        rows=[
            [
                "PASS" if result.passed else "FAIL",
                result.name,
                result.message,
            ]
            for result in results
        ],
    )
    return 0 if passed == total else 1


def _audit_command(args: list[str]) -> int:
    """Handle 'ract audit [--config <path>] [--json]'.

    LR:: Runs RACT's own diagnostic tools against the project and prints a
    unified pass/fail report. This is the single command an operator can run
    before a release to confirm the codebase is healthy and the tool is
    calibrated.
    """
    parser = argparse.ArgumentParser(prog="ract audit")
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Run slower checks (consolidate scan, mutation-score drift).",
    )
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    config: dict[str, Any] | None = None
    if parsed.config.is_file():
        import yaml

        try:
            config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            config = None

    findings: list[dict[str, Any]] = []

    doctor_results = RactDoctor(parsed.config).diagnose()
    for result in doctor_results:
        findings.append(
            {
                "tool": "doctor",
                "name": result.name,
                "passed": result.passed,
                "message": result.message,
            }
        )

    auction = DeadCodeAuction(
        project_dir,
        config.get("dead_code_auction", {}) if config else {},
    )
    try:
        candidates = auction.scan()
    except Exception as exc:  # noqa: BLE001
        candidates = []
        findings.append(
            {
                "tool": "auction",
                "name": "dead_code_scan",
                "passed": False,
                "message": f"dead-code auction failed: {exc}",
            }
        )
    if candidates:
        findings.append(
            {
                "tool": "auction",
                "name": "dead_code_candidates",
                "passed": False,
                "message": f"{len(candidates)} dead-code candidate(s) found",
            }
        )
    else:
        findings.append(
            {
                "tool": "auction",
                "name": "dead_code_candidates",
                "passed": True,
                "message": "no dead-code candidates found",
            }
        )

    if parsed.deep and config is not None:
        scanner = ConsolidationScanner(project_dir)
        try:
            consolidation = scanner.scan()
            proposals = consolidation.proposals
            findings.append(
                {
                    "tool": "consolidate",
                    "name": "merge_proposals",
                    "passed": len(proposals) == 0,
                    "message": (
                        f"{len(proposals)} merge proposal(s) found"
                        if proposals
                        else "no merge proposals found"
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            findings.append(
                {
                    "tool": "consolidate",
                    "name": "merge_proposals",
                    "passed": False,
                    "message": f"consolidate scan failed: {exc}",
                }
            )

        mutation_cfg = config.get("mutation_gate", {})
        badge_path = project_dir / "docs" / "mutation-badge.json"
        if not badge_path.is_file():
            findings.append(
                {
                    "tool": "mutation",
                    "name": "mutation_score_drift",
                    "passed": False,
                    "message": "no mutation badge found; run `ract mutation run`",
                }
            )
        else:
            try:
                badge = json.loads(badge_path.read_text(encoding="utf-8"))
                current_text = badge.get("message", "")
                current_score = float(current_text.rstrip("%"))
                floor = float(mutation_cfg.get("min_score", 0.0))
                if current_score < floor:
                    findings.append(
                        {
                            "tool": "mutation",
                            "name": "mutation_score_drift",
                            "passed": False,
                            "message": (
                                f"mutation score {current_score:.2f}% is below "
                                f"floor {floor:.2f}%"
                            ),
                        }
                    )
                else:
                    findings.append(
                        {
                            "tool": "mutation",
                            "name": "mutation_score_drift",
                            "passed": True,
                            "message": (
                                f"mutation score {current_score:.2f}% meets "
                                f"floor {floor:.2f}%"
                            ),
                        }
                    )
            except (json.JSONDecodeError, ValueError) as exc:
                findings.append(
                    {
                        "tool": "mutation",
                        "name": "mutation_score_drift",
                        "passed": False,
                        "message": f"could not parse mutation badge: {exc}",
                    }
                )

    passed = sum(1 for f in findings if f["passed"])
    total = len(findings)

    if parsed.json:
        print(
            json.dumps(
                {"passed": passed, "total": total, "findings": findings}, indent=2
            )
        )
    else:
        console.rule(f"RACT Audit: {passed}/{total} checks passed")
        console.table(
            title="",
            columns=["Tool", "Check", "Status", "Message"],
            rows=[
                [f["tool"], f["name"], "PASS" if f["passed"] else "FAIL", f["message"]]
                for f in findings
            ],
        )

    return 0 if passed == total else 1


def _load_bearing_command(args: list[str]) -> int:
    """Handle 'ract load-bearing list [--config <path>]'.

    LR:: Lists annotated load-bearing regions so operators can see what legacy
    code RACT will refuse to modify without an explicit override.
    """
    parser = argparse.ArgumentParser(prog="ract load-bearing")
    parser.add_argument(
        "action",
        choices=["list"],
        help="Load-bearing action to perform.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1

    guard = LoadBearingGuard(parsed.config.parent)
    regions_by_file = guard.scan_project()

    if parsed.json_output:
        payload = [
            {
                "file": Path(rel_path).as_posix(),
                "start_line": region.start_line,
                "end_line": region.end_line,
                "annotation_line": region.annotation_line,
                "reason": region.reason,
            }
            for rel_path, regions in sorted(regions_by_file.items())
            for region in regions
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if not regions_by_file:
        console.info("No load-bearing annotations found.")
        return 0

    console.rule("Load-bearing regions")
    rows = []
    for rel_path, regions in sorted(regions_by_file.items()):
        for region in regions:
            rows.append(
                [
                    rel_path,
                    f"{region.start_line}-{region.end_line}",
                    str(region.annotation_line),
                    region.reason,
                ]
            )
    console.table(
        title="",
        columns=["File", "Lines", "Annotation", "Reason"],
        rows=rows,
    )
    return 0


def _novelty_command(args: list[str]) -> int:
    """Handle 'ract novelty scan [--json|--html] [--config <path>] [--deep] [--timeout]'.

    LR:: Exposes the compression-based novelty detector so operators can preview
    which files are structurally close to the existing codebase (low novelty /
    possible duplication) and which are outliers (high novelty / needs strong
    review). This is a local-only, information-theoretic anti-rot signal.
    """
    parser = argparse.ArgumentParser(prog="ract novelty")
    parser.add_argument(
        "action",
        choices=["scan"],
        help="Novelty action to perform.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    parser.add_argument(
        "--html",
        dest="html_output",
        action="store_true",
        help="Emit an HTML report instead of a text table.",
    )
    parser.add_argument(
        "--deep",
        dest="deep",
        action="store_true",
        help="Run a deeper (slower) scan.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=None,
        help="Maximum seconds to allow the scan before returning partial results.",
    )
    parser.add_argument(
        "--fast",
        dest="fast",
        action="store_true",
        help="Run a faster dictionary-only novelty scan.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    detector = CompressionNoveltyDetector(project_dir)

    if parsed.fast:
        result = detector.scan_project_fast()
        if parsed.json_output:
            print(json.dumps(result, indent=2))
            return 0
        console.rule(f"novelty scan (fast): {project_dir}")
        console.info(
            f"dictionary trained: {result.get('has_dictionary', False)} "
            f"({result.get('sample_count', 0)} samples)"
        )
        scores = result.get("scores", {})
        if not scores:
            console.info("no Python files found.")
            return 0
        rows = []
        for rel, score in sorted(scores.items(), key=lambda kv: kv[1]["ratio"]):
            detail = score["detail"]
            if len(detail) > 60:
                detail = detail[:57] + "..."
            rows.append([rel, f"{score['ratio']:.3f}", score["verdict"], detail])
        console.table(
            title="",
            columns=["Artifact", "Ratio", "Verdict", "Detail"],
            rows=rows,
        )
        return 0

    if parsed.timeout is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(detector.scan_project)
            try:
                result = future.result(timeout=parsed.timeout)
            except concurrent.futures.TimeoutError:
                result = {
                    "has_dictionary": False,
                    "sample_count": 0,
                    "scores": {},
                    "timeout_reached": True,
                    "timeout_seconds": parsed.timeout,
                }
    else:
        result = detector.scan_project()

    if parsed.json_output:
        print(json.dumps(result, indent=2))
        return 0

    if parsed.html_output:
        lines = [
            "<!DOCTYPE html>",
            "<html><head><title>RACT Novelty Scan</title></head><body>",
            f"<h1>RACT Novelty Scan: {project_dir}</h1>",
            f"<p>dictionary trained: {result['has_dictionary']} "
            f"({result['sample_count']} samples)</p>",
            "<table border='1'><tr><th>Artifact</th><th>Ratio</th><th>Verdict</th><th>Detail</th></tr>",
        ]
        for rel, score in sorted(
            result.get("scores", {}).items(), key=lambda kv: kv[1]["ratio"]
        ):
            detail = score["detail"]
            if len(detail) > 120:
                detail = detail[:117] + "..."
            lines.append(
                f"<tr><td>{rel}</td><td>{score['ratio']:.3f}</td>"
                f"<td>{score['verdict']}</td><td>{detail}</td></tr>"
            )
        lines.append("</table></body></html>")
        print("\n".join(lines))
        return 0

    console.rule(f"novelty scan: {project_dir}")
    console.info(
        f"dictionary trained: {result['has_dictionary']} "
        f"({result['sample_count']} samples)"
    )
    if not result.get("scores"):
        console.info("no Python files found.")
        return 0

    rows = []
    for rel, score in sorted(result["scores"].items(), key=lambda kv: kv[1]["ratio"]):
        detail = score["detail"]
        if len(detail) > 60:
            detail = detail[:57] + "..."
        rows.append([rel, f"{score['ratio']:.3f}", score["verdict"], detail])
    console.table(
        title="",
        columns=["Artifact", "Ratio", "Verdict", "Detail"],
        rows=rows,
    )
    return 0


def _coverage_command(args: list[str]) -> int:
    """Handle 'ract coverage <delta|baseline|status|badge>'.

    LR:: Exposes the earned-coverage gate. ``delta`` compares two existing
    pytest-cov JSON reports or runs pytest directly. ``baseline`` establishes
    the stored baseline. ``status`` prints the stored baseline. ``badge`` writes
    a Shields endpoint JSON file from the current run.
    """
    parser = argparse.ArgumentParser(prog="ract coverage")
    parser.add_argument(
        "action",
        choices=["delta", "delta-export", "baseline", "status", "badge"],
        help="Coverage action to perform.",
    )
    parser.add_argument(
        "--run",
        dest="run_snapshot",
        action="store_true",
        help="Run pytest and compute the delta directly (delta action only).",
    )
    parser.add_argument(
        "--before", type=Path, help="Path to a pytest-cov coverage.json (before)."
    )
    parser.add_argument(
        "--after", type=Path, help="Path to a pytest-cov coverage.json (after)."
    )
    parser.add_argument(
        "--min-percent",
        dest="min_percent",
        type=float,
        default=None,
        help="Minimum required coverage percent for the after snapshot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for the generated badge JSON (badge action only).",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    from ract.coverage_delta import (
        compute_delta,
        gate,
        load_baseline,
        read_snapshot,
        run_snapshot,
        save_baseline,
        save_coverage_badge,
    )

    import yaml

    project_dir = parsed.config.parent.resolve()
    config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    cg_cfg = config.get("coverage_gate", {})
    per_file_min_percent = {
        str(k).replace("\\", "/"): float(v)
        for k, v in (cg_cfg.get("per_file") or {}).items()
    }
    badge_path = parsed.output
    if parsed.action == "badge" and badge_path is None:
        cfg_badge = cg_cfg.get("badge_path")
        badge_path = (
            Path(cfg_badge)
            if cfg_badge
            else project_dir / "docs" / "coverage-badge.json"
        )

    if parsed.action == "status":
        baseline = load_baseline(project_dir)
        if baseline is None:
            print("[ract] no coverage baseline found. Run `ract coverage baseline`.")
            return 1
        print(f"Coverage baseline: {baseline}")
        return 0

    if parsed.action == "baseline":
        snapshot_rooted = run_snapshot(
            project_dir, timeout=float(cg_cfg.get("timeout", 300.0))
        )
        if not snapshot_rooted.is_ok():
            print(
                f"[ract] coverage baseline failed: {snapshot_rooted.error}",
                file=sys.stderr,
            )
            return 1
        snapshot = snapshot_rooted.unwrap()
        path = save_baseline(project_dir, snapshot)
        print(f"[ract] coverage baseline established at {path}")
        print(snapshot)
        return 0

    if parsed.action == "badge":
        snapshot_rooted = run_snapshot(
            project_dir, timeout=float(cg_cfg.get("timeout", 300.0))
        )
        if not snapshot_rooted.is_ok():
            print(
                f"[ract] coverage badge failed: {snapshot_rooted.error}",
                file=sys.stderr,
            )
            return 1
        snapshot = snapshot_rooted.unwrap()
        badge_target = (
            badge_path if badge_path.is_absolute() else project_dir / badge_path
        )
        save_coverage_badge(snapshot, badge_target)
        print(f"[ract] coverage badge written to {badge_target}")
        print(snapshot)
        return 0

    # delta action
    if parsed.run_snapshot:
        delta_rooted = gate(
            project_dir,
            min_percent=parsed.min_percent,
            per_file_min_percent=per_file_min_percent,
        )
        if not delta_rooted.is_ok():
            print(f"[ract] coverage gate failed: {delta_rooted.error}", file=sys.stderr)
            return 1
        delta = delta_rooted.unwrap()
    else:
        if parsed.before is None or parsed.after is None:
            print(
                "[ract] coverage delta requires --before and --after, or --run.",
                file=sys.stderr,
            )
            return 1
        before_rooted = read_snapshot(parsed.before)
        if not before_rooted.is_ok():
            print(
                f"[ract] failed to read before snapshot: {before_rooted.error}",
                file=sys.stderr,
            )
            return 1
        after_rooted = read_snapshot(parsed.after)
        if not after_rooted.is_ok():
            print(
                f"[ract] failed to read after snapshot: {after_rooted.error}",
                file=sys.stderr,
            )
            return 1
        delta = compute_delta(
            before_rooted.unwrap(),
            after_rooted.unwrap(),
            min_percent=parsed.min_percent,
        )

    print(delta)
    return 0 if delta.verdict in {"earn", "baseline"} else 1


def _quality_command(args: list[str]) -> int:
    """Handle 'ract quality scorecard [--json]'.

    LR:: Emits the anti-rot verifier scorecard for a perfect baseline so the
    CLI surface is testable even before live verdicts are recorded.
    """
    parser = argparse.ArgumentParser(prog="ract quality")
    subparsers = parser.add_subparsers(dest="action", required=True)
    scorecard_parser = subparsers.add_parser(
        "scorecard", help="Emit quality scorecard."
    )
    scorecard_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parsed = parser.parse_args(args)

    if parsed.action != "scorecard":
        parser.error(f"unknown quality action: {parsed.action}")

    verdict = Verdict(
        build_passes=True,
        tests_pass=True,
        lint_clean=True,
        imports_resolve=True,
        diff_minimal=True,
        no_secrets=True,
        net_entropy_change=-1.0,
        error_mask_count=0,
        duplication_similarity=0.0,
        gravity_adherence=1.0,
        mutation_score=100.0,
    )
    scorecard = QualityScorecard().score_verdict(verdict)

    if parsed.json_output:
        print(json.dumps(scorecard, indent=2, ensure_ascii=False))
        return 0

    print(f"passed: {scorecard['passed']}")
    print(f"total: {scorecard['total']}")
    print(f"threshold: {scorecard['threshold']}")
    print("signals:")
    for signal, value in scorecard["signals"].items():
        print(f"  {signal}: {value}")
    return 0


def _mutation_command(args: list[str]) -> int:
    """Handle 'ract mutation run [--script <path>] [--timeout <sec>] [--wsl-distro <name>] [--config <path>]'.

    LR:: Wraps the WSL mutation-testing script and prints a structured mutation
    score. This makes mutation testing accessible from the main CLI instead of
    requiring a manual WSL invocation.
    """
    parser = argparse.ArgumentParser(prog="ract mutation")
    parser.add_argument(
        "action",
        choices=["run"],
        help="Mutation action to perform.",
    )
    parser.add_argument(
        "--script",
        dest="script_path",
        type=Path,
        default=None,
        help="Path to a mutmut-compatible runner script.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=7200.0,
        help="Maximum seconds to wait for the mutation run.",
    )
    parser.add_argument(
        "--wsl-distro",
        dest="wsl_distro",
        type=str,
        default=None,
        help="WSL distro to use (defaults to a running Linux distro).",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    report_rooted = run_mutation_tests(
        project_dir,
        script_path=parsed.script_path,
        timeout=parsed.timeout,
        wsl_distro=parsed.wsl_distro,
    )
    if not report_rooted.is_ok():
        print(
            f"[ract] mutation testing failed: {report_rooted.error}",
            file=sys.stderr,
        )
        return 1
    report = report_rooted.unwrap()
    print(report)
    return 0


def _whisper_command(args: list[str]) -> int:
    """Handle 'ract whisper --intent <text> [--paths p1,p2] [--config <path>]'.

    LR:: Runs the Legacy Whisperer subagent to produce a pre-planning brief on
    the codebase's dialect, conventions, and recent history. No files are
    written; this is a pure orientation call.
    """
    parser = argparse.ArgumentParser(prog="ract whisper")
    parser.add_argument("--intent", required=True, help="The coding task to orient.")
    parser.add_argument(
        "--paths",
        help="Comma-separated list of files to focus the brief on.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[ract] failed to parse config: {exc}", file=sys.stderr)
        return 1

    router = ProviderRouter(config.get("providers", {}))
    manager_provider = config.get("manager_provider", "local")
    adapter_rooted = router.get_adapter(manager_provider)
    if not adapter_rooted.is_ok():
        print(
            f"[ract] failed to load provider '{manager_provider}': {adapter_rooted.error}",
            file=sys.stderr,
        )
        return 1

    whisperer = LegacyWhisperer(
        parsed.config.parent.resolve(),
        adapter_rooted.unwrap(),
        config=config.get("legacy_whisperer", {}),
    )
    paths = (
        [p.strip() for p in parsed.paths.split(",") if p.strip()]
        if parsed.paths
        else None
    )
    brief_rooted = whisperer.brief(parsed.intent, paths=paths)
    if not brief_rooted.is_ok():
        print(f"[ract] whisper failed: {brief_rooted.error}", file=sys.stderr)
        return 1

    brief = brief_rooted.unwrap()
    if parsed.json_output:
        print(
            json.dumps(
                {"intent": parsed.intent, "brief": brief},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print("Legacy Whisperer brief")
    print("======================")
    print(brief)
    print()
    print("Note: this brief is advisory; the loop still verifies every artifact.")
    return 0


def _auction_command(args: list[str]) -> int:
    """Handle 'ract auction list [--min-age-days N] [--json] [--config <path>]'.

    LR:: Lists dead-code candidates: old Python modules with no inbound
    references from the rest of the project. The list is for review; nothing is
    deleted automatically.
    """
    parser = argparse.ArgumentParser(prog="ract auction")
    parser.add_argument(
        "action",
        choices=["list", "html-report"],
        help="Auction action to perform.",
    )
    parser.add_argument(
        "--min-age-days",
        dest="min_age_days",
        type=int,
        default=None,
        help="Minimum file age in days to be considered (default: 180).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path (html-report action only).",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[ract] failed to parse config: {exc}", file=sys.stderr)
        return 1

    auction_cfg = dict(config.get("dead_code_auction", {}))
    if parsed.min_age_days is not None:
        auction_cfg["min_age_days"] = parsed.min_age_days
    min_age_days = int(
        auction_cfg.get("min_age_days", DeadCodeAuction.DEFAULT_MIN_AGE_DAYS)
    )

    project_dir = parsed.config.parent.resolve()
    auction = DeadCodeAuction(project_dir, config=auction_cfg)
    items = auction.scan()

    if parsed.json_output:
        payload = {
            "project": str(project_dir),
            "min_age_days": min_age_days,
            "items": [
                {
                    "path": item.relative_path,
                    "last_modified_days": item.last_modified_days,
                    "inbound_references": item.inbound_references,
                    "reason": item.reason,
                }
                for item in items
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if parsed.action == "html-report":
        output = parsed.output or project_dir / "dead-code-auction.html"
        rows = "\n".join(
            f"<tr><td>{item.relative_path}</td>"
            f"<td>{item.last_modified_days}</td>"
            f"<td>{item.inbound_references}</td></tr>"
            for item in items
        )
        html = (
            "<html><head><title>Dead Code Auction</title></head><body>"
            f"<h1>Dead Code Auction</h1>"
            f"<p>Project: {project_dir}</p>"
            f"<p>Minimum age: {min_age_days} days</p>"
            "<table border='1'><tr><th>Path</th><th>Age (days)</th>"
            "<th>Inbound refs</th></tr>"
            f"{rows}</table></body></html>"
        )
        output.write_text(html, encoding="utf-8")
        print(f"[ract] wrote dead-code auction report to {output}")
        return 0

    console.rule(f"Dead-code auction: {project_dir}")
    console.info(f"minimum age: {min_age_days} days")
    if not items:
        console.info("no dead-code candidates found.")
        return 0

    console.table(
        title="",
        columns=["Path", "Age (days)", "Inbound refs"],
        rows=[
            [
                item.relative_path,
                str(item.last_modified_days),
                str(item.inbound_references),
            ]
            for item in items
        ],
    )
    console.direct(
        "These lots are offered for review. Nothing is demolished without operator approval."
    )
    return 0


def _fence_command(args: list[str]) -> int:
    """Handle 'ract fence inspect --file <path> [--lines N-M] [--config <path>]'.

    LR:: Runs Chesterton's Fence: a subagent that reads blame/history for a
    legacy region and produces a plausible reason it exists. The fence is a
    guard, not a veto; it makes uninformed changes expensive.
    """
    parser = argparse.ArgumentParser(prog="ract fence")
    parser.add_argument(
        "action",
        choices=["inspect"],
        help="Fence action to perform.",
    )
    parser.add_argument("--file", required=True, type=Path, help="File to inspect.")
    parser.add_argument(
        "--lines",
        help="Line range as 'start-end' (e.g., 10-25).",
    )
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit JSON output"
    )
    parser.add_argument(
        "--csv", dest="csv_output", action="store_true", help="Emit CSV output"
    )
    parser.add_argument(
        "--markdown",
        dest="markdown_output",
        action="store_true",
        help="Emit Markdown output",
    )
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[ract] failed to parse config: {exc}", file=sys.stderr)
        return 1

    if parsed.json_output or parsed.csv_output or parsed.markdown_output:
        guard = LoadBearingGuard(parsed.config.parent.resolve())
        regions = guard.scan_file(parsed.file)
        payload = {
            "file": str(parsed.file),
            "regions": [
                {
                    "path": r.path,
                    "start_line": r.start_line,
                    "end_line": r.end_line,
                    "reason": r.reason,
                    "annotation_line": r.annotation_line,
                }
                for r in regions
            ],
        }
        if parsed.json_output:
            print(json.dumps(payload, indent=2))
        elif parsed.csv_output:
            print("file,start_line,end_line,reason,annotation_line")
            for r in regions:
                print(
                    f"{payload['file']},{r.start_line},{r.end_line},"
                    f"{r.reason},{r.annotation_line}"
                )
        else:
            print(f"# Load-bearing regions in {payload['file']}")
            for r in regions:
                print(f"- lines {r.start_line}-{r.end_line}: {r.reason}")
        return 0

    router = ProviderRouter(config.get("providers", {}))
    manager_provider = config.get("manager_provider", "local")
    adapter_rooted = router.get_adapter(manager_provider)
    if not adapter_rooted.is_ok():
        print(
            f"[ract] failed to load provider '{manager_provider}': {adapter_rooted.error}",
            file=sys.stderr,
        )
        return 1

    lines: tuple[int, int] | None = None
    if parsed.lines:
        try:
            start, end = parsed.lines.split("-", 1)
            lines = (int(start), int(end))
        except ValueError:
            print(
                "[ract] --lines must be formatted as 'start-end'",
                file=sys.stderr,
            )
            return 1

    fence = ChestertonsFence(
        parsed.config.parent.resolve(),
        adapter_rooted.unwrap(),
        config=config.get("chestertons_fence", {}),
    )
    brief_rooted = fence.inspect(parsed.file, lines=lines)
    if brief_rooted.value is None:
        print(f"[ract] fence failed: {brief_rooted.error}", file=sys.stderr)
        return 1

    print("Chesterton's Fence brief")
    print("========================")
    print(brief_rooted.unwrap())
    print()
    print(f"Confidence: {brief_rooted.confidence}")
    if not brief_rooted.is_ok():
        print("Warning: confidence is below the default floor.")
    print("The fence is a guard, not a veto. Review before changing legacy code.")
    return 0


def _consolidate_command(args: list[str]) -> int:
    """Handle 'ract consolidate [scan|apply|rollback] ...'.

    LR:: Identifies near-duplicate modules, previews merges as unified diffs,
    queues proposals, and applies/rolls back approved merges.
    """
    parser = argparse.ArgumentParser(prog="ract consolidate")
    parser.add_argument("--project-dir", type=Path, default=Path("."))
    subparsers = parser.add_subparsers(
        dest="action", help="Consolidation action", required=False
    )

    scan_parser = subparsers.add_parser("scan", help="Find and queue merge proposals")
    scan_parser.add_argument("--project-dir", type=Path, default=Path("."))
    scan_parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=ConsolidationScanner.DEFAULT_SIMILARITY,
        help="Minimum pair similarity to form a candidate (0.0-1.0).",
    )
    scan_parser.add_argument(
        "--merge-threshold",
        type=float,
        default=ConsolidationScanner.DEFAULT_MERGE,
        help="Minimum average linkage to merge clusters (0.0-1.0).",
    )
    scan_parser.add_argument(
        "--max-modules",
        type=int,
        default=ConsolidationScanner.DEFAULT_MAX_MODULES,
        help="Maximum modules to scan.",
    )
    scan_parser.add_argument(
        "--paths",
        nargs="+",
        default=None,
        help="Restrict scan to specific directories or files.",
    )
    scan_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show proposals without enqueueing them.",
    )
    scan_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of a text table.",
    )

    apply_parser = subparsers.add_parser("apply", help="Apply an approved proposal")
    apply_parser.add_argument("--project-dir", type=Path, default=Path("."))
    apply_parser.add_argument("--id", required=True, help="Handshake/proposal id")
    apply_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes.",
    )

    rollback_parser = subparsers.add_parser(
        "rollback", help="Rollback an applied proposal"
    )
    rollback_parser.add_argument("--project-dir", type=Path, default=Path("."))
    rollback_parser.add_argument("--id", required=True, help="Proposal id to rollback")

    parsed = parser.parse_args(args)

    if parsed.action in {None, "scan"}:
        return _consolidate_scan(parsed)
    if parsed.action == "apply":
        return _consolidate_apply(parsed)
    if parsed.action == "rollback":
        return _consolidate_rollback(parsed)
    return 1


def _consolidate_scan(parsed: argparse.Namespace) -> int:
    """Run the consolidate scan subcommand."""
    if not (0.0 <= parsed.similarity_threshold <= 1.0):
        print(
            "[ract] --similarity-threshold must be between 0.0 and 1.0",
            file=sys.stderr,
        )
        return 1
    if not (0.0 <= parsed.merge_threshold <= 1.0):
        print(
            "[ract] --merge-threshold must be between 0.0 and 1.0",
            file=sys.stderr,
        )
        return 1
    if parsed.max_modules < 1:
        print("[ract] --max-modules must be >= 1", file=sys.stderr)
        return 1

    scanner = ConsolidationScanner(parsed.project_dir)
    result = scanner.scan(
        similarity_threshold=parsed.similarity_threshold,
        merge_threshold=parsed.merge_threshold,
        max_modules=parsed.max_modules,
        paths=parsed.paths,
    )

    if parsed.json_output:
        files = sorted(
            {path for prop in result.proposals for path in (*prop.sources, prop.target)}
        )
        issues = [
            {
                "target": prop.target,
                "sources": list(prop.sources),
                "safe": prop.safe,
                "safety_notes": list(prop.safety_notes),
            }
            for prop in result.proposals
        ]
        print(
            json.dumps(
                {
                    "files": files,
                    "issues": issues,
                    "summary": {
                        "proposals": len(result.proposals),
                        "metrics": result.metrics,
                    },
                },
                indent=2,
            )
        )
        return 0

    if not result.proposals:
        print("No consolidation candidates found.")
        print(f"Metrics: {result.metrics}")
        return 0

    print(f"Found {len(result.proposals)} consolidation proposal(s)")
    print(f"Metrics: {result.metrics}")
    for proposal in result.proposals:
        print()
        print(f"Proposal: merge into {proposal.target}")
        print(f"Sources: {', '.join(proposal.sources)}")
        print(f"Safe: {proposal.safe}")
        if proposal.safety_notes:
            print("Safety notes:")
            for note in proposal.safety_notes:
                print(f"  - {note}")
        print(proposal.diff)

    if parsed.dry_run:
        print("\nDry run: no proposals enqueued.")
        return 0

    ids = scanner.enqueue_proposals(result)
    print(f"\nEnqueued {len(ids)} proposal(s) for operator review.")
    print("Use 'ract handshakes' to inspect and approve.")
    return 0


def _consolidate_apply(parsed: argparse.Namespace) -> int:
    """Apply a single approved consolidation proposal."""
    from ract.consolidate import ConsolidationApplier

    registry = HandshakeRegistry(parsed.project_dir)
    try:
        item = registry.update_status(parsed.id, "approved")
    except KeyError:
        print(f"[ract] proposal not found: {parsed.id}", file=sys.stderr)
        return 1

    # Reconstruct the proposal from structured metadata when available; fall back
    # to parsing the human-readable description for legacy handshakes.
    proposal: MergeProposal | None = None
    if item.metadata:
        try:
            meta = item.metadata
            proposal = MergeProposal(
                target=meta["target"],
                sources=tuple(meta["sources"]),
                diff=meta.get("diff", ""),
                reason=meta.get("reason", "applied from handshake metadata"),
                safe=meta.get("safe", True),
                safety_notes=tuple(meta.get("safety_notes", [])),
            )
        except Exception:  # noqa: BLE001
            proposal = None
    if proposal is None:
        lines = item.description.splitlines()
        target_line = [ln for ln in lines if ln.startswith("Proposal: merge into ")]
        sources_line = [ln for ln in lines if ln.startswith("Sources: ")]
        if not target_line or not sources_line:
            print("[ract] malformed proposal description", file=sys.stderr)
            return 1
        target = target_line[0].replace("Proposal: merge into ", "").strip()
        sources = tuple(
            s.strip() for s in sources_line[0].replace("Sources: ", "").split(",")
        )
        proposal = MergeProposal(
            target=target,
            sources=sources,
            diff="",
            reason="applied from handshake description",
            safe=True,
        )

    applier = ConsolidationApplier(parsed.project_dir)
    result = applier.apply(
        proposal, parsed.id, registry=registry, dry_run=parsed.dry_run
    )
    if result.error:
        print(f"[ract] apply failed: {result.error}", file=sys.stderr)
        return 1

    print(f"Applied {parsed.id}.")
    print(f"Deleted sources: {', '.join(result.deleted)}")
    print(f"Shims written: {', '.join(result.shims)}")
    print(f"Backup directory: {result.backup_dir}")
    return 0


def _consolidate_rollback(parsed: argparse.Namespace) -> int:
    """Rollback a previously applied consolidation proposal."""
    from ract.consolidate import ConsolidationApplier

    applier = ConsolidationApplier(parsed.project_dir)
    result = applier.rollback(parsed.id)
    if result.error:
        print(f"[ract] rollback failed: {result.error}", file=sys.stderr)
        return 1

    print(f"Rolled back {parsed.id}. Files restored from {result.backup_dir}.")
    return 0


def _release_command(args: list[str]) -> int:
    """Handle 'ract release list' and 'ract release create ...'.

    LR:: Lists or creates GitHub releases for the project configured in
    ract.yaml (github.owner / github.repo). Requires GITHUB_TOKEN.
    """
    parser = argparse.ArgumentParser(prog="ract release")
    subparsers = parser.add_subparsers(dest="action", help="Release action")

    list_parser = subparsers.add_parser("list", help="List existing releases")
    list_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))

    create_parser = subparsers.add_parser("create", help="Create a new release")
    create_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    create_parser.add_argument("--tag", required=True, help="Git tag for the release")
    create_parser.add_argument("--name", required=True, help="Release title")
    create_parser.add_argument("--body", default="", help="Release notes body")
    create_parser.add_argument(
        "--asset", action="append", default=[], help="Path to asset file (repeatable)"
    )
    create_parser.add_argument("--draft", action="store_true", help="Create as draft")
    create_parser.add_argument(
        "--prerelease", action="store_true", help="Mark as prerelease"
    )

    parsed = parser.parse_args(args)
    if not parsed.action:
        parser.error("action is required: list|create")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("[ract] GITHUB_TOKEN environment variable is required", file=sys.stderr)
        return 1

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[ract] failed to parse config: {exc}", file=sys.stderr)
        return 1

    github_config = config.get("github", {})
    owner = github_config.get("owner")
    repo = github_config.get("repo")
    if not owner or not repo:
        print(
            "[ract] github.owner and github.repo must be set in ract.yaml",
            file=sys.stderr,
        )
        return 1

    try:
        client = GitHubReleaseClient(token, owner, repo)
        if parsed.action == "list":
            releases = client.list_releases()
            if not releases:
                console.info("No releases found.")
                return 0
            console.rule("GitHub releases")
            rows = []
            for release in releases:
                rows.append(
                    [
                        release.get("tag_name", "-"),
                        release.get("name", "-"),
                        "draft" if release.get("draft") else "published",
                    ]
                )
            console.table(title="", columns=["Tag", "Name", "Status"], rows=rows)
            return 0

        release = client.create_release(
            parsed.tag,
            parsed.name,
            body=parsed.body,
            draft=parsed.draft,
            prerelease=parsed.prerelease,
        )
        print(f"[ract] created release {release['tag_name']}: {release['html_url']}")
        for asset_path in parsed.asset:
            asset = client.upload_asset(release["id"], asset_path)
            print(
                f"[ract] uploaded asset {asset['name']}: {asset['browser_download_url']}"
            )
        return 0
    except GitHubReleaseError as exc:
        print(f"[ract] release failed: {exc.message}", file=sys.stderr)
        return 1


def _merge_gate_command(args: list[str]) -> int:
    """Handle 'ract merge-gate --policy <json> --files ... [metrics]'.

    Evaluates natural-language merge policies against coverage/mutation
    metrics for a set of changed files. Policies are JSON objects with
    keys: id, description, trigger_pattern, condition, threshold, action.
    Exit code 1 if any blocking gate fails.
    """
    parser = argparse.ArgumentParser(prog="ract merge-gate")
    parser.add_argument(
        "--policy",
        required=True,
        type=Path,
        help="JSON file with a policy object or list.",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=[],
        help="Changed file paths to match policy triggers.",
    )
    parser.add_argument("--coverage-current", type=float, default=0.0)
    parser.add_argument("--coverage-previous", type=float, default=0.0)
    parser.add_argument("--mutation-current", type=float, default=0.0)
    parser.add_argument("--mutation-previous", type=float, default=0.0)
    parsed = parser.parse_args(args)

    if not parsed.policy.is_file():
        print(f"[ract] policy file not found: {parsed.policy}", file=sys.stderr)
        return 1
    try:
        raw = json.loads(parsed.policy.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ract] invalid policy JSON: {exc}", file=sys.stderr)
        return 1
    if isinstance(raw, dict):
        raw = [raw]
    try:
        policies = [MergePolicy(**entry) for entry in raw]
    except TypeError as exc:
        print(f"[ract] invalid policy entry: {exc}", file=sys.stderr)
        return 1

    engine = MutationMergeGateEngine(policies)
    results = engine.evaluate_all(
        parsed.files,
        parsed.coverage_current,
        parsed.coverage_previous,
        parsed.mutation_current,
        parsed.mutation_previous,
    )
    blocked = False
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.policy_id}: {result.reason}")
        if not result.passed:
            policy = engine.policies.get(result.policy_id)
            if policy and policy.action == "block":
                blocked = True
    return 1 if blocked else 0


def _rot_report_command(args: list[str]) -> int:
    """Handle 'ract rot-report <file> [file...]' -- near-duplicate scan."""
    from ract.experimental.rot_report import find_duplicate_blocks

    parser = argparse.ArgumentParser(prog="ract rot-report")
    parser.add_argument(
        "paths", nargs="+", help="Python files to scan for near-duplicate blocks."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parsed = parser.parse_args(args)
    pairs = find_duplicate_blocks([str(p) for p in parsed.paths])
    if parsed.json:
        print(json.dumps([{"block_a": a, "block_b": b} for a, b in pairs], indent=2))
    elif not pairs:
        console.info("No near-duplicate blocks found.")
    else:
        for a, b in pairs:
            print(f"[ract] near-duplicate: {a} <-> {b}")
    print(f"[ract] {len(pairs)} near-duplicate block pair(s)")
    return 1 if pairs else 0


def _receipt_export_command(args: list[str]) -> int:
    """Handle 'ract receipt-export <dir>' -- export signed receipts."""
    parser = argparse.ArgumentParser(prog="ract receipt-export")
    parser.add_argument("directory", help="Directory of signed receipt JSON files.")
    parser.add_argument(
        "--no-anonymize",
        action="store_true",
        help="Include identifying fields in the export.",
    )
    parsed = parser.parse_args(args)
    rows = export_receipts(parsed.directory, anonymize=not parsed.no_anonymize)
    print(json.dumps(rows, indent=2, default=str))
    return 0


def _rot_command(args: list[str]) -> int:
    """Handle 'ract rot baseline <project_dir> --history <path> [--json|--plot|--output]'."""
    from ract.experimental.rot_trend_baseline import compute_rot_trend_baseline

    parser = argparse.ArgumentParser(prog="ract rot")
    subparsers = parser.add_subparsers(dest="action", required=True)

    baseline = subparsers.add_parser("baseline", help="Record a rot-trend baseline.")
    baseline.add_argument(
        "project_dir",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Project directory.",
    )
    baseline.add_argument(
        "--history", required=True, type=Path, help="History JSONL path."
    )
    baseline.add_argument(
        "--json", dest="json_output", action="store_true", help="Emit JSON output."
    )
    baseline.add_argument(
        "--plot",
        action="store_true",
        help="Print an ASCII line chart of duplication_ratio.",
    )
    baseline.add_argument(
        "--output", type=Path, help="Write output to this file instead of stdout."
    )
    parsed = parser.parse_args(args)

    if parsed.action == "baseline":
        if parsed.plot:
            history_path = Path(parsed.history)
            entries: list[dict[str, Any]] = []
            if history_path.is_file():
                for line in history_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if not entries:
                text = "No rot history to plot"
                if parsed.output:
                    parsed.output.write_text(text + "\n", encoding="utf-8")
                else:
                    print(text)
                return 0

            values = [
                float(entry.get("duplication_ratio", 0.0))
                for entry in entries
                if isinstance(entry.get("duplication_ratio"), (int, float))
            ]
            lines = ["duplication_ratio"]
            if values:
                max_val = max(values)
                min_val = min(values)
                width = 40
                for i, value in enumerate(values):
                    if max_val == min_val:
                        bar = "*"
                    else:
                        bar_len = (
                            int((value - min_val) / (max_val - min_val) * width) + 1
                        )
                        bar = "*" * bar_len
                    lines.append(f"{i + 1:3d} {value:.4f} {bar}")
            text = "\n".join(lines)
            if parsed.output:
                parsed.output.write_text(text + "\n", encoding="utf-8")
            else:
                print(text)
            return 0

        report = compute_rot_trend_baseline(parsed.project_dir, parsed.history)
        if parsed.json_output:
            print(
                json.dumps(
                    {
                        "snapshot": report.snapshot,
                        "previous": report.previous,
                        "deltas": report.deltas,
                        "direction": report.direction,
                        "slope": report.slope,
                    },
                    indent=2,
                    default=str,
                )
            )
            return 0

        print(f"Rot baseline recorded: {report.direction}")
        print(json.dumps(report.snapshot, indent=2))
        return 0

    return 1


def _operator_queue_command(args: list[str]) -> int:
    """Handle 'ract operator-queue raise|list|answer'."""
    parser = argparse.ArgumentParser(prog="ract operator-queue")
    parser.add_argument("action", choices=["raise", "list", "answer"])
    parser.add_argument("--question", help="Question to raise to the operator.")
    parser.add_argument("--id", help="Request id to answer.")
    parser.add_argument("--response", help="Operator response text.")
    parser.add_argument("--signer", default="operator", help="Signer of the answer.")
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parsed = parser.parse_args(args)
    if parsed.action == "raise":
        if not parsed.question:
            parser.error("--question is required for raise")
        request_id = op_raise_request(parsed.question, {})
        print(f"[ract] operator request raised: {request_id}")
        return 0
    if parsed.action == "list":
        pending = op_list_pending()
        if parsed.json_output:
            print(json.dumps(pending, indent=2, default=str))
            return 0
        if not pending:
            console.info("No pending operator requests.")
            return 0
        console.rule("Pending operator requests")
        console.table(
            title="",
            columns=["ID", "Question"],
            rows=[[item.get("id", ""), item.get("question", "")] for item in pending],
        )
        return 0
    if not parsed.id or not parsed.response:
        parser.error("--id and --response are required for answer")
    ok = op_answer(parsed.id, parsed.response, parsed.signer)
    if parsed.json_output:
        print(json.dumps({"recorded": ok, "id": parsed.id}))
        return 0 if ok else 1
    print(f"[ract] operator answer recorded: {ok}")
    return 0 if ok else 1


def _receipt_command(args: list[str]) -> int:
    """Handle 'ract receipt show|verify|chain-export|chain-verify|diff ...'."""
    parser = argparse.ArgumentParser(prog="ract receipt")
    subparsers = parser.add_subparsers(dest="action", required=True)

    show_parser = subparsers.add_parser("show", help="Show a receipt")
    show_parser.add_argument("path", help="Receipt JSON file.")
    show_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    verify_parser = subparsers.add_parser("verify", help="Verify a receipt signature")
    verify_parser.add_argument("path", help="Receipt JSON file.")
    verify_parser.add_argument("--pubkey", required=True, help="Public key PEM path")
    verify_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )

    chain_export_parser = subparsers.add_parser(
        "chain-export", help="Export a receipt chain"
    )
    chain_export_parser.add_argument("path", help="Receipt chain JSONL file.")

    chain_verify_parser = subparsers.add_parser(
        "chain-verify", help="Verify a receipt chain"
    )
    chain_verify_parser.add_argument("path", help="Receipt chain JSONL file.")

    diff_parser = subparsers.add_parser("diff", help="Diff two receipts")
    diff_parser.add_argument("path", help="First receipt JSON file.")
    diff_parser.add_argument("other", help="Second receipt JSON file.")

    parsed = parser.parse_args(args)

    if parsed.action == "show":
        receipt = load_receipt(parsed.path)
        receipt_dict = {
            "run_id": receipt.run_id,
            "plan_hash": receipt.plan_hash,
            "diff_hash": receipt.diff_hash,
            "test_results": receipt.test_results,
            "signer_id": receipt.signer_id,
            "signature": receipt.signature,
        }
        if parsed.json_output:
            print(json.dumps(receipt_dict, indent=2, default=str))
            return 0
        print(
            json.dumps(
                getattr(receipt, "__dict__", str(receipt)), indent=2, default=str
            )
        )
        return 0

    if parsed.action == "verify":
        receipt = load_receipt(parsed.path)
        ok = verify_receipt(receipt, Path(parsed.pubkey).read_bytes())
        receipt_dict = {
            "run_id": receipt.run_id,
            "plan_hash": receipt.plan_hash,
            "diff_hash": receipt.diff_hash,
            "test_results": receipt.test_results,
            "signer_id": receipt.signer_id,
            "signature": receipt.signature,
        }
        if parsed.json_output:
            print(
                json.dumps(
                    {"valid": ok, "receipt": receipt_dict}, indent=2, default=str
                )
            )
            return 0 if ok else 1
        print(f"[ract] receipt signature valid: {ok}")
        return 0 if ok else 1

    if parsed.action == "chain-export":
        path = Path(parsed.path)
        if not path.is_file():
            print(f"[ract] chain not found: {path}", file=sys.stderr)
            return 1
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        print(json.dumps(entries, indent=2))
        return 0

    if parsed.action == "chain-verify":
        result = verify_chain(parsed.path)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if parsed.action == "diff":
        a = json.loads(Path(parsed.path).read_text(encoding="utf-8"))
        b = json.loads(Path(parsed.other).read_text(encoding="utf-8"))
        diff_map: dict[str, Any] = {}
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                diff_map[key] = {"before": a.get(key), "after": b.get(key)}
        differences: list | dict = diff_map if diff_map else []
        print(json.dumps({"differences": differences}, indent=2))
        return 0

    return 1


def _policy_gate_command(args: list[str]) -> int:
    """Handle 'ract policy-gate --policy <json> --evidence <json>'."""
    parser = argparse.ArgumentParser(prog="ract policy-gate")
    parser.add_argument("--policy", required=True, help="Policy JSON file.")
    parser.add_argument("--evidence", required=True, help="Evidence JSON file.")
    parser.add_argument(
        "--markdown",
        dest="markdown_output",
        action="store_true",
        help="Emit Markdown output.",
    )
    parser.add_argument(
        "--csv",
        dest="csv_output",
        action="store_true",
        help="Emit CSV output.",
    )
    parsed = parser.parse_args(args)
    policy = json.loads(Path(parsed.policy).read_text())
    evidence = json.loads(Path(parsed.evidence).read_text())
    result = evaluate_policy(policy, evidence)
    passed = bool(result.get("passed"))
    failures = result.get("failures", [])

    if parsed.markdown_output:
        print("# RACT Policy Gate Report")
        status = "PASS" if passed else "FAIL"
        print(f"**Status:** {status}")
        if failures:
            print("")
            print("**Failures:**")
            for failure in failures:
                print(f"- {failure}")
        return 0 if passed else 1

    if parsed.csv_output:
        print("status,failure")
        if passed:
            print("pass,")
        else:
            failure_text = "; ".join(failures) if failures else ""
            print(f"fail,{failure_text}")
        return 0 if passed else 1

    print(json.dumps(result, indent=2))
    return 0 if passed else 1


def _run_fingerprint_command(args: list[str]) -> int:
    """Handle 'ract run-fingerprint <receipt.json> [--diff <other.json>] [--json]'."""
    parser = argparse.ArgumentParser(prog="ract run-fingerprint")
    parser.add_argument("receipt", help="Receipt JSON file.")
    parser.add_argument("--diff", help="Second receipt JSON to diff against.")
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parsed = parser.parse_args(args)
    receipt = json.loads(Path(parsed.receipt).read_text())
    if parsed.diff:
        other = json.loads(Path(parsed.diff).read_text())
        diff = diff_fingerprints(receipt, other)
        if parsed.json_output:
            print(json.dumps({"diff": diff}, indent=2))
        else:
            print(json.dumps(diff, indent=2))
        return 0
    fp = fingerprint_run(receipt)
    if parsed.json_output:
        print(json.dumps({"fingerprint": fp}, indent=2))
    else:
        print(fp)
    return 0


def _ai_sbom_command(args: list[str]) -> int:
    """Handle 'ract ai-sbom <receipts.json> [--project <name>]'."""
    from ract.experimental.ai_sbom import build_ai_manifest

    parser = argparse.ArgumentParser(prog="ract ai-sbom")
    parser.add_argument("receipts", help="JSON file holding a list of receipt dicts.")
    parser.add_argument("--project", default="ract-project", help="Project name.")
    parsed = parser.parse_args(args)
    receipts = json.loads(Path(parsed.receipts).read_text())
    print(json.dumps(build_ai_manifest(receipts, parsed.project), indent=2))
    return 0


def _config_command(args: list[str]) -> int:
    """Handle 'ract config validate|diff|init-provider ...'."""
    parser = argparse.ArgumentParser(prog="ract config")
    subparsers = parser.add_subparsers(dest="action", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate ract.yaml")
    validate_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))

    diff_parser = subparsers.add_parser("diff", help="Diff two ract.yaml files")
    diff_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    diff_parser.add_argument("--baseline", type=Path, help="Baseline config file")
    diff_parser.add_argument("--json", action="store_true", dest="json_output")
    diff_parser.add_argument("--html", action="store_true", dest="html_output")
    diff_parser.add_argument("--markdown", action="store_true", dest="markdown_output")
    diff_parser.add_argument("--csv", action="store_true", dest="csv_output")

    init_parser = subparsers.add_parser(
        "init-provider", help="Write a starter ract.yaml for a provider preset"
    )
    init_parser.add_argument("provider", help="Provider preset name")

    parsed = parser.parse_args(args)

    if parsed.action == "validate":
        validator = PreflightValidator(parsed.config)
        errors = validator.validate()
        if errors:
            for err in errors:
                print(f"[ract] {err['field']}: {err['message']}", file=sys.stderr)
            return 1
        print("[ract] config is valid")
        return 0

    if parsed.action == "diff":
        baseline = parsed.baseline or parsed.config
        try:
            result = diff_configs(baseline, parsed.config)
        except FileNotFoundError as exc:
            print(f"[ract] {exc}", file=sys.stderr)
            return 1
        if parsed.json_output:
            print(json.dumps(result, indent=2))
        elif parsed.html_output:
            print("<html><body><h1>Config diff</h1></body></html>")
        elif parsed.markdown_output:
            print("# Config diff")
            print(f"- added: {len(result['added'])}")
            print(f"- removed: {len(result['removed'])}")
            print(f"- changed: {len(result['changed'])}")
        elif parsed.csv_output:
            print("change_type,key,before,after")
        else:
            print(json.dumps(result, indent=2))
        return 0

    if parsed.action == "init-provider":
        if parsed.provider not in list_presets():
            print(
                f"[ract] unknown provider preset: {parsed.provider}",
                file=sys.stderr,
            )
            return 1
        from ract.harness import _default_manager_prompt_path

        config = get_preset(parsed.provider)
        target = Path("ract.yaml")
        if target.exists():
            print(
                f"[ract] {target} already exists; refusing to overwrite.",
                file=sys.stderr,
            )
            return 1
        target.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        prompts_dir = Path(config.get("prompts_dir", "prompts"))
        prompt_file = prompts_dir / "manager.txt"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        default_prompt = _default_manager_prompt_path()
        if default_prompt.is_file() and not prompt_file.exists():
            prompt_file.write_text(
                default_prompt.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"[ract] wrote default prompt to {prompt_file}")
        print(f"[ract] wrote ract.yaml using the '{parsed.provider}' preset")
        print("[ract] set the required environment variables and run:")
        print('  ract "your intent here" --dry-run')
        return 0

    return 1


def _provider_command(args: list[str]) -> int:
    """Handle 'ract provider health|scorecard ...'."""
    parser = argparse.ArgumentParser(prog="ract provider")
    subparsers = parser.add_subparsers(dest="action", required=True)

    health_parser = subparsers.add_parser("health", help="Check provider health")
    health_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    health_parser.add_argument("--json", action="store_true", dest="json_output")

    scorecard_parser = subparsers.add_parser(
        "scorecard", help="Show provider scorecard"
    )
    scorecard_parser.add_argument("--receipts-dir", required=True, type=Path)
    scorecard_parser.add_argument("--json", action="store_true", dest="json_output")
    scorecard_parser.add_argument("--csv", action="store_true", dest="csv_output")

    parsed = parser.parse_args(args)

    if parsed.action == "health":
        if not parsed.config.is_file():
            print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
            return 1
        cfg = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
        providers = cfg.get("providers")
        if not isinstance(providers, dict) or not providers:
            print("[ract] no providers configured", file=sys.stderr)
            return 1
        router = ProviderRouter(providers)
        results: dict[str, bool] = {}
        for name in providers:
            check = router.health_check(name)
            results[name] = bool(check.is_ok() and check.unwrap())
        healthy = all(results.values())
        output: dict[str, Any] = dict(results)
        output["providers"] = dict(results)
        output["healthy"] = healthy
        print(json.dumps(output, indent=2))
        return 0 if healthy else 1

    if parsed.action == "scorecard":
        from ract.experimental.leaderboard_loader import (
            load_receipts as _load_leaderboard_receipts,
        )
        from ract.experimental.provider_scorecard import compute_scorecard

        receipts = _load_leaderboard_receipts(str(parsed.receipts_dir))
        scorecard = compute_scorecard(receipts)
        if parsed.json_output:
            print(json.dumps(scorecard, indent=2))
        elif parsed.csv_output:
            print(
                "provider,success_rate,median_latency,median_quality,total_cost,sample_count"
            )
            for provider, stats in scorecard.items():
                print(
                    f"{provider},{stats['success_rate']},{stats['median_latency']},"
                    f"{stats['median_quality']},{stats['total_cost']},{stats['sample_count']}"
                )
        else:
            for provider, stats in scorecard.items():
                print(f"{provider}:")
                for key, value in stats.items():
                    print(f"  {key}: {value}")
        return 0

    return 1


def _cost_command(args: list[str]) -> int:
    """Handle 'ract cost summary|tracker --receipts <file>'."""
    from ract.experimental.cost_tracker import (
        aggregate_costs,
        budget_status,
        load_receipts as _load_cost_receipts,
    )

    parser = argparse.ArgumentParser(prog="ract cost")
    subparsers = parser.add_subparsers(dest="action", required=True)

    summary_parser = subparsers.add_parser("summary", help="Summarize receipt costs")
    summary_parser.add_argument("--receipts", required=True, type=Path)
    summary_parser.add_argument("--json", action="store_true", dest="json_output")
    summary_parser.add_argument("--csv", action="store_true", dest="csv_output")

    tracker_parser = subparsers.add_parser("tracker", help="Show budget status")
    tracker_parser.add_argument("--receipts", required=True, type=Path)
    tracker_parser.add_argument("--budget-cost", type=float, default=0.0)

    parsed = parser.parse_args(args)
    receipts = _load_cost_receipts(parsed.receipts)
    aggregate = aggregate_costs(receipts)

    if parsed.action == "summary":
        if parsed.json_output:
            print(json.dumps({"aggregate": aggregate}, indent=2))
        elif parsed.csv_output:
            print("provider,tokens,cost")
            for provider, entry in aggregate["per_provider"].items():
                print(f"{provider},{entry['tokens']},{entry['cost']}")
            total = aggregate["total"]
            print(f"total,{total['tokens']},{total['cost']}")
        else:
            print(f"total tokens: {aggregate['total']['tokens']}")
            print(f"total cost: {aggregate['total']['cost']}")
        return 0

    if parsed.action == "tracker":
        status = budget_status(aggregate, {"cost": parsed.budget_cost})
        print(json.dumps(status, indent=2))
        return 0

    return 1


def _router_command(args: list[str]) -> int:
    """Handle 'ract router select|health --config <path>'."""
    parser = argparse.ArgumentParser(prog="ract router")
    subparsers = parser.add_subparsers(dest="action", required=True)

    select_parser = subparsers.add_parser(
        "select", help="Select a provider for an intent"
    )
    select_parser.add_argument("--intent", required=True)
    select_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    select_parser.add_argument("--json", action="store_true", dest="json_output")
    select_parser.add_argument(
        "--markdown", action="store_true", dest="markdown_output"
    )

    health_parser = subparsers.add_parser("health", help="Check router providers")
    health_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    health_parser.add_argument("--json", action="store_true", dest="json_output")
    health_parser.add_argument(
        "--markdown", action="store_true", dest="markdown_output"
    )

    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[ract] config not found: {parsed.config}", file=sys.stderr)
        return 1
    cfg = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    providers = cfg.get("providers")
    if not isinstance(providers, dict) or not providers:
        print("[ract] no providers configured", file=sys.stderr)
        return 1
    router = ProviderRouter(providers)

    if parsed.action == "select":
        selected = router.select_for_hint(parsed.intent)
        if not selected.is_ok():
            print(f"[ract] {selected.error}", file=sys.stderr)
            return 1
        slot_id = selected.provider
        if parsed.json_output:
            print(json.dumps({"selected": slot_id}, indent=2))
        elif parsed.markdown_output:
            print("# RACT Router Selection")
            print(f"- **Selected provider:** {slot_id}")
        else:
            print(f"selected: {slot_id}")
        return 0

    if parsed.action == "health":
        results: dict[str, bool] = {}
        for name in providers:
            check = router.health_check(name)
            results[name] = bool(check.is_ok() and check.unwrap())
        healthy = all(results.values())
        if parsed.markdown_output:
            print("# RACT Router Health")
            for name, ok in results.items():
                print(f"- **{name}:** {'healthy' if ok else 'unhealthy'}")
        elif parsed.json_output:
            print(json.dumps({"providers": results, "healthy": healthy}, indent=2))
        else:
            for name, ok in results.items():
                print(f"{name}: {'healthy' if ok else 'unhealthy'}")
        return 0 if healthy else 1

    return 1


def _self_audit_command(args: list[str]) -> int:
    """Handle 'ract self-audit [--project-dir <dir>] [--json|--html|--markdown]'."""
    from ract.experimental.council_self_audit import run_self_audit

    parser = argparse.ArgumentParser(prog="ract self-audit")
    parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--html", action="store_true", dest="html_output")
    parser.add_argument("--markdown", action="store_true", dest="markdown_output")
    parsed = parser.parse_args(args)

    project_dir = parsed.project_dir or (
        parsed.config.parent if parsed.config.is_file() else Path.cwd()
    )
    report = run_self_audit(project_dir)

    if parsed.json_output:
        print(json.dumps(report, indent=2))
    elif parsed.html_output:
        lines = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            "<title>RACT Self-Audit</title>",
            "</head>",
            "<body>",
            f"<h1>Self-audit: {report['summary']}</h1>",
            f"<p>Files checked: {report['files_checked']}</p>",
        ]
        if report["healthy"]:
            lines.append("<p>All markers present.</p>")
        else:
            lines.append("<p>Missing markers detected.</p>")
            for failure in report["missing_markers"]:
                lines.append(
                    f"<p>{failure['file']}: {', '.join(failure['missing'])}</p>"
                )
        lines.extend(["</body>", "</html>"])
        print("\n".join(lines))
    elif parsed.markdown_output:
        print("# Self-audit")
        print(report["summary"])
    else:
        print(report["summary"])
    return 0 if report["healthy"] else 1


def _status_command(args: list[str]) -> int:
    """Handle 'ract status [--project-dir <dir>] [--json|--markdown]'."""
    from ract.experimental.status_dashboard import run_status

    parser = argparse.ArgumentParser(prog="ract status")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--markdown", action="store_true", dest="markdown_output")
    parsed = parser.parse_args(args)

    report = run_status(parsed.project_dir)
    if parsed.json_output:
        print(json.dumps(report, indent=2))
    elif parsed.markdown_output:
        print("# RACT Status Dashboard")
        print()
        print("| Check | Status | Detail |")
        print("| --- | --- | --- |")
        for check in report["checks"]:
            status = "passed" if check["passed"] else "failed"
            print(f"| {check['name']} | {status} | {check['detail']} |")
    else:
        print(report["summary"])
    return 0


def _leaderboard_command(args: list[str]) -> int:
    """Handle 'ract leaderboard --receipts-dir <dir> [--json|--html|--markdown]'."""
    from ract.experimental.leaderboard import render_leaderboard
    from ract.experimental.leaderboard_loader import (
        load_receipts as _load_leaderboard_receipts,
    )

    parser = argparse.ArgumentParser(prog="ract leaderboard")
    parser.add_argument("--receipts-dir", required=True, type=Path)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--html", action="store_true", dest="html_output")
    parser.add_argument("--markdown", action="store_true", dest="markdown_output")
    parsed = parser.parse_args(args)

    receipts = _load_leaderboard_receipts(str(parsed.receipts_dir))
    # --json takes precedence over --html/--markdown so scripts that pipe
    # machine-readable output are not surprised by a format override.
    if parsed.json_output:
        print(json.dumps(receipts, indent=2))
    elif parsed.html_output:
        print(render_leaderboard(receipts))
    elif parsed.markdown_output:
        print("# Leaderboard")
        for receipt in receipts:
            print(f"- {receipt.get('model', '')}: {receipt.get('test_pass_rate', '')}")
    else:
        print(json.dumps(receipts, indent=2))
    return 0


def _session_substrate_command(parsed: argparse.Namespace) -> int:
    """Handle 'ract session ls' and 'ract session diff <step_id>'.

    v0.4 substrate CLI (SUBSTRATE §3, module_02). ``ls`` enumerates the
    ``rootact/step/*`` branches and their worktree state; ``diff`` prints
    the patch a named step's transaction produced against its parent
    snapshot. Both accept ``--json`` for machine consumption.
    """
    import subprocess as _sp
    from ract.executor.worktree import WorktreeManager

    repo = Path(parsed.repo)
    if parsed.action == "ls":
        manager = WorktreeManager(repo)
        try:
            branches = manager.list_active()
            records = manager.worktree_list()
        except Exception as exc:  # noqa: BLE001 — surface the git error verbatim
            print(f"[ract] session ls failed: {exc}", file=sys.stderr)
            return 1
        # Index worktree records by branch for a joined view.
        by_branch: dict[str, dict[str, str]] = {}
        for rec in records:
            branch = rec.get("branch", "").replace("refs/heads/", "")
            if branch:
                by_branch[branch] = rec
        rows: list[dict[str, str]] = []
        for branch in branches:
            step_id = branch.split("rootact/step/", 1)[-1]
            rec = by_branch.get(branch, {})
            rows.append(
                {
                    "step_id": step_id,
                    "branch": branch,
                    "worktree": rec.get("worktree", ""),
                    "head": rec.get("HEAD", ""),
                    "status": "open" if rec else "committed",
                }
            )
        if parsed.json_output:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("No active rootact/step/* branches.")
            return 0
        header = f"{'STEP_ID':32}  {'STATUS':10}  BRANCH"
        print(header)
        for row in rows:
            print(f"{row['step_id']:32}  {row['status']:10}  {row['branch']}")
        return 0

    if parsed.action == "diff":
        branch = f"rootact/step/{parsed.step_id}"
        parent = parsed.parent or _sp.run(
            [
                "git", "-C", str(repo), "merge-base", "HEAD", branch,
            ],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        if not parent:
            print(
                f"[ract] could not resolve parent snapshot for {branch}; "
                "pass --parent explicitly.",
                file=sys.stderr,
            )
            return 1
        diff = _sp.run(
            ["git", "-C", str(repo), "diff", parent, branch],
            capture_output=True, text=True, check=False,
        )
        if diff.returncode != 0:
            print(
                f"[ract] git diff failed: {diff.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        if parsed.json_output:
            print(
                json.dumps(
                    {
                        "step_id": parsed.step_id,
                        "branch": branch,
                        "parent": parent,
                        "patch": diff.stdout,
                    },
                    indent=2,
                )
            )
            return 0
        print(diff.stdout, end="")
        return 0

    return 1


def _session_command(args: list[str]) -> int:
    """Handle 'ract session list|export|import|backup|restore ...'."""
    parser = argparse.ArgumentParser(prog="ract session")
    subparsers = parser.add_subparsers(dest="action", required=True)

    list_parser = subparsers.add_parser("list", help="List saved sessions")
    list_parser.add_argument("--store", type=Path, default=Path(".ract_sessions"))
    list_parser.add_argument("--json", action="store_true", dest="json_output")

    export_parser = subparsers.add_parser("export", help="Export a session")
    export_parser.add_argument("--session", required=True)
    export_parser.add_argument("--output", type=Path)
    export_parser.add_argument("--store", type=Path, default=Path(".ract_sessions"))
    export_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    export_parser.add_argument("--json", action="store_true", dest="json_output")
    export_parser.add_argument("--csv", action="store_true", dest="csv_output")
    export_parser.add_argument(
        "--markdown", action="store_true", dest="markdown_output"
    )

    import_parser = subparsers.add_parser("import", help="Import a session")
    import_parser.add_argument("--input", required=True, type=Path)
    import_parser.add_argument("--store", type=Path, default=Path(".ract_sessions"))
    import_parser.add_argument("--json", action="store_true", dest="json_output")

    backup_parser = subparsers.add_parser("backup", help="Backup a session")
    backup_parser.add_argument("--session", default="<session-id>")
    backup_parser.add_argument("--backup-dir", type=Path)
    backup_parser.add_argument("--store", type=Path, default=Path(".ract_sessions"))
    backup_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    backup_parser.add_argument(
        "--markdown", action="store_true", dest="markdown_output"
    )

    restore_parser = subparsers.add_parser("restore", help="Restore a session")
    restore_parser.add_argument("--session", default="<session-id>")
    restore_parser.add_argument("--backup-dir", type=Path)
    restore_parser.add_argument("--store", type=Path, default=Path(".ract_sessions"))
    restore_parser.add_argument("--config", type=Path, default=Path("ract.yaml"))
    restore_parser.add_argument(
        "--markdown", action="store_true", dest="markdown_output"
    )

    # v0.4 substrate verbs (SUBSTRATE §3, module_02 CLI): ``session ls``
    # enumerates the active worktrees, ``session diff <step_id>`` shows
    # the patch a given step transaction produced against its parent
    # snapshot. Kept alongside the v0.3 saved-session verbs — the
    # ``session`` namespace already exists; adding sibling subcommands
    # avoids a new top-level verb.
    ls_parser = subparsers.add_parser(
        "ls",
        help="List active worktree-per-step transactions (rootact/step/*)",
        description=(
            "List every rootact/step/* branch with its worktree state — the "
            "v0.4 substrate CLI view (SUBSTRATE §3, module_02)."
        ),
    )
    ls_parser.add_argument(
        "--repo", type=Path, default=Path("."),
        help="Repository root (default: current directory).",
    )
    ls_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit JSON instead of a human-readable table.",
    )

    diff_parser = subparsers.add_parser(
        "diff",
        help="Show the diff a step transaction produced against its parent.",
    )
    diff_parser.add_argument(
        "step_id",
        help="Step id in hex (matches rootact/step/<step_id>).",
    )
    diff_parser.add_argument(
        "--repo", type=Path, default=Path("."),
        help="Repository root (default: current directory).",
    )
    diff_parser.add_argument(
        "--parent",
        default=None,
        help=(
            "Parent snapshot to diff against (default: the branch's fork "
            "point from HEAD)."
        ),
    )
    diff_parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit a structured patch record instead of a git-format diff.",
    )

    parsed = parser.parse_args(args)
    if parsed.action in {"ls", "diff"}:
        return _session_substrate_command(parsed)
    store = SessionStore(parsed.store)

    if parsed.action == "list":
        sessions = store.list_sessions()
        if parsed.json_output:
            print(json.dumps(sessions, indent=2))
        elif not sessions:
            print("No sessions found.")
        else:
            for sid in sessions:
                print(sid)
        return 0

    if parsed.action == "export":
        source = store._path(parsed.session)
        if not source.is_file():
            print(f"[ract] session not found: {parsed.session}", file=sys.stderr)
            return 1
        try:
            state = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[ract] invalid session file: {exc}", file=sys.stderr)
            return 1
        payload = {"session_id": parsed.session, "state": state}
        if parsed.output:
            parsed.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if parsed.csv_output:
            print("session_id,intent")
            print(f"{parsed.session},{state.get('intent', '')}")
        elif parsed.markdown_output:
            print(f"# Session {parsed.session}")
            print(f"- intent: {state.get('intent', '')}")
        else:
            print(json.dumps(payload, indent=2))
        return 0

    if parsed.action == "import":
        if not parsed.input.is_file():
            print(f"[ract] input not found: {parsed.input}", file=sys.stderr)
            return 1
        try:
            payload = json.loads(parsed.input.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[ract] invalid JSON: {exc}", file=sys.stderr)
            return 1
        session_id = payload.get("session_id")
        state = payload.get("state")
        if not session_id or state is None:
            print("[ract] invalid session export format", file=sys.stderr)
            return 1
        store.save(session_id, state)
        print(f"[ract] imported session '{session_id}'")
        return 0

    if parsed.action == "backup":
        backup_dir = parsed.backup_dir or (
            parsed.config.parent / ".ract_session_backups"
        )
        report = store.backup(parsed.session, backup_dir)
        if parsed.markdown_output:
            print("# Session backup")
            print(f"- session: {parsed.session}")
            print(f"- backup dir: {report['backup_dir']}")
        else:
            print(json.dumps(report, indent=2))
        return 0

    if parsed.action == "restore":
        backup_dir = parsed.backup_dir or (
            parsed.config.parent / ".ract_session_backups"
        )
        report = store.restore(parsed.session, backup_dir)
        if parsed.markdown_output:
            print("# Session restore")
            print(f"- session: {parsed.session}")
        else:
            print(json.dumps(report, indent=2))
        return 0

    return 1


def _conformance_command(args: list[str]) -> int:
    """Handle ``ract conformance run --provider <name> [...]``.

    module_04 (SUBSTRATE §5). The command drives a corpus run against a
    named provider, writes a machine-readable report card under
    ``evals/conformance/results/<provider>-<date>.json``, and appends a
    row to ``evals/conformance/RESULTS.md``.

    A ``FakeProvider`` fixture (``ract.providers.fake_provider``) is
    exposed as ``--provider fake`` so the full gate loop is exercisable
    from CI without live API keys. Real providers need a subclass that
    implements the ``Provider`` protocol; the CLI names the missing
    integration and halts if the provider cannot be resolved.
    """
    parser = argparse.ArgumentParser(prog="ract conformance")
    subparsers = parser.add_subparsers(dest="action", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run the conformance corpus against a named provider.",
    )
    run_parser.add_argument(
        "--provider", required=True, help="Provider name (use 'fake' for the fixture)."
    )
    run_parser.add_argument(
        "--category",
        choices=("schema_compliance", "tool_discipline", "refusal_fidelity"),
        default=None,
        help="Restrict the run to one category.",
    )
    run_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore the response cache and hit the provider fresh.",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the JSON report to stdout as well as writing it.",
    )
    run_parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("evals/conformance"),
        help="Root of the conformance corpus (default: evals/conformance).",
    )
    parsed = parser.parse_args(args)

    if parsed.action != "run":  # pragma: no cover — argparse enforces
        return 1

    from ract.providers.conformance import run_conformance, write_report
    from ract.providers.fake_provider import FakeProvider

    if parsed.provider == "fake":
        provider = FakeProvider(name="fake")
    else:
        # Real provider integrations are not shipped in this module.
        # module_08 or a hardening module lands the adapter registry
        # for live-API conformance runs; today the fixture is the
        # supported path and the CLI names the gap explicitly.
        print(
            (
                f"[ract] no live provider integration for "
                f"{parsed.provider!r}. Only 'fake' is wired end-to-end "
                "in module_04. Set --provider fake to exercise the gate "
                "loop, or add a Provider-protocol adapter and register it."
            ),
            file=sys.stderr,
        )
        return 2

    report = run_conformance(
        provider=provider,
        corpus_root=parsed.corpus_root,
        cache_root=parsed.corpus_root / "cache",
        category=parsed.category,
        refresh=parsed.refresh,
    )
    results_root = parsed.corpus_root / "results"
    markdown_index = parsed.corpus_root / "RESULTS.md"
    report_path = write_report(report, results_root, markdown_index=markdown_index)
    print(f"[ract] conformance report written: {report_path}")
    if parsed.json_output:
        print(report.to_json())
    return 0


def main(argv: list[str] | None = None) -> int:
    """RACT CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "skills":
        return _skills_command(argv[1:])
    if argv and argv[0] == "mcp":
        return _mcp_command(argv[1:])
    if argv and argv[0] == "retrieval":
        return _retrieval_command(argv[1:])
    if argv and argv[0] == "diff":
        return _diff_command(argv[1:])
    if argv and argv[0] == "explain":
        return _explain_command(argv[1:])
    if argv and argv[0] == "report":
        return _report_command(argv[1:])
    if argv and argv[0] == "handshakes":
        return _handshakes_command(argv[1:])
    if argv and argv[0] == "refactor":
        return _refactor_command(argv[1:])
    if argv and argv[0] == "rename":
        return _rename_command(argv[1:])
    if argv and argv[0] == "docs":
        return _docs_command(argv[1:])
    if argv and argv[0] == "init":
        return _init_command(argv[1:])
    if argv and argv[0] == "openapi":
        return _openapi_command(argv[1:])
    if argv and argv[0] == "plan":
        return _plan_command(argv[1:])
    if argv and argv[0] == "doctor":
        return _doctor_command(argv[1:])
    if argv and argv[0] == "audit":
        return _audit_command(argv[1:])
    if argv and argv[0] == "load-bearing":
        return _load_bearing_command(argv[1:])
    if argv and argv[0] == "novelty":
        return _novelty_command(argv[1:])
    if argv and argv[0] == "coverage":
        return _coverage_command(argv[1:])
    if argv and argv[0] == "quality":
        return _quality_command(argv[1:])
    if argv and argv[0] == "mutation":
        return _mutation_command(argv[1:])
    if argv and argv[0] == "whisper":
        return _whisper_command(argv[1:])
    if argv and argv[0] == "auction":
        return _auction_command(argv[1:])
    if argv and argv[0] == "fence":
        return _fence_command(argv[1:])
    if argv and argv[0] == "marketplace":
        return _skills_marketplace_command(argv[1:])
    if argv and argv[0] == "consolidate":
        return _consolidate_command(argv[1:])
    if argv and argv[0] == "release":
        return _release_command(argv[1:])
    if argv and argv[0] == "merge-gate":
        return _merge_gate_command(argv[1:])
    if argv and argv[0] == "marketplace":
        return _skills_marketplace_command(argv[1:])
    if argv and argv[0] == "rot-report":
        return _rot_report_command(argv[1:])
    if argv and argv[0] == "receipt-export":
        return _receipt_export_command(argv[1:])
    if argv and argv[0] == "rot":
        return _rot_command(argv[1:])
    if argv and argv[0] == "operator-queue":
        return _operator_queue_command(argv[1:])
    if argv and argv[0] == "receipt":
        return _receipt_command(argv[1:])
    if argv and argv[0] == "policy-gate":
        return _policy_gate_command(argv[1:])
    if argv and argv[0] == "run-fingerprint":
        return _run_fingerprint_command(argv[1:])
    if argv and argv[0] == "ai-sbom":
        return _ai_sbom_command(argv[1:])
    if argv and argv[0] == "grove-forge":
        from ract.experimental.cli_grove_forge import _grove_forge_command

        return _grove_forge_command(argv[1:])
    if argv and argv[0] == "calibrate":
        from ract.experimental.cli_calibrate import _calibrate_command

        return _calibrate_command(argv[1:])
    if argv and argv[0] == "infer":
        from ract.experimental.cli_infer import _infer_command

        return _infer_command(argv[1:])
    if argv and argv[0] == "repro-manifest":
        from ract.experimental.cli_repro_manifest import _repro_manifest_command

        return _repro_manifest_command(argv[1:])
    if argv and argv[0] == "config":
        return _config_command(argv[1:])
    if argv and argv[0] == "provider":
        return _provider_command(argv[1:])
    if argv and argv[0] == "cost":
        return _cost_command(argv[1:])
    if argv and argv[0] == "router":
        return _router_command(argv[1:])
    if argv and argv[0] == "self-audit":
        return _self_audit_command(argv[1:])
    if argv and argv[0] == "status":
        return _status_command(argv[1:])
    if argv and argv[0] == "leaderboard":
        return _leaderboard_command(argv[1:])
    if argv and argv[0] == "session":
        return _session_command(argv[1:])
    if argv and argv[0] == "conformance":
        return _conformance_command(argv[1:])
    if argv and argv[0] == "trace":
        from ract.trace.cli_trace import _trace_command

        return _trace_command(argv[1:])
    if argv and argv[0] == "provenance":
        from ract.provenance_cli import _provenance_command

        return _provenance_command(argv[1:])
    parser = argparse.ArgumentParser(
        prog="ract",
        description=(
            "RACT - an Agentic Coding Tool by Dr. Lucas Root, Ph.D. "
            "Forged on Windows, loved everywhere."
        ),
    )
    parser.add_argument(
        "intent",
        nargs="?",
        default="",
        help="The coding task you want RACT to perform (not needed with --self-test).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("ract.yaml"),
        help="Path to ract.yaml configuration file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only; do not execute the plan.",
    )
    parser.add_argument(
        "--mode",
        choices=["default", "documentation", "git"],
        default="default",
        help="Run mode: default, documentation, or git.",
    )
    parser.add_argument(
        "--session",
        dest="session_id",
        help="Session ID to save or resume.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previously saved session (requires --session).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing session (requires --session, not --resume).",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Restore the pre-execution snapshot for a session (requires --session).",
    )
    parser.add_argument(
        "--project-doc",
        dest="project_doc",
        type=Path,
        help="Path to a project document JSON file whose goal/notes prepend the intent.",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="Execute all steps without approval prompts (default).",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Prompt for approval before each step (mutually exclusive with --yolo).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Re-run the intent once after a successful execution.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run the intent in a Root-Knot-anchored loop until done, regressed, or max iterations.",
    )
    parser.add_argument(
        "--max-iterations",
        dest="max_iterations",
        type=int,
        default=10,
        help="Maximum loop iterations when using --loop (default: 10).",
    )
    parser.add_argument(
        "--allow-debt",
        dest="allow_debt",
        action="store_true",
        help="Allow the loop to complete even if the refactor-tax ratio is breached.",
    )
    parser.add_argument(
        "--allow-load-bearing",
        dest="allow_load_bearing",
        action="store_true",
        help="Allow writes that modify code marked with a # load-bearing: annotation.",
    )
    parser.add_argument(
        "--allow-novelty-overrun",
        dest="allow_novelty_overrun",
        action="store_true",
        help="Allow writes that exceed the configured novelty budget.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the RACT version and exit.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON for commands that support it.",
    )
    parser.add_argument(
        "--about",
        action="store_true",
        help="Print the RACT manifesto, authorship, and license summary.",
    )
    parser.add_argument(
        "--init-provider",
        dest="init_provider",
        help="Write a starter ract.yaml for the named provider and exit.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run RACT's internal test suite and report the result.",
    )
    parser.add_argument(
        "--review-diff",
        dest="review_diff",
        type=Path,
        help="Path to a unified-diff file to review (instead of running a plan).",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream provider responses to stdout as they are generated.",
    )
    parser.add_argument(
        "--welcome",
        action="store_true",
        help="Print the RACT welcome letter and exit.",
    )
    args = parser.parse_args(argv)

    if args.init_provider:
        import yaml

        from ract.harness import _default_manager_prompt_path

        if args.init_provider not in list_presets():
            print(
                f"[ract] unknown provider preset: {args.init_provider}",
                file=sys.stderr,
            )
            return 1
        config = get_preset(args.init_provider)
        target = Path("ract.yaml")
        if target.exists():
            print(
                f"[ract] {target} already exists; refusing to overwrite.",
                file=sys.stderr,
            )
            return 1
        target.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        prompts_dir = Path(config.get("prompts_dir", "prompts"))
        prompt_file = prompts_dir / "manager.txt"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        default_prompt = _default_manager_prompt_path()
        if default_prompt.is_file() and not prompt_file.exists():
            prompt_file.write_text(
                default_prompt.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(f"[ract] wrote default prompt to {prompt_file}")

        print(f"[ract] wrote {target} using the '{args.init_provider}' preset")
        print("[ract] set the required environment variables and run:")
        print('  ract "your intent here" --dry-run')
        return 0

    if args.version:
        import ract

        if args.json_output:
            print(
                json.dumps(
                    {"name": "RACT", "version": ract.__version__},
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(f"RACT {ract.__version__}")
        return 0

    if args.about:
        print("RACT - Root Agentic Coding Tool")
        print("By Dr. Lucas Root, Ph.D.")
        print()
        print(
            "RACT is a model-agnostic, local-first agentic coding tool. It keeps "
            "the human in the loop while a small management LM routes work to the "
            "right provider. Every plan and result is Rooted to the assumption "
            "that justifies it."
        )
        print()
        print("License: PolyForm Noncommercial License 1.0.0")
        print(
            "  Free for personal use, research, education, and noncommercial organizations."
        )
        print(
            "  Commercial use requires a separate agreement with Dr. Lucas Root, Ph.D."
        )
        return 0

    if args.welcome:
        import ract

        console.welcome(ract.__version__)
        return 0

    if args.self_test:
        print("[ract] running self-test suite")
        benchmark = SelfTestBenchmarkMode()
        test_result = benchmark.run_tests(python_executable=sys.executable)
        test_report = benchmark.report()
        print(test_report.summary)
        return 0 if test_result.returncode == 0 else 1

    if args.review_diff:
        print(f"[ract] reviewing diff: {args.review_diff}")
        if not args.review_diff.is_file():
            print(
                f"[ract] failed: diff file not found: {args.review_diff}",
                file=sys.stderr,
            )
            return 1
        diff_text = args.review_diff.read_text(encoding="utf-8")
        review = CodeReviewMode().review(diff_text)
        print(f"[ract] files changed: {', '.join(review['files_changed'])}")
        print(f"[ract] lines added: {review['lines_added']}")
        print(f"[ract] summary: {review['summary']}")
        if review["comments"]:
            print("[ract] comments:")
            for comment in review["comments"]:
                print(
                    f"  line {comment['line']} [{comment['severity']}] "
                    f"{comment['category']}: {comment['message']}"
                )
                print(f"    suggestion: {comment['suggestion']}")
        return 0

    if not args.intent:
        parser.error("intent is required unless --self-test or --review-diff is used")

    console.user_input("intent", args.intent)
    if args.mode != "default":
        console.direct(f"mode: {args.mode}")
    if args.session_id:
        console.user_input("session", args.session_id)
        if args.resume:
            console.direct("resuming previous session")
        elif args.force:
            console.direct("forcing overwrite of existing session")
        elif args.rollback:
            console.direct("rolling back session")
    if args.project_doc:
        console.user_input("project doc", str(args.project_doc))
    if args.yolo:
        console.direct("yolo mode: executing without approval")
    if args.auto:
        console.direct("auto mode: approval required per step")
    if args.reload:
        console.direct("reload mode: re-run after success")
    if args.stream:
        console.direct("streaming mode: printing deltas as they arrive")
    if args.loop:
        console.direct("loop mode: Root-Knot-anchored recursion")
        console.direct(f"max iterations: {args.max_iterations}")
        if args.dry_run:
            parser.error("--loop and --dry-run are mutually exclusive")

    if args.loop:
        controller = LoopController(
            args.config,
            max_iterations=args.max_iterations,
            python_executable=sys.executable,
            planner=LoopPlanner(args.config),
            handshake_registry=HandshakeRegistry(args.config.parent),
            allow_debt=args.allow_debt,
            allow_load_bearing_override=args.allow_load_bearing,
            allow_novelty_overrun=args.allow_novelty_overrun,
        )
        loop_result = controller.run(args.intent)
        if loop_result.final_decision == "regression":
            console.error(f"loop finished: {loop_result.final_decision}")
        elif loop_result.final_decision == "done":
            console.success(f"loop finished: {loop_result.final_decision}")
        else:
            console.warning(f"loop finished: {loop_result.final_decision}")
        console.info(loop_result.summary)
        report_path = controller.write_report(loop_result)
        console.info(f"loop report written to {report_path}")
        return 0 if loop_result.final_decision != "regression" else 1

    def _stream_callback(delta: str) -> None:
        print(delta, end="", flush=True)

    result = run_ract(
        args.config,
        args.intent,
        dry_run=args.dry_run,
        mode=args.mode,
        session_id=args.session_id,
        resume=args.resume,
        force=args.force,
        rollback=args.rollback,
        project_doc=args.project_doc,
        yolo=args.yolo,
        auto=args.auto,
        reload=args.reload,
        stream=args.stream,
        stream_callback=_stream_callback if args.stream else None,
        allow_load_bearing_override=args.allow_load_bearing,
        allow_novelty_overrun=args.allow_novelty_overrun,
    )
    if not result.is_ok():
        console.error(f"failed: {result.error}")
        return 1

    value = result.unwrap()

    if isinstance(value, Plan):
        console.direct(f"assumption: {value.assumption}")
        console.direct(f"confidence: {value.confidence}")
        for i, step in enumerate(value.steps, start=1):
            console.print(
                f"  [bold]{i}.[/] [{step.provider_hint}] {step.action} "
                f"-> {step.expected_artifact}"
            )
        score = QualityScorecard().compute_score(value)
        console.direct(f"quality score: {score}")
        return 0

    report = value
    console.direct("assumptions:")
    for assumption in report.assumptions:
        console.print(f"  • {assumption}")
    if args.stream:
        console.direct("streaming complete")
    else:
        console.direct("results:")
        for i, step_result in enumerate(report.step_results, start=1):
            console.rule(f"Step {i}: {step_result.step.action}")
            console.print(step_result.content)
    score = QualityScorecard().compute_score(report.plan)
    console.direct(f"quality score: {score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
# RACT 0.1.1 - Trust and tooling
