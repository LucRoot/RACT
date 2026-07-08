# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""AST-based detector for error-masking patterns.

The GitClear + GitKraken finding shows AI-generated code is increasingly
introducing silent error handling. This detector hunts those patterns and
requires explicit accountability comments before any instance is permitted.

Permitted annotations must be machine-parseable:

    # error-mask-permitted: cause=<reason> recovery=<strategy>

If the comment is missing or malformed, the pattern is reported as a violation.
"""

import ast
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorMaskMatch:
    """A single detected error-masking pattern."""

    line: int
    pattern: str
    message: str
    permitted: bool = False


class ErrorMaskDetector(ast.NodeVisitor):
    """Detect error-masking patterns in Python source.

    LR:: Error masking is the fastest-growing rot vector in AI-generated code.
    RACT rejects masked errors unless the author has written a required
    accountability comment explaining why the mask is safe and how recovery
    happens. This makes the cheap path (silence the error) more expensive than
    the honest path (handle or escalate it).
    """

    _PERMITTED_RE = re.compile(
        r"error-mask-permitted:\s*"
        r"cause\s*=\s*(?P<cause>[^\n]+?)"
        r"(?:\s+recovery\s*=\s*(?P<recovery>[^\n]+))?"
        r"\s*$",
        re.IGNORECASE,
    )

    # Broad exception types that should almost never be suppressed.
    _BROAD_EXCEPTIONS: frozenset[str] = frozenset(
        {"Exception", "BaseException", "RuntimeError"}
    )

    def __init__(self, source: str) -> None:
        self.source = source
        self.lines = source.splitlines()
        self.matches: list[ErrorMaskMatch] = []

    @classmethod
    def check(cls, source: str) -> list[ErrorMaskMatch]:
        """Parse *source* and return all error-mask matches."""
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Malformed source cannot be analyzed; defer to other validators.
            return []
        detector = cls(source)
        detector.visit(tree)
        return detector.matches

    def _line_text(self, lineno: int) -> str:
        """Return the raw source line for *lineno* (1-based)."""
        if 1 <= lineno <= len(self.lines):
            return self.lines[lineno - 1]
        return ""

    def _has_permitted_comment(self, lineno: int) -> bool:
        """True if the line (or the line before) carries a permitted annotation."""
        for offset in (0, -1):
            candidate = lineno + offset
            if candidate < 1:
                continue
            line = self._line_text(candidate)
            if self._PERMITTED_RE.search(line):
                return True
        return False

    def _is_recovery_action(self, node: ast.AST) -> bool:
        """Return True if *node* performs meaningful recovery (re-raise/log+return)."""
        # A single statement that re-raises or returns a non-None sentinel is not a mask.
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Return):
            # Returning None silently is the mask; returning a sentinel is recovery.
            return node.value is not None and not isinstance(node.value, ast.Constant)
        if isinstance(node, ast.Expr):
            # logger.warning(...) followed by nothing else is still a mask unless we
            # also return/raise. We only treat logging as recovery if it is part of a
            # larger block that ends in raise/return sentinel.
            return False
        if isinstance(node, ast.Call):
            # A bare call like logger.exception(...) without re-raise is not recovery.
            return False
        return False

    def _block_has_recovery(self, body: list[ast.stmt]) -> bool:
        """Return True if the exception body ends with a recovery action."""
        if not body:
            return False
        # Strip trailing Expr nodes (logging-only tails) and check the last real stmt.
        meaningful = [s for s in body if not isinstance(s, ast.Expr)]
        if not meaningful:
            return False
        return self._is_recovery_action(meaningful[-1])

    def _body_returns_none(self, body: list[ast.stmt]) -> bool:
        """True if the handler body returns None or nothing at all."""
        if not body:
            return True
        last = body[-1]
        if isinstance(last, ast.Return):
            return last.value is None or (
                isinstance(last.value, ast.Constant) and last.value.value is None
            )
        if isinstance(last, ast.Pass):
            return True
        return False

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
        for handler in node.handlers:
            self._check_handler(handler)
        self.generic_visit(node)

    def _check_handler(self, handler: ast.ExceptHandler) -> None:
        lineno = handler.lineno
        permitted = self._has_permitted_comment(lineno)

        # Bare except: catches everything including SystemExit.
        if handler.type is None:
            self.matches.append(
                ErrorMaskMatch(
                    line=lineno,
                    pattern="bare-except",
                    message="Bare except clause swallows all exceptions including SystemExit.",
                    permitted=permitted,
                )
            )
            return

        # Broad exception classes.
        type_name = ""
        if isinstance(handler.type, ast.Name):
            type_name = handler.type.id
        elif isinstance(handler.type, ast.Tuple):
            names = [elt.id for elt in handler.type.elts if isinstance(elt, ast.Name)]
            if names:
                type_name = names[0]

        is_broad = type_name in self._BROAD_EXCEPTIONS

        # Empty or pass-only body.
        body = handler.body
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            self.matches.append(
                ErrorMaskMatch(
                    line=lineno,
                    pattern="except-pass",
                    message=f"{type_name or 'Except'} handler contains only 'pass'; errors are silently discarded.",
                    permitted=permitted,
                )
            )
            return

        # Return None silently.
        if self._body_returns_none(body) and is_broad:
            self.matches.append(
                ErrorMaskMatch(
                    line=lineno,
                    pattern="except-return-none",
                    message=f"{type_name} handler returns None without re-raising or logging; errors are masked.",
                    permitted=permitted,
                )
            )
            return

        # Logging-only handler with broad exception and no re-raise/recovery.
        if is_broad and not self._block_has_recovery(body):
            # Confirm the body is mostly logging calls.
            all_logging = all(
                isinstance(stmt, (ast.Expr, ast.Assign, ast.AnnAssign)) for stmt in body
            )
            if all_logging:
                self.matches.append(
                    ErrorMaskMatch(
                        line=lineno,
                        pattern="except-log-no-recovery",
                        message=f"{type_name} handler logs but does not re-raise or return a sentinel; errors are masked.",
                        permitted=permitted,
                    )
                )
                return

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        for item in node.items:
            ctx = item.context_expr
            if not isinstance(ctx, ast.Call):
                continue
            func = ctx.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "suppress":
                continue
            # contextlib.suppress or similar suppress call.
            value = func.value
            if isinstance(value, ast.Name) and value.id == "contextlib":
                lineno = node.lineno
                permitted = self._has_permitted_comment(lineno)
                args = ctx.args
                if not args:
                    # suppress() with no args is a no-op, not interesting.
                    continue
                arg_names = [arg.id for arg in args if isinstance(arg, ast.Name)]
                broad = [a for a in arg_names if a in self._BROAD_EXCEPTIONS]
                if broad:
                    self.matches.append(
                        ErrorMaskMatch(
                            line=lineno,
                            pattern="contextlib-suppress-broad",
                            message=f"contextlib.suppress({', '.join(broad)}) discards broad exceptions silently.",
                            permitted=permitted,
                        )
                    )
        self.generic_visit(node)


def error_mask_violations(source: str) -> list[dict[str, Any]]:
    """Return matches formatted as SafetyGuardrail-compatible violations.

    Permitted matches (those with a valid accountability comment) are filtered
    out. The remaining matches are violations that should block the artifact.
    """
    matches = ErrorMaskDetector.check(source)
    return [
        {
            "rule": match.pattern,
            "line": match.line,
            "message": match.message,
        }
        for match in matches
        if not match.permitted
    ]


# RACT 0.1.0 - Initial Public Release
