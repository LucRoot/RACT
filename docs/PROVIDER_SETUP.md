# Rooted by Dr. Lucas Root, Ph.D.

# RootAct Provider Setup Guide

RootAct routes each plan step to a provider adapter. You can use local models, remote APIs, or multiple providers side by side.

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

Configure RootAct:

```yaml
manager_provider: local

providers:
  local:
    adapter: local_http
    url: http://127.0.0.1:8011/v1
    model: my-local-model
```

The `model` value is passed to the server but may be ignored by local servers.

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

RootAct expands `${...}` placeholders from the environment at runtime. Keep secrets out of the config file by using environment variables.

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

In a plan, a step can specify `provider_hint: coder`. RootAct's router selects the best matching provider.

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

If the adapter advertises the `streaming` capability, RootAct can stream deltas as they arrive:

```bash
rootact "explain this code" --config rootact.yaml --stream
```

Streaming is optional; if the adapter does not support it, RootAct falls back to a non-streaming completion.

## Capability-based routing

The router scores providers by how well they match a step's hint. A provider named or tagged for a hint is preferred. If no specific match exists, the first configured provider is used.

## Security notes

- Never commit API keys to version control.
- Use environment variables or a secrets manager.
- RootAct's safety guardrails block `eval()`, `exec()`, `subprocess...shell=True`, and bare `except:` in generated content.

<!-- RACT 0.1.1 - Trust and tooling -->
