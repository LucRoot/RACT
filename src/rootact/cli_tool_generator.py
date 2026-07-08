from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import re
from dataclasses import dataclass, field
from typing import Any

_ROOT_KNOT = object()


@dataclass
class CliToolSpec:
    """Parsed specification for a small CLI tool."""

    name: str
    description: str
    positional: list[tuple[str, str]] = field(default_factory=list)  # (arg_name, help)
    flags: list[tuple[str, str, Any]] = field(
        default_factory=list
    )  # (dest, help, default)


class CliToolGenerator:
    """
    Generate a small, self-contained Python CLI script from a natural-language
    description.

    The generator extracts a tool name, a one-line description, positional
    arguments, and boolean/value flags. It then emits a script that uses the
    standard-library ``argparse`` module and a ``main`` entry point.

    This is intentionally simple: it demonstrates RootAct turning intent into
    runnable, testable tooling without external dependencies.
    """

    _ROOT_KNOT = _ROOT_KNOT

    # Sentence fragments that suggest a boolean flag.

    def generate(self, description: str) -> dict[str, Any]:
        """Parse ``description`` and return a generated CLI script."""
        spec = self._parse(description)
        script = self._render(spec)
        return {
            "name": spec.name,
            "description": spec.description,
            "script": script,
            "entrypoint": "main",
            "positional": [p[0] for p in spec.positional],
            "flags": [f[0] for f in spec.flags],
        }

    def _parse(self, description: str) -> CliToolSpec:
        """Extract a CliToolSpec from free-form text."""
        # Normalize whitespace and trailing punctuation.
        text = " ".join(description.split())
        if not text:
            return CliToolSpec(name="cli_tool", description="Generated CLI tool.")

        # First sentence is the description; remaining sentences may mention args.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        headline = sentences[0] if sentences else text

        # Prefer an explicit "named <name>" or quoted tool name.
        named_match = re.search(r"\bnamed\s+([a-zA-Z][a-zA-Z0-9_-]*)", text)
        quoted_match = re.search(r'["\']([a-zA-Z][a-zA-Z0-9_-]*)["\']', text)
        if named_match:
            name = named_match.group(1).lower().replace("-", "_")
        elif quoted_match:
            name = quoted_match.group(1).lower().replace("-", "_")
        else:
            # Derive a snake_case tool name from the first few words.
            first_words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", headline)[:4]
            name = (
                "_".join(w.lower() for w in first_words) if first_words else "cli_tool"
            )
            name = re.sub(r"_+", "_", name).strip("_") or "cli_tool"

        positional: list[tuple[str, str]] = []
        flags: list[tuple[str, str, Any]] = []

        # Look for "takes <arg>" or "accepts <arg>" patterns.
        for match in re.finditer(
            r"(?:takes?|accepts?|requires?)\s+(?:an?\s+)?(?:<([^>]+)>|([a-z][a-z0-9_]*))",
            text,
        ):
            arg_name = match.group(1) or match.group(2)
            if arg_name and arg_name.lower() not in {"input", "output"}:
                arg_name = arg_name.lower().replace("-", "_")
                if arg_name not in {p[0] for p in positional}:
                    positional.append((arg_name, f"The {arg_name} argument."))

        # Add default input/output positional args if the description mentions them.
        if re.search(r"\binput\b", text, re.IGNORECASE) and "input" not in {
            p[0] for p in positional
        }:
            positional.append(("input", "Input file or value."))
        if re.search(r"\boutput\b", text, re.IGNORECASE) and "output" not in {
            p[0] for p in positional
        }:
            positional.append(("output", "Output file or value."))

        # Detect simple boolean flags by keyword.
        flag_keywords = {
            "verbose": ("verbose", "Enable verbose output.", False),
            "debug": ("debug", "Enable debug output.", False),
            "force": ("force", "Force the operation.", False),
            "dry-run": ("dry_run", "Perform a dry run.", False),
            "dryrun": ("dry_run", "Perform a dry run.", False),
            "show": ("show", "Show additional details.", False),
        }
        for keyword, flag_spec in flag_keywords.items():
            if re.search(rf"\b{keyword}\b", text, re.IGNORECASE):
                if flag_spec[0] not in {f[0] for f in flags}:
                    flags.append(flag_spec)

        return CliToolSpec(
            name=name,
            description=headline,
            positional=positional,
            flags=flags,
        )

    def _render(self, spec: CliToolSpec) -> str:
        """Render a CliToolSpec as a Python script string."""
        lines: list[str] = [
            "from __future__ import annotations",
            "",
            "import argparse",
            "",
            "",
            "def main(argv: list[str] | None = None) -> int:",
            f"    parser = argparse.ArgumentParser(description={spec.description!r})",
        ]
        for flag_dest, flag_help, flag_default in spec.flags:
            flag_name = flag_dest.replace("_", "-")
            lines.append(
                f'    parser.add_argument("--{flag_name}", "-{flag_name[0]}", '
                f'action="store_true", dest="{flag_dest}", '
                f"default={flag_default!r}, help={flag_help!r})"
            )
        for arg_name, arg_help in spec.positional:
            lines.append(f'    parser.add_argument("{arg_name}", help={arg_help!r})')
        lines.extend(
            [
                "    args = parser.parse_args(argv)",
                '    print(f"Running {args!r}")',
                "    return 0",
                "",
                "",
                'if __name__ == "__main__":',
                "    raise SystemExit(main())",
            ]
        )
        return "\n".join(lines) + "\n"
