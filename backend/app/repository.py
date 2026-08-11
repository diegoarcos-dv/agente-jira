from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class ProposalRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS proposal_versions (
                    proposal_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    document TEXT NOT NULL,
                    PRIMARY KEY (proposal_id, version)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS proposal_lifecycle (
                    proposal_id TEXT PRIMARY KEY,
                    archived_at TEXT,
                    archived_by TEXT,
                    display_name TEXT,
                    display_name_updated_at TEXT,
                    display_name_updated_by TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jira_dry_runs (
                    dry_run_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    proposal_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    document TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jira_dry_runs_proposal
                ON jira_dry_runs (proposal_id, proposal_version, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jira_execution_intents (
                    execution_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    proposal_version INTEGER NOT NULL,
                    row_id TEXT NOT NULL,
                    dry_run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    document TEXT NOT NULL,
                    UNIQUE (proposal_id, proposal_version, row_id, dry_run_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jira_execution_intents_proposal
                ON jira_execution_intents (proposal_id, updated_at DESC)
                """
            )
            existing_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(proposal_lifecycle)"
                ).fetchall()
            }
            for column in (
                "display_name",
                "display_name_updated_at",
                "display_name_updated_by",
            ):
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE proposal_lifecycle ADD COLUMN {column} TEXT"
                    )

    def save(self, proposal: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO proposal_versions
                    (proposal_id, version, status, source_file, created_at, document)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal["proposal_id"],
                    proposal["version"],
                    proposal["status"],
                    proposal["source_file"]["name"],
                    proposal["created_at"],
                    json.dumps(proposal, ensure_ascii=False),
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO proposal_lifecycle
                    (proposal_id, archived_at, archived_by, display_name)
                VALUES (?, NULL, NULL, ?)
                """,
                (proposal["proposal_id"], Path(proposal["source_file"]["name"]).stem),
            )
        return proposal

    def get(self, proposal_id: str, version: int | None = None) -> dict[str, Any] | None:
        if version is None:
            query = """
                SELECT document FROM proposal_versions
                WHERE proposal_id = ?
                ORDER BY version DESC LIMIT 1
            """
            params = (proposal_id,)
        else:
            query = """
                SELECT document FROM proposal_versions
                WHERE proposal_id = ? AND version = ?
            """
            params = (proposal_id, version)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return json.loads(row["document"]) if row else None

    def list_latest(self) -> list[dict[str, Any]]:
        return [proposal for proposal, _ in self.list_latest_with_lifecycle()]

    def list_latest_with_lifecycle(
        self,
    ) -> list[tuple[dict[str, Any], dict[str, str | None]]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pv.document, pl.archived_at, pl.archived_by,
                       pl.display_name, pl.display_name_updated_at,
                       pl.display_name_updated_by
                FROM proposal_versions pv
                JOIN (
                    SELECT proposal_id, MAX(version) AS version
                    FROM proposal_versions
                    GROUP BY proposal_id
                ) latest
                ON latest.proposal_id = pv.proposal_id
                AND latest.version = pv.version
                LEFT JOIN proposal_lifecycle pl
                ON pl.proposal_id = pv.proposal_id
                ORDER BY pv.created_at DESC
                """
            ).fetchall()
        return [
            (
                json.loads(row["document"]),
                {
                    "archived_at": row["archived_at"],
                    "archived_by": row["archived_by"],
                    "display_name": row["display_name"],
                    "display_name_updated_at": row["display_name_updated_at"],
                    "display_name_updated_by": row["display_name_updated_by"],
                },
            )
            for row in rows
        ]

    def set_archived(
        self,
        proposal_id: str,
        *,
        archived_at: str | None,
        archived_by: str | None,
    ) -> bool:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM proposal_versions WHERE proposal_id = ? LIMIT 1",
                (proposal_id,),
            ).fetchone()
            if exists is None:
                return False
            connection.execute(
                """
                INSERT INTO proposal_lifecycle
                    (proposal_id, archived_at, archived_by)
                VALUES (?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    archived_at = excluded.archived_at,
                    archived_by = excluded.archived_by
                """,
                (proposal_id, archived_at, archived_by),
            )
        return True

    def get_lifecycle(self, proposal_id: str) -> dict[str, str | None]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT archived_at, archived_by, display_name,
                       display_name_updated_at, display_name_updated_by
                FROM proposal_lifecycle
                WHERE proposal_id = ?
                """,
                (proposal_id,),
            ).fetchone()
        if row is None:
            return {
                "archived_at": None,
                "archived_by": None,
                "display_name": None,
                "display_name_updated_at": None,
                "display_name_updated_by": None,
            }
        return {
            "archived_at": row["archived_at"],
            "archived_by": row["archived_by"],
            "display_name": row["display_name"],
            "display_name_updated_at": row["display_name_updated_at"],
            "display_name_updated_by": row["display_name_updated_by"],
        }

    def set_display_name(
        self,
        proposal_id: str,
        *,
        display_name: str,
        updated_at: str,
        updated_by: str,
    ) -> bool:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM proposal_versions WHERE proposal_id = ? LIMIT 1",
                (proposal_id,),
            ).fetchone()
            if exists is None:
                return False
            connection.execute(
                """
                INSERT INTO proposal_lifecycle
                    (proposal_id, display_name, display_name_updated_at,
                     display_name_updated_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    display_name_updated_at = excluded.display_name_updated_at,
                    display_name_updated_by = excluded.display_name_updated_by
                """,
                (proposal_id, display_name, updated_at, updated_by),
            )
        return True

    def save_dry_run(
        self,
        dry_run: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Persist once by deterministic ID; repeated previews return the original audit record."""

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT document FROM jira_dry_runs WHERE dry_run_id = ?",
                (dry_run["dry_run_id"],),
            ).fetchone()
            if existing is not None:
                return json.loads(existing["document"]), True
            connection.execute(
                """
                INSERT INTO jira_dry_runs
                    (dry_run_id, proposal_id, proposal_version, status,
                     created_at, created_by, document)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dry_run["dry_run_id"],
                    dry_run["proposal_id"],
                    dry_run["proposal_version"],
                    dry_run["status"],
                    dry_run["generated_at"],
                    dry_run["generated_by"],
                    json.dumps(dry_run, ensure_ascii=False),
                ),
            )
        return dry_run, False

    def get_latest_dry_run(
        self,
        proposal_id: str,
        proposal_version: int | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            if proposal_version is None:
                row = connection.execute(
                    """
                    SELECT document FROM jira_dry_runs
                    WHERE proposal_id = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (proposal_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT document FROM jira_dry_runs
                    WHERE proposal_id = ? AND proposal_version = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (proposal_id, proposal_version),
                ).fetchone()
        return json.loads(row["document"]) if row else None

    def save_execution_intent(
        self,
        intent: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Persist one Objective 4A intent for a proposal/version/row/Dry run tuple."""

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT document FROM jira_execution_intents
                WHERE proposal_id = ? AND proposal_version = ?
                  AND row_id = ? AND dry_run_id = ?
                """,
                (
                    intent["proposal_id"],
                    intent["proposal_version"],
                    intent["row_id"],
                    intent["dry_run_id"],
                ),
            ).fetchone()
            if existing is not None:
                return json.loads(existing["document"]), True
            connection.execute(
                """
                INSERT INTO jira_execution_intents
                    (execution_id, proposal_id, proposal_version, row_id,
                     dry_run_id, status, created_at, updated_at, created_by,
                     idempotency_key, payload_hash, document)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent["execution_id"],
                    intent["proposal_id"],
                    intent["proposal_version"],
                    intent["row_id"],
                    intent["dry_run_id"],
                    intent["status"],
                    intent["created_at"],
                    intent["updated_at"],
                    intent["created_by"],
                    intent["idempotency_key"],
                    intent["payload_hash"],
                    json.dumps(intent, ensure_ascii=False),
                ),
            )
        return intent, False

    def update_execution_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE jira_execution_intents
                SET status = ?, updated_at = ?, payload_hash = ?, document = ?
                WHERE execution_id = ?
                """,
                (
                    intent["status"],
                    intent["updated_at"],
                    intent["payload_hash"],
                    json.dumps(intent, ensure_ascii=False),
                    intent["execution_id"],
                ),
            )
            if updated.rowcount != 1:
                raise KeyError(intent["execution_id"])
        return intent

    def get_execution_intent(self, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM jira_execution_intents WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return json.loads(row["document"]) if row else None

    def get_latest_execution_intent(
        self,
        proposal_id: str,
        objective: str | None = None,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT document FROM jira_execution_intents
                WHERE proposal_id = ?
                ORDER BY updated_at DESC
                """,
                (proposal_id,),
            ).fetchall()
        for row in rows:
            document = json.loads(row["document"])
            if objective is None or document.get("objective") == objective:
                return document
        return None

    def list_execution_intents(
        self,
        proposal_id: str,
        objective: str | None = None,
        proposal_version: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT document FROM jira_execution_intents
                WHERE proposal_id = ?
                ORDER BY updated_at DESC
                """,
                (proposal_id,),
            ).fetchall()
        documents = [json.loads(row["document"]) for row in rows]
        return [
            document
            for document in documents
            if (objective is None or document.get("objective") == objective)
            and (proposal_version is None or document.get("proposal_version") == proposal_version)
        ]
