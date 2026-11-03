# Readability report (B-168)

Grade is Flesch-Kincaid, target about 6; above 8.0 is a failure to card.

| grade | string |
| --- | --- |
| 5.7 | Suggested model: x (about x GB): x. |
| -3.4 | x |
| 4.8 | Start it with one of these (setup does not download anything): |
| 1.7 | The guidance was last checked x. The sizes are rough. |
| 2.9 | address: x |
| 1.3 | key variable: x |
| 8.4 | Machine: |
| 7.6 | network: not tested. Setup talks only to this machine's usual server addresses and to the provider you pick. |
| 2.5 | Wrote x and prompts/manager.txt. |
| 2.5 | Adds the provider 'x' to x: |
| 5.7 | Wrote x; the manager provider stays 'x'. |
| 4.5 | Checking x with one tiny request: |
| 2.9 | failed: x |
| -3.0 | hint: x |
| 14.7 | nothing answered |
| 1.6 | x is not an address (it starts with http:// or https://) |
| 5.1 | that address has a key in it. Setup saves addresses only. Type it again without the key, and keep the key in an environment variable. |
| 4.0 | that address has a user name or password in it. Type it without them. Put any key in an environment variable. |
| 6.6 | nothing answered at x |
| 1.3 | this machine has x GB, x GB free right now |
| 5.8 | only x GB is free right now; close other programs before loading it |
| -3.4 | x |
| 8.8 | Cloud providers: |
| -3.4 | x |
| 2.5 | key variable: none (no key needed) |
| 1.6 | x is set; ract.yaml will refer to it as ${x}. |
| 2.3 | x is not set. ract.yaml will refer to it as ${x}; set it in your shell before running RACT. Setup never reads or stores the key. |
| -3.4 | x |
| 6.9 | Looking for a model server on this machine (default ports only): |
| 5.2 | Wrote x. Differences from x: |
| 4.0 | Review it, then replace x with it to use it, or delete it. |
| 0.5 | Skipped the health check (check: false). |
| 5.8 | This directory is not a git repository. RACT records each step on its own branch, so it works best in one. Command: git init |
| 5.2 | Opening the session. Try: x |
| 5.2 | Next: run `ract` to open a session here, or try: ract -p --ask "what does this project do?" |
| 3.7 | x is rewritten whole, so comments in it are not kept. |
| 5.2 | Nothing was changed. |
| 0.5 | Skipped the health check (check: false). |
| 6.9 | Skipped the health check: the key variable is not set yet. Then run: ract doctor --check-providers |
| -1.8 | ok: x in x s |
| 7.4 | Both are listed by: ract doctor --check-providers |
| 2.9 | x answers (x); models: x |
| 5.4 | x answers (x) but lists no model yet; load one in it, then run setup again |
| 3.7 | It reports x models: |
| -3.4 | x |
| 4.2 | No server chosen. Use a local model or a cloud provider? [L/c] |
| 3.2 | error: x. Nothing was sent and nothing was written. |
| 7.6 | setup stopped; nothing was written. |
| 6.0 | Setup needs an answer, but the input ended. Nothing was written. hint: ract setup --answers FILE, or ract setup --yolo |
| 2.9 | error: x |
| 6.9 | Skipped the health check: the key variable is not set yet. Then run: ract doctor --check-providers |
| 4.5 | Checking x with one tiny request: |
| 1.3 | ran: git init |
| 0.6 | Use the server at x? [Y/n] |
| 6.8 | Start the server, then press Enter to look again. Or type skip for Ollama's address: |
| -1.8 | ok: x in x s |
| 2.9 | failed: x |
| -3.0 | hint: x |
| -1.4 | Write it to x? [y/N] |
| -3.0 | Which one? [1] |
| 0.6 | Run git init here now? [y/N] |
| -3.0 | Which one? [1] |
| 6.8 | Still nothing to use; no config written. Run ract setup again once the server is up, or type skip at that question to write a config for Ollama's default address. |
| -3.0 | ract.yaml |
| -2.6 | ract.yaml.draft |
| 6.4 | # Answers for `ract setup --answers FILE`. Every field is optional. |
| 7.6 | provider: local          # local or cloud |
| 8.4 | local: |
| 4.0 | url: null              # null: use the first server that answers on a default port |
| 5.0 | model: null            # null: the first model the server reports |
| -3.4 | cloud: |
| 5.2 | preset: openai         # one of: {cloud} |
| 5.7 | model: null            # null: the preset's default model |
| 6.0 | check: true              # run one tiny completion with the written config |
| 9.4 | git_init: false          # run `git init` when this directory is not a repository |
| 5.8 | reconfigure: false       # write ract.yaml.draft next to an existing ract.yaml |
| 5.8 | Address of your model server (for example http://127.0.0.1:8080/v1), or Enter to skip: |
