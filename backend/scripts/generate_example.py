from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.models import PlanDefaults
from app.repository import ProposalRepository
from app.schema import ProposalSchemaValidator
from app.service import ProposalService


ROOT = BACKEND_DIR.parent
SOURCE = ROOT / "examples" / "plan_timeline_referencia_v1_1_valido.xlsx"
OUTPUT = ROOT / "examples" / "propuesta_timeline_referencia_v1_1.json"
TEMP_DB = ROOT / "tmp" / "generate-example.db"


def main() -> None:
    TEMP_DB.parent.mkdir(parents=True, exist_ok=True)
    if TEMP_DB.exists():
        TEMP_DB.unlink()
    service = ProposalService(
        ProposalRepository(TEMP_DB),
        ProposalSchemaValidator(
            ROOT / "docs" / "schemas" / "jira_proposal_v1_1.schema.json"
        ),
    )
    proposal = service.create_from_workbook(
        filename=SOURCE.name,
        content=SOURCE.read_bytes(),
        defaults=PlanDefaults(
            space="AT",
            iniciativa="Piloto timeline",
            tipo_seguimiento="Semanal",
        ),
        created_by="evidencia-local@agentejira.local",
    )
    service.validator.validate(proposal)
    OUTPUT.write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
