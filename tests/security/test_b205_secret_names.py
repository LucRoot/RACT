"""B-205: one list of secret-shaped file names, and every consumer agrees with it.

The lists disagreed (reader run): ``.env.dist`` was exempt in
``workspace_path`` and blocked by git_tools; ``.env.EXAMPLE`` and
``.env.local.example`` were secret to ``workspace_path`` and staged by
git_tools; ``id_ecdsa`` and ``id_dsa`` were blocked by git_tools and shown to
the model and copied into step snapshots. The rule now, written once: an env
file is secret unless its last suffix is example, sample, template or dist
(any case); every OpenSSH private key name, key stores and token files are
secret. The table runs both directions against every consumer.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract.core.threat_model import _matches_sensitive
from ract.executor.worktree import _SNAPSHOT_EXCLUDES
from ract.tools.git_tools import blocked_name
from ract.workspace_path import is_never_sent, is_secret_shaped, resolve_workspace_path

SECRET = [
    ".env",
    ".ENV",
    ".env.local",
    ".env.production",
    ".Env.Staging",
    "sub/.env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "ID_ECDSA",
    "id_ed25519",
    "id_ecdsa_sk",
    "id_ed25519_sk",
    "server.pem",
    "TLS.PEM",
    "private.key",
    "store.p12",
    "cert.pfx",
    "app.jks",
    "release.keystore",
    "putty.ppk",
    "vault.kdbx",
    ".netrc",
    ".pypirc",
    ".git-credentials",
]
NOT_SECRET = [
    ".env.example",
    ".env.EXAMPLE",
    ".env.local.example",
    ".env.sample",
    ".env.template",
    ".env.dist",
    ".env.DIST",
    "id_rsa.pub",
    "id_utils.py",
    "env.py",
    ".envrc.md",
    "keys.md",
    "README.md",
    "src/app.py",
    "monkey.py",
]


def test_the_table_has_forty_names() -> None:
    assert len(SECRET) + len(NOT_SECRET) == 40


@pytest.mark.parametrize("name", SECRET)
def test_a_secret_name_is_secret_to_every_consumer(name: str, tmp_path: Path) -> None:
    assert is_secret_shaped(name)
    assert is_never_sent(name)  # the read tool and every send
    assert blocked_name(name) is not None  # git staging
    assert _matches_sensitive(name)  # the threat model's read check
    assert not resolve_workspace_path(tmp_path, name, purpose="write").is_ok()


@pytest.mark.parametrize("name", NOT_SECRET)
def test_a_plain_name_is_plain_to_every_consumer(name: str, tmp_path: Path) -> None:
    assert not is_secret_shaped(name)
    assert not is_never_sent(name)
    assert blocked_name(name) is None
    assert not _matches_sensitive(name)


def test_the_step_snapshot_leaves_out_exactly_the_secret_names(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env
        )

    assert git("init", "-q").returncode == 0
    names = [n for n in SECRET + NOT_SECRET if n.casefold() not in {".env", ".pem"}]
    # Windows folds case: one file per folded name.
    unique = {n.casefold(): n for n in names}
    for name in unique.values():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("x\n", encoding="utf-8")
    (repo / ".env").write_text("x\n", encoding="utf-8")
    assert git("add", "-A", "--force").returncode == 0
    removed = git("rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", *_SNAPSHOT_EXCLUDES)
    assert removed.returncode == 0, removed.stderr
    kept = set(git("ls-files").stdout.split())
    expected = {n for n in unique.values() if not is_secret_shaped(n)}
    assert kept == expected
