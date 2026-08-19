"""Canned-response provider for function-contract tests.

Lateral Chain branch B (module_06 PRE): every function test needs a
provider stub. This module lands one:

- :class:`MockProvider` — records every invocation, returns responses
  by function name (from the assembled prompt's system section) or
  by prompt-hash key.

The provider satisfies the
:class:`~ract.memory.functions.provider_adapter.MemoryFunctionProvider`
protocol so no adapter wrapping is required at call sites.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MockProvider:
    """Canned-response ``MemoryFunctionProvider`` for tests.

    ``responses_by_function`` — map from function name (matched against
    the assembled prompt's system-section header text) to a canned
    response string.

    ``responses_by_prompt_hash`` — map from the SHA-256 of the exact
    assembled prompt to a response. Wins over the function-name
    match when present.

    ``fallback`` — string returned when no key matches. Defaults to
    an empty JSON object (``"{}"``) so the caller's contract parser
    surfaces the missing-fields error rather than a crash.

    ``call_log`` — list of ``(function_name, prompt_hash)`` tuples
    recorded in call order.
    """

    responses_by_function: dict[str, str] = field(default_factory=dict)
    responses_by_prompt_hash: dict[str, str] = field(default_factory=dict)
    fallback: str = "{}"
    call_log: list[tuple[str, str]] = field(default_factory=list)

    def send(self, prompt: str, declaration: Any) -> str:
        """Return the canned response for ``prompt``.

        The lookup order:

        1. ``responses_by_prompt_hash[sha256(prompt)]`` — exact match.
        2. ``responses_by_function[declaration.function]`` — by
           function.
        3. ``fallback``.
        """
        prompt_hash = hashlib.sha256(
            prompt.encode("utf-8", errors="replace")
        ).hexdigest()
        function = getattr(declaration, "function", "")
        self.call_log.append((function, prompt_hash))
        if prompt_hash in self.responses_by_prompt_hash:
            return self.responses_by_prompt_hash[prompt_hash]
        if function in self.responses_by_function:
            return self.responses_by_function[function]
        return self.fallback


__all__ = ["MockProvider"]


from ract.core.module_identity import _module_knot, register_module_knot  # noqa: E402

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
