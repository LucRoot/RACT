"""Custom error hierarchy."""


class TinyError(Exception):
    """Root of the tiny-repo error hierarchy."""


class TinyValueError(TinyError):
    """Raised on bad value input."""
