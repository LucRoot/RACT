# Rooted by Dr. Lucas Root, Ph.D.

# RACT Provider Setup Guide

RACT routes each plan step to a provider adapter. You can use local models, remote APIs, or multiple providers side by side.

## Supported adapters

| Adapter | Use case | Configuration keys |
|---------|----------|--------------------|
| `local_http` | Local servers such as llama-server, ollama, lmstudio | `url`, `model` |
| `openai` | OpenAI-compatible cloud APIs | `url`, `api_key`, `model` |

## Local model via llama-server

Start the server:

```bash
llama-server -m /path/to/model.gguf --port 8011 --host 127.0.0.1 -c 32768
```

Configure RACT:

```yaml
manager_provider: local

providers:
  local:
    adapter: local_http
    url: http://127.0.0.1:8011/v1
    model: my-local-model
```

The `model` value is passed to the server but may be ignored by local servers.

### Where the keys go

`manager_provider`, `providers`, `prompts_dir` and `context_budget_tokens` are
top-level keys. The `project:` block holds only `name`. If you indent
`manager_provider` or `providers` under `project:`, RACT does not read them.
`ract config validate` and `ract doctor` report this, along with these other
mistakes:

- `prompt_file:` is not a RACT setting. RACT reads the manager prompt from
  `<prompts_dir>/manager.txt` (default `prompts/manager.txt`) and falls back to
  the bundled prompt.
- A provider slot uses `adapter:`, not `type:`.
- The output cap is `max_tokens:`, not `max_output_tokens:`.

If `manager_provider` is not set, RACT uses a provider named `local`, or the
only provider you defined. With several providers and no `local`, it stops and
tells you to set `manager_provider`.

### Output limit and reasoning models

`max_tokens` is a per-provider setting:

```yaml
providers:
  bolt:
    adapter: local_http
    url: http://127.0.0.1:8080/v1
    model: my-reasoning-model
    max_tokens: 8192   # an integer, or "none" to send no limit
    timeout: 900       # seconds; local_http defaults to 600
```

For `local_http`, RACT sends no output limit unless you set one, so the server's
own limit (`n-predict`, context size) applies. Hosted `openai` providers keep
the per-call default unless you set `max_tokens`.

Reasoning models write their thinking first, then the
answer. If the limit is reached during thinking, the response has no answer and
`finish_reason` is `length`. RACT now says so, with the size of the reasoning it
received, instead of reporting a JSON parse error. Raise `max_tokens` or remove
it. RACT also strips `<think>...</think>` blocks from answers, and it refuses to
write an empty answer over an existing file.

### Ollama

```yaml
providers:
  ollama:
    adapter: local_http
    url: http://127.0.0.1:11434/v1
    model: llama3.1
```

### Local model behind an inference proxy

If you run a local inference proxy that routes to a model on port 11434:

```yaml
providers:
  local_proxy:
    adapter: local_http
    url: http://127.0.0.1:11434/v1
    model: my-local-model
```

### KoboldCpp and llama.cpp

Any OpenAI-compatible local endpoint works with the `local_http` adapter. For example, a KoboldCpp or llama.cpp server instance on port `11435`:

```yaml
providers:
  local_llm:
    adapter: local_http
    url: http://127.0.0.1:11435/v1
    model: my-local-model
```

The `model` string is forwarded to the server. Some local servers ignore it and serve whichever model is currently loaded; others use it for routing. Match it to the loaded model name when possible.

## OpenAI API

```yaml
providers:
  openai:
    adapter: openai
    url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o-mini
```

## Cheap frontier providers

### Z.ai

```yaml
providers:
  zai:
    adapter: openai
    url: https://api.z.ai/v1
    api_key: ${ZAI_API_KEY}
    model: your-zai-model
```

### Moonshot AI

```yaml
providers:
  moonshot:
    adapter: openai
    url: https://api.moonshot.cn/v1
    api_key: ${MOONSHOT_API_KEY}
    model: moonshot-v1-8k
```

### OpenRouter

```yaml
providers:
  openrouter:
    adapter: openai
    url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: openai/gpt-4o-mini
```

RACT expands `${...}` placeholders from the environment at runtime. Keep secrets out of the config file by using environment variables.

## Multiple providers

You can define more than one provider. The manager uses `manager_provider` to choose which model plans the work. Each step can then request a provider by hint:

```yaml
manager_provider: planner

providers:
  planner:
    adapter: openai
    url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o
  coder:
    adapter: openai
    url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o-mini
```

In a plan, a step can specify `provider_hint: coder`. RACT's router selects the best matching provider.

## Retry and timeout behavior

Providers support configurable retries:

```yaml
providers:
  openai:
    adapter: openai
    url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    model: gpt-4o-mini
    max_retries: 3
    retry_delay: 1.0
    retry_backoff: 2.0
    retry_max_delay: 30.0
    retry_on_429: true
```

- `max_retries`: how many times to retry a failed request.
- `retry_delay`: initial delay in seconds.
- `retry_backoff`: multiplier applied after each retry.
- `retry_max_delay`: cap on the delay between retries.
- `retry_on_429`: whether to retry HTTP 429 rate-limit responses.

## Streaming

If the adapter advertises the `streaming` capability, RACT can stream deltas as they arrive:

```bash
ract "explain this code" --config ract.yaml --stream
```

Streaming is optional; if the adapter does not support it, RACT falls back to a non-streaming completion.

## Capability-based routing

The router scores providers by how well they match a step's hint. A provider named or tagged for a hint is preferred. If no specific match exists, the first configured provider is used.

## Security notes

- Never commit API keys to version control.
- Use environment variables or a secrets manager.
- RACT's safety guardrails block `eval()`, `exec()`, `subprocess...shell=True`, and bare `except:` in generated content.

<!-- RACT 0.1.1 - Trust and tooling -->
