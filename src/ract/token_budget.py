from __future__ import annotations


from dataclasses import dataclass, field


@dataclass
class TokenBudget:
    """Token budget tracker and context curator for plans and steps.

    The class is deterministic and stateful. It can reserve tokens manually
    (e.g. for a system prompt or task description) and then rank candidate
    context files by relevance, returning the whole files that fit within the
    remaining budget. Files are always included whole; low-relevance files are
    dropped when the budget is exhausted.

    Example::

        from ract.token_budget import TokenBudget

        budget = TokenBudget(max_tokens=20)
        budget.reserve(5)  # hold tokens for the system prompt
        budget.add_file("high.py", "important code", relevance=1.0)
        budget.add_file("low.py", "less relevant code", relevance=0.1)
        selected = budget.select()
        omitted = budget.omitted()
    """

    max_tokens: int
    used_tokens: int = 0
    _candidates: list[tuple[str, str, float]] = field(default_factory=list, repr=False)
    _selected: list[tuple[str, str]] = field(default_factory=list, repr=False)
    _omitted: list[str] = field(default_factory=list, repr=False)
    _finalized: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.used_tokens > self.max_tokens:
            raise ValueError("Initial used_tokens cannot exceed max_tokens")

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Return a fast, deterministic token estimate.

        We use whitespace-split word count as a conservative proxy. It is
        slightly lower than true BPE token counts for code, which means we
        tend to stay safely under the real limit.
        """
        return len(text.split())

    def reserve(self, n_tokens: int) -> bool:
        """Reserve ``n_tokens`` tokens.

        Returns ``True`` if the reservation succeeds, ``False`` if it would
        exceed the budget. The internal ``used_tokens`` counter is only
        incremented on success.
        """
        if self.used_tokens + n_tokens > self.max_tokens:
            return False
        self.used_tokens += n_tokens
        return True

    def add_file(self, path: str, content: str, relevance: float) -> None:
        """Add a candidate file for context curation.

        ``relevance`` is a float; higher values are preferred. Call
        :meth:`select` to finalize the selection.
        """
        self._candidates.append((path, content, float(relevance)))
        self._finalized = False

    def select(self) -> list[tuple[str, str]]:
        """Return whole files that fit within the remaining token budget.

        Files are sorted by descending relevance. Each file is included only
        if its full token estimate fits in the remaining budget; otherwise it
        is recorded as omitted. The result is cached until the next
        ``add_file`` or ``reset`` call.
        """
        if self._finalized:
            return list(self._selected)

        self._selected = []
        self._omitted = []
        sorted_candidates = sorted(self._candidates, key=lambda c: c[2], reverse=True)
        for path, content, _relevance in sorted_candidates:
            cost = self.estimate_tokens(content)
            if self.used_tokens + cost <= self.max_tokens:
                self.used_tokens += cost
                self._selected.append((path, content))
            else:
                self._omitted.append(path)
        self._finalized = True
        return list(self._selected)

    def omitted(self) -> list[str]:
        """Return paths of candidate files that did not fit in the budget."""
        if not self._finalized:
            self.select()
        return list(self._omitted)

    def reset(self) -> None:
        """Reset the budget and clear all candidates/selections."""
        self.used_tokens = 0
        self._candidates.clear()
        self._selected.clear()
        self._omitted.clear()
        self._finalized = False

    def __bool__(self) -> bool:
        """Allow truthiness checks (e.g., ``if budget:``)."""
        return self.used_tokens < self.max_tokens


# RACT 0.1.1 - Trust and tooling
