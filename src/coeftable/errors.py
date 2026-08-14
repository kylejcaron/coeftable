"""Shared exceptions for invalid table specifications."""


class SpecError(ValueError):
    """Raised when a table specification is internally inconsistent."""


class ColumnNotFoundError(KeyError):
    """Raised when a specification names a column absent from the frame."""
