from __future__ import annotations


class ApplicationError(ValueError):
    """Safe, transport-neutral failure raised by an application use case."""

    def __init__(self, code: str, message: str, *, kind: str = "invalid") -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.kind = kind
