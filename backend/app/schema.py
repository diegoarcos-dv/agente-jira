from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class ProposalSchemaValidator:
    def __init__(self, schema_path: Path):
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.validator = Draft202012Validator(
            self.schema,
            format_checker=FormatChecker(),
        )

    def validate(self, proposal: dict[str, Any]) -> None:
        errors = sorted(self.validator.iter_errors(proposal), key=lambda error: list(error.path))
        if not errors:
            return
        messages = []
        for error in errors[:10]:
            path = ".".join(str(part) for part in error.absolute_path) or "$"
            messages.append(f"{path}: {error.message}")
        raise ValueError("La propuesta no cumple el esquema v1.1: " + "; ".join(messages))

