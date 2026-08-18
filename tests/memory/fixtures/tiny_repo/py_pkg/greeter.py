"""Greeter module — one class, one method, one function."""

from typing import Union

Name = Union[str, bytes]


class Greeter:
    """A polite greeter."""

    def greet(self, who: Name) -> str:
        """Return a greeting for ``who``."""
        return f"Hello, {who!r}"


def make_greeter() -> Greeter:
    """Factory that returns a fresh Greeter."""
    return Greeter()
