"""Production signing: the harness signs what it writes (S-015b, L-018 recommendation 2).

LR:: Before this, the harness built no manifest, loaded no keys and never
called ``Executor.install_v4_provenance_deps``, so every artifact was
"unsigned". ``install`` now does that at run entry:

- the session key is ``SessionKey.load_or_create`` under the user state
  directory (``<state>/keys/<id>.pem``), where ``ract provenance verify``
  resolves a knot's generator key by id;
- the sandbox and ALM verifier keys are per run, in the state folder of
  this repository (B-111, ADR-0048 R3), never inside the project;
- the workspace snapshot is the project's tracked text at run entry, the
  acceptance suite is compiled from the run's intent against it, and the
  manifest is the default ``CapabilityManifest`` for the run, bound to the
  sandbox key's id.

Every knot is v4 (D-012: no interim v1 or v3). When anything above cannot
be built, nothing is signed and the reason is returned and printed: the
artifact stays honestly "unsigned". The run keys are archived at once (the
file moves to ``archive/``, where verification resolves it; the key stays in
memory for this run's signatures), so a run that is killed leaves no live
key file behind. Command records are not part of a knot: they bind into the
trace chain (ADR-0048 D10).
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

# The snapshot reads at most this much of the project at run entry.
_MAX_FILES = 2000
_MAX_FILE_BYTES = 256 * 1024
# G-226 note 3: at most this much text is read in all; past it a file is
# recorded by its hash only, as a large file is.
_MAX_TOTAL_BYTES = 32 * 1024 * 1024


def _tracked_text(project: Path) -> dict[str, str]:
    """The project's tracked text files at run entry (the attested workspace)."""
    try:
        done = subprocess.run(
            # core.fsmonitor=false: a repository's config cannot start a program.
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=",
                "--no-optional-locks",
                "ls-files",
                "-z",
            ],
            cwd=project,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[provenance] the tracked files were not listed: {exc}", flush=True)
        return {}
    if done.returncode != 0:
        return {}
    files: dict[str, str] = {}
    total = 0
    for raw in done.stdout.split(b"\0")[:_MAX_FILES]:
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="replace")
        if rel.startswith(".ract/"):
            continue
        path = project / rel
        try:
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()[: _MAX_FILE_BYTES + 1]
        except OSError as exc:
            print(f"[provenance] {rel} was not read: {exc}", flush=True)
            continue
        if (
            len(data) > _MAX_FILE_BYTES
            or b"\0" in data
            or total + len(data) > _MAX_TOTAL_BYTES
        ):
            files[rel] = "sha256:" + hashlib.sha256(data).hexdigest()
            continue
        total += len(data)
        files[rel] = data.decode("utf-8", errors="replace")
    return files


def run_seed(run_id: str) -> bytes:
    """The 16-byte id the run's keys are filed under."""
    return hashlib.sha256(run_id.encode("utf-8")).digest()[:16]


def install(
    executor: Any, project: Path | str, intent: str, *, run_id: str
) -> str | None:
    """Wire v4 signing into *executor*; None when it is wired, else why it is not."""
    project = Path(project)
    try:
        from ract.core.compile import IntentCompiler
        from ract.core.keys import SessionKey
        from ract.core.loop import WorkspaceSnapshot
        from ract.core.provenance import ProvenanceIndex
        from ract.core.types import digest_bytes
        from ract.security.alm_verifier_key import AlmVerifierKey
        from ract.security.keys import SandboxKey
        from ract.security.manifest import CapabilityManifest, ManifestDigest

        seed = run_seed(run_id)
        session_key = SessionKey.load_or_create(seed)
        # A second turn under the same run id reuses the run's archived keys:
        # generating again would replace them and orphan earlier knots.
        sandbox = SandboxKey.load_archived(seed, project)
        if sandbox is None:
            sandbox = SandboxKey.generate(seed, project)
            sandbox.archive(project)
        alm = AlmVerifierKey.load_archived(seed, project)
        if alm is None:
            alm = AlmVerifierKey.generate(seed, project)
            alm.archive(project)
        snapshot = WorkspaceSnapshot(files=_tracked_text(project), timestamp=0.0)
        compiled = IntentCompiler().compile(intent, snapshot)
        suite = getattr(compiled, "visible", compiled)
        if getattr(suite, "prompt_digest", None) is None:
            raise ValueError("the compiled acceptance suite has no prompt digest")
        manifest = CapabilityManifest(
            run_id=run_id,
            sandbox_key_id=bytes(digest_bytes(sandbox.public)).hex(),
        )
        manifest_digest = ManifestDigest.of(manifest)
    except Exception as exc:  # noqa: BLE001 - signing that cannot be built signs nothing
        why = f"{type(exc).__name__}: {exc}"
        print(f"[provenance] signing is off for this run: {why}", flush=True)
        return why
    executor.provenance_index = ProvenanceIndex(project)
    executor.session_key = session_key
    executor.install_v4_provenance_deps(
        session_key=session_key,
        sandbox_signer=sandbox,
        alm_signer=alm,
        workspace_snapshot_provider=lambda: snapshot,
        prompt_digest_provider=lambda: suite.prompt_digest,
        acceptance_suite_provider=lambda: suite,
        manifest_digest_provider=lambda: manifest_digest,
    )
    return None


__all__ = ["install", "run_seed"]
