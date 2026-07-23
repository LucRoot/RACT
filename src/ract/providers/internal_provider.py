import subprocess
from typing import Any

from ract.providers.base import ProviderAdapter
from ract.rooted import Rooted


class InternalProvider(ProviderAdapter):
    """Provider that routes prompts to a local command via stdin/stdout."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.command = config.get("command", [])

    @property
    def name(self) -> str:
        return "internal"

    def models(self) -> list[str]:
        return ["internal"]

    def capabilities(self) -> set[str]:
        return {"chat"}

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        if not self.command:
            return Rooted(
                value=None,
                assumption="Internal provider has a configured command.",
                confidence=0.0,
                provenance=["internal_provider"],
                error="No command configured for internal provider.",
            )
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "")
                break
        try:
            proc = subprocess.run(
                self.command,
                input=last_user.encode("utf-8"),
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Rooted(
                value=None,
                assumption="Internal command executes successfully.",
                confidence=0.0,
                provenance=["internal_provider"],
                error=f"Internal command failed: {exc}",
            )
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            return Rooted(
                value=None,
                assumption="Internal command exits with status 0.",
                confidence=0.0,
                provenance=["internal_provider"],
                error=f"Internal command exited {proc.returncode}: {stderr or stdout}",
            )
        return Rooted(
            value={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": stdout,
                        }
                    }
                ]
            },
            assumption="Internal command output is the assistant response.",
            confidence=0.9,
            provenance=["internal_provider"],
            provider="internal",
        )
