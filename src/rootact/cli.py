# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Command-line interface for RootAct."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from rootact.builtin_skill_library import BuiltinSkillLibrary
from rootact.chestertons_fence import ChestertonsFence
from rootact.code_review_mode import CodeReviewMode
from rootact.compression_novelty_detector import CompressionNoveltyDetector
from rootact.consolidate import ConsolidationScanner, MergeProposal
from rootact.dead_code_auction import DeadCodeAuction
from rootact.skill_marketplace import SkillMarketplace
from rootact.doc_generator import DocGenerator
from rootact.diff_applier import DiffApplier
from rootact.handshake_registry import HandshakeRegistry
from rootact.harness import _build_retrieval_adapter
from rootact.legacy_whisperer import LegacyWhisperer
from rootact.tui import console
from rootact.load_bearing_guard import LoadBearingGuard
from rootact.loop_controller import LoopController
from rootact.loop_planner import LoopPlanner
from rootact.mcp_adapter import McpToolRegistry
from rootact.mutation_runner import run_mutation_tests
from rootact.providers.router import ProviderRouter
from rootact.openapi_client_generator import OpenApiClientGenerator
from rootact.doctor import RactDoctor
from rootact.openapi_server_generator import OpenApiServerGenerator
from rootact.plan_replay import PlanReplay
from rootact.plan_serializers import load_plan, save_plan
from rootact.project_initializer import ProjectInitializer, list_templates
from rootact.provider_presets import get_preset, list_presets
from rootact.manager import Plan
from rootact.quality_scorecard import QualityScorecard
from rootact.rootact_runner import run_rootact
from rootact.run_reporter import RunReporter
from rootact.self_test_benchmark_mode import SelfTestBenchmarkMode
from rootact.session_store import SessionStore
from rootact.skills_registry import SkillRegistry
from rootact.symbol_renamer import SymbolRenamer


def _handshakes_command(args: list[str]) -> int:
    """Handle 'rootact handshakes list/approve/reject <id>'."""
    parser = argparse.ArgumentParser(prog="rootact handshakes")
    parser.add_argument(
        "action",
        choices=["list", "approve", "reject", "defer"],
        help="Action to perform on the handshake registry.",
    )
    parser.add_argument(
        "milestone_id", nargs="?", help="Milestone id for approve/reject/defer."
    )
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    registry = HandshakeRegistry(parsed.config.parent)
    if parsed.action == "list":
        items = registry.entries()
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

    if parsed.milestone_id is None:
        parser.error("milestone_id is required for approve/reject/defer")
    status_map = {"approve": "approved", "reject": "rejected", "defer": "deferred"}
    status = status_map[parsed.action]
    try:
        registry.update_status(parsed.milestone_id, status)
    except KeyError as exc:
        print(f"[rootact] {exc}", file=sys.stderr)
        return 1
    print(f"[rootact] handshake '{parsed.milestone_id}' marked {status}")
    return 0


def _mcp_command(args: list[str]) -> int:
    """Handle 'rootact mcp list' and 'rootact mcp invoke'.

    LR:: Lists tools exposed by configured MCP servers so users can see what
    external capabilities RACT can invoke before running a plan. The invoke
    action lets operators call a configured tool directly from the terminal
    for quick verification or one-off tasks.
    """
    parser = argparse.ArgumentParser(prog="rootact mcp")
    parser.add_argument(
        "action",
        choices=["list", "invoke"],
        help="MCP action to perform.",
    )
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
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
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[rootact] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[rootact] failed to parse config: {exc}", file=sys.stderr)
        return 1

    registry = McpToolRegistry.from_config(config)

    if parsed.action == "invoke":
        return _mcp_invoke(registry, parsed.tool, parsed.input_json)

    tools_rooted = registry.list_all_tools()
    if tools_rooted.error is not None:
        print(
            f"[rootact] failed to list MCP tools: {tools_rooted.error}", file=sys.stderr
        )
        return 1

    tools = tools_rooted.value or []
    if not tools:
        console.info("No MCP tools configured or reachable.")
        console.direct("Add an 'mcp_servers:' section to rootact.yaml to expose tools.")
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
        print(
            "[rootact] invoke requires --tool <server_name/tool_name>", file=sys.stderr
        )
        return 1
    try:
        arguments: dict[str, Any] = json.loads(input_json)
    except json.JSONDecodeError as exc:
        print(f"[rootact] invalid --input JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(arguments, dict):
        print("[rootact] --input must be a JSON object.", file=sys.stderr)
        return 1

    result = registry.call_tool(tool, arguments)
    if result.error is not None:
        print(f"[rootact] MCP tool failed: {result.error}", file=sys.stderr)
        return 1

    tool_result = result.unwrap()
    if tool_result.is_error:
        print("[rootact] tool reported an error.", file=sys.stderr)
    for item in tool_result.content or []:
        text = item.get("text") if isinstance(item, dict) else None
        if text:
            console.direct(text)
        else:
            console.direct(json.dumps(item))
    return 0


def _retrieval_command(args: list[str]) -> int:
    """Handle 'rootact retrieval search <query>'.

    LR:: Lets operators preview what context RACT retrieves for a query before
    invoking the management model. Works with the keyword adapter by default and
    web-search adapters when configured.
    """
    parser = argparse.ArgumentParser(prog="rootact retrieval")
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    if parsed.action is None:
        parser.print_help()
        return 1

    if parsed.query is None:
        parser.error("query is required for search")

    if not parsed.config.is_file():
        print(f"[rootact] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[rootact] failed to parse config: {exc}", file=sys.stderr)
        return 1

    project_dir = parsed.config.parent.resolve()
    adapter = _build_retrieval_adapter(config, project_dir)
    if adapter is None:
        print("No retrieval adapter configured. Falling back to keyword search.")
        from rootact.retrieval_adapter import KeywordRetrievalAdapter

        adapter = KeywordRetrievalAdapter(project_dir)

    results_rooted = adapter.search(parsed.query, top_k=parsed.top_k)
    if results_rooted.error is not None:
        print(f"[retrieval] failed: {results_rooted.error}", file=sys.stderr)
        return 1

    results = results_rooted.value or []
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
    """Handle 'rootact report --last' and 'rootact report --session <id>'.

    LR:: Supports both human-readable text and JSON output, with optional file
    export, so the run report can be consumed by humans, scripts, or CI.
    """
    parser = argparse.ArgumentParser(prog="rootact report")
    parser.add_argument(
        "--last", action="store_true", help="Show the last loop report."
    )
    parser.add_argument("--session", help="Show the report for a saved session.")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the report to this file instead of stdout.",
    )
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    reporter = RunReporter(parsed.config.parent)
    if parsed.last:
        if parsed.format == "json":
            payload = reporter.render_last_loop_json()
            output = "{}" if payload is None else json.dumps(payload, indent=2)
        else:
            output = reporter.render_last_loop()
    elif parsed.session:
        if parsed.format == "json":
            payload = reporter.render_session_json(parsed.session)
            output = "{}" if payload is None else json.dumps(payload, indent=2)
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
    """Handle 'rootact diff apply --patch <path> [--dry-run]'.

    LR:: Applies a unified-diff patch file to the project. In dry-run mode it
    previews which files would change and where, without writing anything.
    """
    parser = argparse.ArgumentParser(prog="rootact diff")
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    if parsed.action is None:
        parser.print_help()
        return 1

    if parsed.patch is None:
        print("[rootact] --patch is required for apply", file=sys.stderr)
        return 1

    if not parsed.patch.is_file():
        print(f"[rootact] patch file not found: {parsed.patch}", file=sys.stderr)
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

    print(f"[rootact] diff {parsed.action}: {applied} applied, {failed} failed")
    for result in results:
        rel = result.path.relative_to(project_dir)
        status = "APPLIED" if result.applied else "FAILED"
        print(f"  [{status}] {rel}: {result.message}")
        if parsed.dry_run and result.backup:
            print(f"    (dry-run: restored from {result.backup.name})")

    return 0 if failed == 0 else 1


def _explain_command(args: list[str]) -> int:
    """Handle 'rootact explain --intent <text> | --plan <path>'.

    LR:: Generates a dry-run plan and narrates it in plain language so the
    operator understands what RACT intends to do before any files are written.
    This is a local-only preview: it does not call the management model beyond
    the planning step already required for dry-run.
    """
    parser = argparse.ArgumentParser(prog="rootact explain")
    parser.add_argument("--intent", help="The coding task to explain.")
    parser.add_argument(
        "--plan", type=Path, help="Path to a saved plan JSON to explain."
    )
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.intent and not parsed.plan:
        parser.print_help()
        return 1

    plan: Plan | None = None
    if parsed.plan:
        try:
            plan = load_plan(parsed.plan)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            print(f"[rootact] failed to load plan: {exc}", file=sys.stderr)
            return 1
    else:
        result = run_rootact(
            parsed.config,
            parsed.intent,
            dry_run=True,
        )
        if not result.is_ok():
            print(f"[rootact] planning failed: {result.error}", file=sys.stderr)
            return 1
        value = result.unwrap()
        if not isinstance(value, Plan):
            print("[rootact] dry-run did not return a plan.", file=sys.stderr)
            return 1
        plan = value

    assert plan is not None
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
    """Handle 'rootact skills list|install|install-all|marketplace ...'."""
    if args and args[0] == "marketplace":
        return _skills_marketplace_command(args[1:])

    library = BuiltinSkillLibrary()
    if not args or args[0] == "list":
        skills = library.list_skills()
        console.rule("Built-in RACT skills")
        console.table(
            title="",
            columns=["Skill", "Description"],
            rows=[[skill["name"], skill["description"]] for skill in skills],
        )
        return 0
    if args[0] == "install" and len(args) == 2:
        name = args[1]
        registry = SkillRegistry()
        try:
            path = library.install(name, registry)
        except KeyError as exc:
            print(f"[rootact] {exc}", file=sys.stderr)
            return 1
        print(f"[rootact] installed skill '{name}' to {path}")
        return 0
    if args[0] == "install-all":
        registry = SkillRegistry()
        installed = library.install_all(registry)
        print(
            f"[rootact] installed {len(installed)} built-in skills: {', '.join(installed)}"
        )
        return 0
    print(
        "[rootact] usage: rootact skills list | rootact skills install <name> | "
        "rootact skills install-all | rootact skills marketplace list|install",
        file=sys.stderr,
    )
    return 1


def _skills_marketplace_command(args: list[str]) -> int:
    """Handle 'rootact skills marketplace list' and 'install --name <name>'."""
    parser = argparse.ArgumentParser(prog="rootact skills marketplace")
    subparsers = parser.add_subparsers(dest="action", required=True)

    list_parser = subparsers.add_parser("list", help="List skills in the marketplace")
    list_parser.add_argument("--project-dir", type=Path, default=Path("."))
    list_parser.add_argument(
        "--catalog",
        default=None,
        help="URL or path to a marketplace catalog JSON file.",
    )
    install_parser = subparsers.add_parser("install", help="Install a skill")
    install_parser.add_argument("--project-dir", type=Path, default=Path("."))
    install_parser.add_argument(
        "--catalog",
        default=None,
        help="URL or path to a marketplace catalog JSON file.",
    )
    install_parser.add_argument("--name", required=True, help="Skill name to install")

    parsed = parser.parse_args(args)
    marketplace = SkillMarketplace(parsed.catalog)

    if parsed.action == "list":
        try:
            skills = marketplace.list_skills()
        except Exception as exc:  # noqa: BLE001
            print(
                f"[rootact] failed to load marketplace catalog: {exc}", file=sys.stderr
            )
            return 1
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
        registry = SkillRegistry(parsed.project_dir)
        try:
            path = marketplace.install(parsed.name, registry)
        except (KeyError, ValueError, httpx.HTTPError, OSError) as exc:
            print(f"[rootact] failed to install skill: {exc}", file=sys.stderr)
            return 1
        print(f"[rootact] installed marketplace skill '{parsed.name}' to {path}")
        return 0

    return 1


def _refactor_command(args: list[str]) -> int:
    """Handle 'rootact refactor --old <name> --new <name> [--module <module>]'."""
    parser = argparse.ArgumentParser(prog="rootact refactor")
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
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


def _docs_command(args: list[str]) -> int:
    """Handle 'rootact docs generate [--output-dir <dir>] [--config <path>]'.

    LR:: A concrete documentation-generation command so Documentation Mode is
    not just an intent rewrite; it can produce Markdown from the source tree.
    """
    parser = argparse.ArgumentParser(prog="rootact docs")
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    generator = DocGenerator(project_dir, output_dir=parsed.output_dir)
    written = generator.generate()
    if not written:
        print("[rootact] no Python files found; no docs generated.")
        return 0

    print(f"[rootact] generated {len(written)} doc file(s) in {generator.output_dir}")
    for path in written:
        rel = path.relative_to(project_dir)
        print(f"  - {rel}")
    return 0


def _init_command(args: list[str]) -> int:
    """Handle 'rootact init --template <name> --provider <name> [--config <path>]'.

    LR:: Scaffolds a brand-new project from a template and provider preset. This
    is the concrete implementation of the configuration-driven project-templates
    use case.
    """
    parser = argparse.ArgumentParser(prog="rootact init")
    parser.add_argument(
        "--template",
        required=True,
        choices=list_templates(),
        help="Project template to use.",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=list_presets(),
        help="Provider preset for rootact.yaml.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("rootact.yaml"),
        help="Target rootact.yaml path (default: ./rootact.yaml).",
    )
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    try:
        result = ProjectInitializer(
            project_dir, parsed.template, parsed.provider
        ).initialize()
    except FileExistsError as exc:
        print(f"[rootact] failed: {exc}", file=sys.stderr)
        return 1
    except KeyError as exc:
        print(f"[rootact] failed: {exc}", file=sys.stderr)
        return 1

    print(f"[rootact] initialized {result.template} project at {result.project_dir}")
    print(f"[rootact] provider: {result.provider}")
    for path in result.files_written:
        rel = path.relative_to(project_dir)
        print(f"  - {rel}")
    return 0


def _openapi_command(args: list[str]) -> int:
    """Handle 'rootact openapi generate-client|generate-server --spec <path> --output <path>'.

    LR:: Generates a small, httpx-based Python client or a FastAPI server module
    from an OpenAPI 3 spec.
    """
    parser = argparse.ArgumentParser(prog="rootact openapi")
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
        print(f"[rootact] failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"[rootact] generated {name} with "
        f"{result.operation_count} operation(s) at {result.module_path}"
    )
    return 0


def _plan_command(args: list[str]) -> int:
    """Handle 'rootact plan export|replay'.

    LR:: Exposes PlanReplay through the CLI so users can save a session's plan
    to disk and replay it later for reproducibility or regression testing.
    """
    parser = argparse.ArgumentParser(prog="rootact plan")
    subparsers = parser.add_subparsers(dest="action")

    export = subparsers.add_parser("export", help="Export a session plan to JSON.")
    export.add_argument("--session", required=True, help="Session id to export.")
    export.add_argument("--output", required=True, type=Path, help="Output JSON path.")
    export.add_argument("--config", type=Path, default=Path("rootact.yaml"))

    replay = subparsers.add_parser("replay", help="Replay a saved plan.")
    replay.add_argument(
        "--plan", required=True, type=Path, help="Path to saved plan JSON."
    )
    replay.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without side effects (default).",
    )

    parsed = parser.parse_args(args)
    if parsed.action is None:
        parser.print_help()
        return 1

    if parsed.action == "export":
        store = SessionStore(parsed.config.parent / ".rootact" / "sessions")
        try:
            state = store.load(parsed.session)
        except KeyError as exc:
            print(f"[rootact] failed: session not found: {exc}", file=sys.stderr)
            return 1
        plan = state.get("plan")
        if plan is None:
            print("[rootact] failed: session has no plan", file=sys.stderr)
            return 1
        save_plan(plan, parsed.output)
        print(f"[rootact] exported plan to {parsed.output}")
        return 0

    # replay
    plan = load_plan(parsed.plan)
    replay_obj = PlanReplay()

    def _noop_executor(action: str) -> None:
        return None

    report = replay_obj.replay(plan, _noop_executor)
    print(f"[rootact] replay summary: {report.summary}")
    for result in report.results:
        status = "OK" if result.success else "FAIL"
        print(f"  [{status}] {result.action}")
    return 0 if report.success else 1


def _doctor_command(args: list[str]) -> int:
    """Handle 'rootact doctor [--config <path>] [--check-providers]'.

    LR:: Runs configuration and project-structure diagnostics so users can fix
    setup problems before invoking a model. Add --check-providers to actually
    ping each configured provider endpoint.
    """
    parser = argparse.ArgumentParser(prog="rootact doctor")
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parser.add_argument(
        "--check-providers",
        dest="check_providers",
        action="store_true",
        help="Ping each configured provider endpoint (slower, requires network).",
    )
    parsed = parser.parse_args(args)

    results = RactDoctor(parsed.config).diagnose(check_providers=parsed.check_providers)
    passed = sum(1 for r in results if r.passed)
    total = len(results)

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


def _load_bearing_command(args: list[str]) -> int:
    """Handle 'rootact load-bearing list [--config <path>]'.

    LR:: Lists annotated load-bearing regions so operators can see what legacy
    code RACT will refuse to modify without an explicit override.
    """
    parser = argparse.ArgumentParser(prog="rootact load-bearing")
    parser.add_argument(
        "action",
        choices=["list"],
        help="Load-bearing action to perform.",
    )
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[rootact] config not found: {parsed.config}", file=sys.stderr)
        return 1

    guard = LoadBearingGuard(parsed.config.parent)
    regions_by_file = guard.scan_project()
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
    """Handle 'rootact novelty scan [--json] [--config <path>]'.

    LR:: Exposes the compression-based novelty detector so operators can preview
    which files are structurally close to the existing codebase (low novelty /
    possible duplication) and which are outliers (high novelty / needs strong
    review). This is a local-only, information-theoretic anti-rot signal.
    """
    parser = argparse.ArgumentParser(prog="rootact novelty")
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    project_dir = parsed.config.parent.resolve()
    detector = CompressionNoveltyDetector(project_dir)
    result = detector.scan_project()

    if parsed.json_output:
        print(json.dumps(result, indent=2))
        return 0

    console.rule(f"novelty scan: {project_dir}")
    console.info(
        f"dictionary trained: {result['has_dictionary']} "
        f"({result['sample_count']} samples)"
    )
    if not result["scores"]:
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
    """Handle 'rootact coverage delta [--run] [--before <path>] [--after <path>] [--config <path>]'.

    LR:: Exposes the earned-coverage gate. Without arguments it compares two
    existing pytest-cov JSON reports. With --run it captures before/after
    snapshots by invoking pytest directly.
    """
    parser = argparse.ArgumentParser(prog="rootact coverage")
    parser.add_argument(
        "action",
        choices=["delta"],
        help="Coverage action to perform.",
    )
    parser.add_argument(
        "--run",
        dest="run_snapshot",
        action="store_true",
        help="Run pytest twice and compute the delta directly.",
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    from rootact.coverage_delta import (
        compute_delta,
        gate,
        read_snapshot,
    )

    project_dir = parsed.config.parent.resolve()

    if parsed.run_snapshot:
        delta_rooted = gate(project_dir, min_percent=parsed.min_percent)
        if not delta_rooted.is_ok():
            print(
                f"[rootact] coverage gate failed: {delta_rooted.error}", file=sys.stderr
            )
            return 1
        delta = delta_rooted.unwrap()
    else:
        if parsed.before is None or parsed.after is None:
            print(
                "[rootact] coverage delta requires --before and --after, or --run.",
                file=sys.stderr,
            )
            return 1
        before_rooted = read_snapshot(parsed.before)
        if not before_rooted.is_ok():
            print(
                f"[rootact] failed to read before snapshot: {before_rooted.error}",
                file=sys.stderr,
            )
            return 1
        after_rooted = read_snapshot(parsed.after)
        if not after_rooted.is_ok():
            print(
                f"[rootact] failed to read after snapshot: {after_rooted.error}",
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


def _mutation_command(args: list[str]) -> int:
    """Handle 'rootact mutation run [--script <path>] [--timeout <sec>] [--wsl-distro <name>] [--config <path>]'.

    LR:: Wraps the WSL mutation-testing script and prints a structured mutation
    score. This makes mutation testing accessible from the main CLI instead of
    requiring a manual WSL invocation.
    """
    parser = argparse.ArgumentParser(prog="rootact mutation")
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
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
            f"[rootact] mutation testing failed: {report_rooted.error}",
            file=sys.stderr,
        )
        return 1
    report = report_rooted.unwrap()
    print(report)
    return 0


def _whisper_command(args: list[str]) -> int:
    """Handle 'rootact whisper --intent <text> [--paths p1,p2] [--config <path>]'.

    LR:: Runs the Legacy Whisperer subagent to produce a pre-planning brief on
    the codebase's dialect, conventions, and recent history. No files are
    written; this is a pure orientation call.
    """
    parser = argparse.ArgumentParser(prog="rootact whisper")
    parser.add_argument("--intent", required=True, help="The coding task to orient.")
    parser.add_argument(
        "--paths",
        help="Comma-separated list of files to focus the brief on.",
    )
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[rootact] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[rootact] failed to parse config: {exc}", file=sys.stderr)
        return 1

    router = ProviderRouter(config.get("providers", {}))
    manager_provider = config.get("manager_provider", "local")
    adapter_rooted = router.get_adapter(manager_provider)
    if not adapter_rooted.is_ok():
        print(
            f"[rootact] failed to load provider '{manager_provider}': {adapter_rooted.error}",
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
        print(f"[rootact] whisper failed: {brief_rooted.error}", file=sys.stderr)
        return 1

    print("Legacy Whisperer brief")
    print("======================")
    print(brief_rooted.unwrap())
    print()
    print(
        "Root Knot dialect note: this brief is advisory; the loop still verifies every artifact."
    )
    return 0


def _auction_command(args: list[str]) -> int:
    """Handle 'rootact auction list [--min-age-days N] [--json] [--config <path>]'.

    LR:: Lists dead-code candidates: old Python modules with no inbound
    references from the rest of the project. The list is for review; nothing is
    deleted automatically.
    """
    parser = argparse.ArgumentParser(prog="rootact auction")
    parser.add_argument(
        "action",
        choices=["list"],
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[rootact] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[rootact] failed to parse config: {exc}", file=sys.stderr)
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
    """Handle 'rootact fence inspect --file <path> [--lines N-M] [--config <path>]'.

    LR:: Runs Chesterton's Fence: a subagent that reads blame/history for a
    legacy region and produces a plausible reason it exists. The fence is a
    guard, not a veto; it makes uninformed changes expensive.
    """
    parser = argparse.ArgumentParser(prog="rootact fence")
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
    parser.add_argument("--config", type=Path, default=Path("rootact.yaml"))
    parsed = parser.parse_args(args)

    if not parsed.config.is_file():
        print(f"[rootact] config not found: {parsed.config}", file=sys.stderr)
        return 1

    import yaml

    try:
        config = yaml.safe_load(parsed.config.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"[rootact] failed to parse config: {exc}", file=sys.stderr)
        return 1

    router = ProviderRouter(config.get("providers", {}))
    manager_provider = config.get("manager_provider", "local")
    adapter_rooted = router.get_adapter(manager_provider)
    if not adapter_rooted.is_ok():
        print(
            f"[rootact] failed to load provider '{manager_provider}': {adapter_rooted.error}",
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
                "[rootact] --lines must be formatted as 'start-end'",
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
        print(f"[rootact] fence failed: {brief_rooted.error}", file=sys.stderr)
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
    """Handle 'rootact consolidate [scan|apply|rollback] ...'.

    LR:: Identifies near-duplicate modules, previews merges as unified diffs,
    queues proposals, and applies/rolls back approved merges.
    """
    parser = argparse.ArgumentParser(prog="rootact consolidate")
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
            "[rootact] --similarity-threshold must be between 0.0 and 1.0",
            file=sys.stderr,
        )
        return 1
    if not (0.0 <= parsed.merge_threshold <= 1.0):
        print(
            "[rootact] --merge-threshold must be between 0.0 and 1.0",
            file=sys.stderr,
        )
        return 1
    if parsed.max_modules < 1:
        print("[rootact] --max-modules must be >= 1", file=sys.stderr)
        return 1

    scanner = ConsolidationScanner(parsed.project_dir)
    result = scanner.scan(
        similarity_threshold=parsed.similarity_threshold,
        merge_threshold=parsed.merge_threshold,
        max_modules=parsed.max_modules,
        paths=parsed.paths,
    )

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
    print("Use 'rootact handshakes' to inspect and approve.")
    return 0


def _consolidate_apply(parsed: argparse.Namespace) -> int:
    """Apply a single approved consolidation proposal."""
    from rootact.consolidate import ConsolidationApplier

    registry = HandshakeRegistry(parsed.project_dir)
    try:
        item = registry.update_status(parsed.id, "approved")
    except KeyError:
        print(f"[rootact] proposal not found: {parsed.id}", file=sys.stderr)
        return 1

    # Reconstruct the proposal from the handshake description. This is a v0
    # simplification; a later version should store structured proposal data.
    lines = item.description.splitlines()
    target_line = [ln for ln in lines if ln.startswith("Proposal: merge into ")]
    sources_line = [ln for ln in lines if ln.startswith("Sources: ")]
    if not target_line or not sources_line:
        print("[rootact] malformed proposal description", file=sys.stderr)
        return 1
    target = target_line[0].replace("Proposal: merge into ", "").strip()
    sources = tuple(
        s.strip() for s in sources_line[0].replace("Sources: ", "").split(",")
    )
    proposal = MergeProposal(
        target=target,
        sources=sources,
        diff="",
        reason="applied from handshake",
        safe=True,
    )

    applier = ConsolidationApplier(parsed.project_dir)
    result = applier.apply(
        proposal, parsed.id, registry=registry, dry_run=parsed.dry_run
    )
    if result.error:
        print(f"[rootact] apply failed: {result.error}", file=sys.stderr)
        return 1

    print(f"Applied {parsed.id}.")
    print(f"Deleted sources: {', '.join(result.deleted)}")
    print(f"Shims written: {', '.join(result.shims)}")
    print(f"Backup directory: {result.backup_dir}")
    return 0


def _consolidate_rollback(parsed: argparse.Namespace) -> int:
    """Rollback a previously applied consolidation proposal."""
    from rootact.consolidate import ConsolidationApplier

    applier = ConsolidationApplier(parsed.project_dir)
    result = applier.rollback(parsed.id)
    if result.error:
        print(f"[rootact] rollback failed: {result.error}", file=sys.stderr)
        return 1

    print(f"Rolled back {parsed.id}. Files restored from {result.backup_dir}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """RootAct CLI entry point."""
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
    if argv and argv[0] == "load-bearing":
        return _load_bearing_command(argv[1:])
    if argv and argv[0] == "novelty":
        return _novelty_command(argv[1:])
    if argv and argv[0] == "coverage":
        return _coverage_command(argv[1:])
    if argv and argv[0] == "mutation":
        return _mutation_command(argv[1:])
    if argv and argv[0] == "whisper":
        return _whisper_command(argv[1:])
    if argv and argv[0] == "auction":
        return _auction_command(argv[1:])
    if argv and argv[0] == "fence":
        return _fence_command(argv[1:])
    if argv and argv[0] == "consolidate":
        return _consolidate_command(argv[1:])
    parser = argparse.ArgumentParser(
        prog="rootact",
        description=(
            "RACT - an Agentic Coding Tool by Dr. Lucas Root, Ph.D. "
            "Forged on Windows, loved everywhere."
        ),
    )
    parser.add_argument(
        "intent",
        nargs="?",
        default="",
        help="The coding task you want RootAct to perform (not needed with --self-test).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("rootact.yaml"),
        help="Path to rootact.yaml configuration file.",
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
        "--about",
        action="store_true",
        help="Print the RACT manifesto, authorship, and license summary.",
    )
    parser.add_argument(
        "--init-provider",
        dest="init_provider",
        choices=list_presets(),
        help="Write a starter rootact.yaml for the named provider and exit.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run RootAct's internal test suite and report the result.",
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

        from rootact.harness import _default_manager_prompt_path

        config = get_preset(args.init_provider)
        target = Path("rootact.yaml")
        if target.exists():
            print(
                f"[rootact] {target} already exists; refusing to overwrite.",
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
            print(f"[rootact] wrote default prompt to {prompt_file}")

        print(f"[rootact] wrote {target} using the '{args.init_provider}' preset")
        print("[rootact] set the required environment variables and run:")
        print('  rootact "your intent here" --dry-run')
        return 0

    if args.version:
        import rootact

        print(f"RACT {rootact.__version__}")
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
        print("The Root Knot (_ROOT_KNOT = object()) is both a coder signature and a")
        print("loop invariant: if a generated file is missing the knot, the loop")
        print("stops rather than compounding unsigned work.")
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
        import rootact

        console.welcome(rootact.__version__)
        return 0

    if args.self_test:
        print("[rootact] running self-test suite")
        benchmark = SelfTestBenchmarkMode()
        test_result = benchmark.run_tests(python_executable=sys.executable)
        test_report = benchmark.report()
        print(test_report.summary)
        return 0 if test_result.returncode == 0 else 1

    if args.review_diff:
        print(f"[rootact] reviewing diff: {args.review_diff}")
        if not args.review_diff.is_file():
            print(
                f"[rootact] failed: diff file not found: {args.review_diff}",
                file=sys.stderr,
            )
            return 1
        diff_text = args.review_diff.read_text(encoding="utf-8")
        review = CodeReviewMode().review(diff_text)
        print(f"[rootact] files changed: {', '.join(review['files_changed'])}")
        print(f"[rootact] lines added: {review['lines_added']}")
        print(f"[rootact] summary: {review['summary']}")
        if review["comments"]:
            print("[rootact] comments:")
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

    result = run_rootact(
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
# RACT 0.1.0 - Initial Public Release
