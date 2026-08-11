from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    row: int | None = None
    column: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "row": self.row,
            "column": self.column,
        }


class WorkbookValidationError(ValueError):
    def __init__(self, message: str, issues: list[ValidationIssue]):
        super().__init__(message)
        self.message = message
        self.issues = issues


class ProposalStateError(ValueError):
    """Raised when an operation is incompatible with the proposal lifecycle."""
