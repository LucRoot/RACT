# Rooted by Dr. Lucas Root, Ph.D.

# RootAct Harness

The harness is the runtime container. It loads configuration, instantiates the provider router, management LM, planner, executor, and support modules, and exposes a single `run(intent)` method.

## Configuration

`rootact.yaml`:

```yaml
project:
  name: my-project

manager_provider: local

providers:
  local:
    adapter: local_http
    url: http://127.0.0.1:11434/v1
    model: nemotron
  openai:
    adapter: openai
    url: https://api.openai.com/v1
    model: gpt-4o-mini
    api_key: ${OPENAI_API_KEY}

prompts_dir: prompts
```

The `project.name` field is required. `PreflightValidator` checks for it before the harness starts.

## Lifecycle

1. `PreflightValidator(config_path).is_valid()` confirms the config exists and contains required fields.
2. `Harness.from_config_path(path)` loads YAML, instantiates the router, and returns a `Rooted[Harness]`.
3. `Harness.run(intent)` plans and executes in one call.
4. Before execution, the plan is validated structurally by `PlanValidator` and checked for dependency cycles by `DependencyGraph`.
5. `Executor` runs each step through the provider `Router`, applies `SafetyGuardrail` checks, and records provenance and artifacts.
6. Every step returns a `Rooted` result; failures short-circuit with a clear assumption.
7. Callers can wrap `Harness.run` with `HarnessReportEnricher.enrich_harness_run` to attach a diff summary and file-level diff to successful reports.

## Local Provider Note

Local servers often reject an `Authorization` header even when the key is empty. Use `adapter: local_http` for llama-server, vLLM, or any local OpenAI-compatible proxy. These slots force `api_key` to `no-key` and omit the auth header on every request.

## Error Handling

Every harness operation returns a `Rooted` result. Common failure modes:

- Missing or unreadable `rootact.yaml` → init failure.
- Missing `project.name` → preflight failure.
- Unconfigured `manager_provider` slot → init failure.
- Missing `prompts/manager.txt` → init failure.
- Provider timeout or HTTP error → execution failure with the violated assumption.
- Model returns non-JSON or low-confidence plan → planning failure.
- Forbidden pattern detected by `SafetyGuardrail` → execution blocked before files are written.

## Context Curation

`TokenBudget` ranks candidate context files by relevance and includes whole files only while staying under a configurable token budget. The harness can reserve tokens for the system prompt and task description before selecting context files.

## User Customization

- Replace `prompts/manager.txt` to change management LM behavior.
- Add provider adapters via `register_adapter(name, AdapterClass)`.
- Register skills in `.rootact/skills/` via `SkillRegistry`.
- Register author signatures in `.rootact/signatures/` via `SignatureRegistry`.
- Register pre/post-step hooks via `HookManager`.
- Wrap `Harness` in a UI, scheduler, or CI step.

## Status

The harness is the primary integration surface and is covered by end-to-end CLI and unit tests. See `docs/ARCHITECTURE.md` for the full module map and `docs/AUDIT.md` for the latest verification numbers.
