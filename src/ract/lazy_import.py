"""A module that is imported when it is first used (B-087b).

``httpx`` costs about a quarter of a second, and a module that only needs it
inside its methods made every ``ract`` start pay for it (``ract --version``
included). ``httpx = lazy_module("httpx")`` keeps every ``httpx.X`` in such a
module as it is; the import happens at the first attribute read.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any


class _LazyModule:
    __slots__ = ("_name", "_module")

    def __init__(self, name: str) -> None:
        self._name = name
        self._module: ModuleType | None = None

    def __getattr__(self, attr: str) -> Any:
        module = self._module
        if module is None:
            module = import_module(self._name)
            self._module = module
        return getattr(module, attr)

    def __repr__(self) -> str:
        state = "loaded" if self._module is not None else "not loaded yet"
        return f"<lazy module {self._name!r}, {state}>"


def lazy_module(name: str) -> Any:
    """A stand-in for the module *name* that imports it at the first attribute read."""
    return _LazyModule(name)
