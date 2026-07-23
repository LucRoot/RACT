# RACT Security Best Practices Guide

Guidelines for running RACT safely in production and shared environments.

## Keeping provider keys out of the repo

**Recommendation:** Store API keys and endpoint credentials in environment variables or a secrets manager, never in `rootact.yaml` or source files.  
**Example:** Use `${OPENAI_API_KEY}` in `rootact.yaml` and set the variable in your shell:

```bash
export OPENAI_API_KEY="sk-..."
ract --config rootact.yaml "add tests"
```

## Reviewing load-bearing annotations

**Recommendation:** Treat `# load-bearing:` annotations as explicit "do not touch" markers. Review them before every plan that touches legacy code.  
**Example:** List annotations before a refactor:

```bash
ract load-bearing list
```

## Validating receipts and chains

**Recommendation:** Sign and verify run receipts so you can audit what RACT changed and when. Verify receipt chains before accepting a deployed artifact.  
**Example:** Verify a single receipt and a chain:

```bash
ract receipt verify receipt.json --pubkey signer.pem --json
ract receipt chain-verify chain.jsonl
```

## Controlling novelty budgets

**Recommendation:** Set a novelty budget in `rootact.yaml` to prevent RACT from introducing too much unfamiliar code in a single run.  
**Example:** Configure a 15% novelty threshold:

```yaml
project:
  name: my-project
novelty:
  budget: 0.15
```

## Least-privilege model servers

**Recommendation:** Run local model servers on `127.0.0.1` only and bind them to ports that are not exposed to the network. Disable any remote-admin endpoints.
