"""RACT environment variable registry (v0.7 WP9, V7-02).

Every RACT_* name that RACT reads, with its class, default, consumer and the
user-facing document that names it. A test (tests/test_env_registry.py) walks
src/ract and fails on any read of a RACT_* name that is not in ENV_VARS.
``ract doctor --env`` lists the variables set in the environment, names only;
a secret-ref variable is shown as set or unset and never by value.

Classes: path (a location), secret-ref (names a secret, never shown),
diagnostic (aids a diagnosis), behavior (changes a behavior), security (a
control; the target rule is that it may only tighten, which is not yet
enforced for these entries: V7-02 records, it does not change behavior).

``documented`` is either the path of a user-facing document (README.md or a
top-level docs/*.md file that contains the name), or a note such as "none" or
"CHANGELOG only" when no user-facing document names the variable. The test
checks both directions.
"""

from __future__ import annotations

from dataclasses import dataclass

CLASSES = ("path", "secret-ref", "diagnostic", "behavior", "security")


@dataclass(frozen=True)
class EnvVar:
    name: str
    cls: str
    default: str
    consumer: str
    documented: str


ENV_VARS: tuple[EnvVar, ...] = (
    EnvVar(
        "RACT_EGRESS_LEDGER",
        "path",
        "<state>/egress.jsonl",
        "ract.egress_ledger: where the egress ledger is written",
        "docs/EGRESS.md",
    ),
    EnvVar(
        "RACT_HANDSHAKE_QUEUE",
        "path",
        "handshake_queue.jsonl",
        "ract.handshake: the approval queue file",
        "none",
    ),
    EnvVar(
        "RACT_EMBED_MODEL_ROOT",
        "path",
        "unset (no local model root)",
        "ract.memory.embedding: parent directory of a local embedding model",
        "README.md",
    ),
    EnvVar(
        "RACT_BASE_URL",
        "behavior",
        "unset",
        "ract.setup.local_probe: endpoint address probed by setup (with OPENAI_BASE_URL)",
        "CHANGELOG only",
    ),
    EnvVar(
        "RACT_OPERATOR_KEY",
        "secret-ref",
        "unset",
        "ract.core.intent_recompile: the operator's signing key for intent recompile",
        "README.md",
    ),
    EnvVar(
        "RACT_KEY_HOSTS",
        "security",
        "unset (keys go to their own default host)",
        "ract.trust and ract.providers.openai_provider: which host each env key may reach",
        "docs/PROVIDER_SETUP.md",
    ),
    EnvVar(
        "RACT_EMBED_ONLINE",
        "security",
        "unset (no model download)",
        "ract.memory.embedding: '1' allows an embedding model download",
        "README.md",
    ),
    EnvVar(
        "RACT_STDIN_IDLE_TIMEOUT",
        "behavior",
        "30 seconds",
        "ract.headless: idle timeout for piped input (B-093)",
        "docs/EVENTS_SESSION.md",
    ),
    EnvVar(
        "RACT_TYPE_AHEAD",
        "behavior",
        "on",
        "ract.repl: '1' turns type-ahead off",
        "review notes only",
    ),
    EnvVar(
        "RACT_WSL_DISTRO",
        "behavior",
        "the default WSL distribution",
        "ract.mutation_runner: which WSL distribution runs the mutation tool",
        "none",
    ),
    EnvVar(
        "RACT_LANCEDB_BACKEND",
        "behavior",
        "auto",
        "ract.memory.cpu_fallback: forces the vector backend",
        "docs/ARCHITECTURE.md",
    ),
    EnvVar(
        "RACT_RUN_ID",
        "diagnostic",
        "unset (a new id per run)",
        "ract.runtime: the run id, passed to child processes; the sandbox keeps it",
        "README.md",
    ),
    EnvVar(
        "RACT_MUTATION_TARGETS",
        "behavior",
        "unset",
        "ract.mutation_runner: written for the mutation script (not read by RACT)",
        "none",
    ),
    EnvVar(
        "RACT_TEST_RUNNER",
        "behavior",
        "unset",
        "ract.mutation_runner: written for the mutation script (not read by RACT)",
        "none",
    ),
)

BY_NAME: dict[str, EnvVar] = {v.name: v for v in ENV_VARS}
