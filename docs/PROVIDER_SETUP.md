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

## Provider presets

`ract --init-provider <preset>` writes a starter `ract.yaml`. It also writes
`prompts/manager.txt` (the default prompt) if the folder does not have one. Cloud
presets keep the key in an environment variable; the file holds only the `${NAME}`
reference.
Every preset is tested against the fake model server in this repository. No
preset has been run against a real server yet.

| Preset | Address | Key variable | How to start | Tested |
|---|---|---|---|---|
| `ollama` | `http://127.0.0.1:11434/v1` | none | start Ollama and pull a model; see Ollama's documentation | tested against the fake server |
| `local` | `http://127.0.0.1:11434/v1` | none | the same as `ollama` (the older name) | tested against the fake server |
| `llamacpp` | `http://127.0.0.1:8080/v1` | none | start `llama-server` with a model; see the llama.cpp server documentation | tested against the fake server |
| `lmstudio` | `http://127.0.0.1:1234/v1` | none | load a model in LM Studio and start its local server | tested against the fake server |
| `vllm` | `http://127.0.0.1:8000/v1` | none | start the vLLM OpenAI-compatible server with a model | tested against the fake server |
| `openai` | `https://api.openai.com/v1` | `${OPENAI_API_KEY}` | create a key with the provider and set the variable | configuration checked only |
| `anthropic` | `https://api.anthropic.com/v1` | `${ANTHROPIC_API_KEY}` | create a key with the provider and set the variable | configuration checked only |
| `zai` | `https://api.z.ai/v1` | `${ZAI_API_KEY}` | create a key with the provider and set the variable | configuration checked only |
| `moonshot` | `https://api.moonshot.cn/v1` | `${MOONSHOT_API_KEY}` | create a key with the provider and set the variable | configuration checked only |
| `openrouter` | `https://openrouter.ai/api/v1` | `${OPENROUTER_API_KEY}` | create a key with the provider and set the variable | configuration checked only |

For the local presets, the test sends a chat request to the fake server through the
provider class. For the cloud presets, the entry is "configuration checked only":
the test checks the configuration and the key pairing, and no request is sent.

The "How to start" column names the tool's own documentation. Those start
commands are not checked in this repository, so treat them as unverified.

The `llamacpp`, `lmstudio` and `vllm` presets leave `model` as a placeholder.
A llama.cpp server in router mode serves several models and needs one of them
named. Read the names with `GET /v1/models` on the server, then put one in
`model`.

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

Server errors (5xx), 408 and 429 are retried. Other 4xx errors are not, because
a retry will not fix a wrong key or a bad request. When the server sends a
`Retry-After` header, RACT waits for the time it asks for, up to 120 seconds.
A longer wait stops the retries. While RACT waits, it says so on the terminal,
for example: `the provider is rate-limiting; trying again in 8 s (attempt 2 of 4)`.
Pressing Ctrl-C ends the wait within a quarter of a second.

A streamed answer is retried only before its first piece of text reaches the
screen. After that, a dropped connection ends the answer, so no text is shown twice.

## Streaming

If the adapter advertises the `streaming` capability, RACT can stream deltas as they arrive:

```bash
ract "explain this code" --config ract.yaml --stream
```

Streaming is optional; if the adapter does not support it, RACT falls back to a non-streaming completion.

## Checking what a provider can do

`ract doctor --check-providers` sends a few small requests to each configured
provider and reports what it can do: chat, streaming, native tool calling,
reasoning text and context size. Each line is a fact from one of those
requests, or `unknown` with the reason. A gap has a next step. A server that
does not support tool calls still works: RACT uses its text fallback, which
is fine for small steps. The report never prints a key. `--json` prints the
same facts as data.

A provider whose key variable is not set is not contacted. The report names
the variable to set.

## Reasoning effort

`/set reasoning off|low|medium|high` asks a reasoning model to think less or more.
It applies to the current session only, and starts at `off` in each new session.
With `off`, no request carries the setting. A provider that has no setting for it
gets its requests unchanged, and RACT prints one line that says the setting is
ignored. Only the OpenAI endpoint is mapped so far. That mapping is unverified
against the repository documentation, so treat it as a best guess until it is
checked against a real server.

## Advice from `ract doctor`

`ract doctor` ends with an Advice section when it finds a problem. Each line
names the setting or the action to take. Plain `ract doctor` sends no request.
Only `--check-providers` does, and the live advice needs it.

- A model id with a size, such as `x-32b`, gets a memory estimate: about 0.6 GB
  per billion parameters, plus 2 GB, for 4-bit weights. The line says these
  are estimates. It uses the free memory this machine reports right now.
- A `context_budget_tokens` above the server's context size is reported with
  both numbers. Servers that do not report a size get no line.
- A server that cannot call tools gets the text fallback sentence.
- A `${VAR}` key is checked for presence only. The value is never shown.
  The line names the variable and, when it is not paired, the host.

## Token budget

`token_budget` in `ract.yaml` sets a hard limit on the tokens one run may use:
a whole number above zero, or leave it out (or set it to `null`) for no limit.

```yaml
token_budget: 200000
```

The count is the input and output tokens each provider reports for its
responses. A request that would start with the count at or over the limit is
not sent. The run stops with the message `stopped: this run used N tokens;
token_budget is M`, and exits with code 4.

- A response with no usage numbers is not counted. The run says once that the
  budget is not enforced for that provider.
- A retry counts only when its response reports usage.
- A value that is not a positive whole number (for example `0`, `-5`, `many`
  or `1.5`) is an error, and `ract doctor` names the key.

`--token-budget N` on `ract run` or `ract -p` overrides the file for that run.

## Capability-based routing

The router scores providers by how well they match a step's hint. A provider named or tagged for a hint is preferred. If no specific match exists, the first configured provider is used.

## Security notes

- Never commit API keys to version control.
- Use environment variables or a secrets manager.
- A key read from your environment, through `api_key: ${VAR}` or the
  `OPENAI_API_KEY` fallback when `api_key` is left out, is sent only to that
  key's own provider: the hosts in the presets above (`OPENAI_API_KEY` to
  `api.openai.com`, `OPENROUTER_API_KEY` to `openrouter.ai`, and so on), the
  host in your own `OPENAI_BASE_URL` for `OPENAI_API_KEY`, and the pairs you
  list in `RACT_KEY_HOSTS`, for example
  `RACT_KEY_HOSTS=OPENAI_API_KEY=gateway.example.com`. All three live outside
  the project, so a `ract.yaml` in a repository you cloned cannot send your
  key to a host of its choosing. When a key is withheld, RACT says which
  variable and which host, once per run, and never prints the value.
- RACT's safety guardrails block `eval()`, `exec()`, `subprocess...shell=True`, and bare `except:` in generated content.

<!-- RACT 0.1.1 - Trust and tooling -->
