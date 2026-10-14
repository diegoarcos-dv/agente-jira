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
                    deleted_at TEXT,
                    deleted_by TEXT,
                    purge_at TEXT,
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
                CREATE TABLE IF NOT EXISTS minutes_enrichments (
                    proposal_id TEXT PRIMARY KEY,
                    base_version INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    suggestions TEXT NOT NULL,
                    message TEXT,
                    failure_code TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    duration_ms REAL
                )
                """
            )
            enrichment_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(minutes_enrichments)"
                ).fetchall()
            }
            if "failure_code" not in enrichment_columns:
                connection.execute(
                    "ALTER TABLE minutes_enrichments ADD COLUMN failure_code TEXT"
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
                "deleted_at",
                "deleted_by",
                "purge_at",
                "display_name",
                "display_name_updated_at",
                "display_name_updated_by",
            ):
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE proposal_lifecycle ADD COLUMN {column} TEXT"
                    )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('ADMIN', 'USER')),
                    status TEXT NOT NULL CHECK(status IN ('PENDING', 'ACTIVE', 'DISABLED')),
                    atlassian_account_id TEXT UNIQUE,
                    atlassian_linked_at TEXT,
                    last_login_at TEXT
                )
                """
            )
            app_user_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(app_users)").fetchall()
            }
            # Onboarding is per local user.  Keep this migration additive so
            # existing OAuth identities and sessions remain untouched.
            for column, definition in (
                ("onboarding_version", "INTEGER NOT NULL DEFAULT 0"),
                ("onboarding_completed_at", "TEXT"),
                ("onboarding_skipped_at", "TEXT"),
            ):
                if column not in app_user_columns:
                    connection.execute(f"ALTER TABLE app_users ADD COLUMN {column} {definition}")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_sessions (
                    session_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES app_users(id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_login_states (
                    state_hash TEXT PRIMARY KEY,
                    pending_identity TEXT NOT NULL,
                    return_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS atlassian_credentials (
                    user_id INTEGER PRIMARY KEY REFERENCES app_users(id),
                    atlassian_account_id TEXT NOT NULL UNIQUE,
                    storage_key TEXT NOT NULL UNIQUE,
                    expires_at TEXT,
                    scopes TEXT,
                    cloud_id TEXT,
                    site_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES app_users(id),
                    event TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    detail TEXT
                )
                """
            )

    @staticmethod
    def _app_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def ensure_authorized_user(
        self,
        *,
        username: str,
        email: str,
        display_name: str,
        role: str = "USER",
        status: str = "PENDING",
    ) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_users (username, email, display_name, role, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    display_name = excluded.display_name,
                    role = excluded.role,
                    status = CASE
                        WHEN app_users.atlassian_account_id IS NULL THEN excluded.status
                        ELSE app_users.status
                    END
                """,
                (username, email.strip().casefold(), display_name.strip() or email, role, status),
            )
            row = connection.execute("SELECT * FROM app_users WHERE email = ?", (email.strip().casefold(),)).fetchone()
        return self._app_user(row) or {}

    def get_app_user_by_account_id(self, account_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM app_users WHERE atlassian_account_id = ?", (account_id,)).fetchone()
        return self._app_user(row)

    def get_app_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM app_users WHERE email = ?", (email.strip().casefold(),)).fetchone()
        return self._app_user(row)

    def get_app_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM app_users WHERE username = ?", (username,)).fetchone()
        return self._app_user(row)

    def link_atlassian_account(self, user_id: int, account_id: str, linked_at: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM app_users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise KeyError(user_id)
            existing = connection.execute(
                "SELECT id FROM app_users WHERE atlassian_account_id = ?", (account_id,)
            ).fetchone()
            if existing is not None and existing["id"] != user_id:
                raise ValueError("La cuenta Atlassian ya está vinculada a otro usuario del Agente Jira.")
            connection.execute(
                """
                UPDATE app_users
                SET atlassian_account_id = ?, atlassian_linked_at = ?, status = 'ACTIVE'
                WHERE id = ?
                """,
                (account_id, linked_at, user_id),
            )
            updated = connection.execute("SELECT * FROM app_users WHERE id = ?", (user_id,)).fetchone()
        return self._app_user(updated) or {}

    def touch_app_user_login(self, user_id: int, logged_in_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE app_users SET last_login_at = ? WHERE id = ?",
                (logged_in_at, user_id),
            )

    def get_onboarding_status(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT onboarding_version, onboarding_completed_at, onboarding_skipped_at FROM app_users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_onboarding_complete(self, user_id: int, version: int, completed_at: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE app_users SET onboarding_version = ?, onboarding_completed_at = ?, onboarding_skipped_at = NULL WHERE id = ?",
                (version, completed_at, user_id),
            )
            row = connection.execute(
                "SELECT onboarding_version, onboarding_completed_at, onboarding_skipped_at FROM app_users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def mark_onboarding_skipped(self, user_id: int, version: int, skipped_at: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE app_users SET onboarding_version = ?, onboarding_skipped_at = ?, onboarding_completed_at = NULL WHERE id = ?",
                (version, skipped_at, user_id),
            )
            row = connection.execute(
                "SELECT onboarding_version, onboarding_completed_at, onboarding_skipped_at FROM app_users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def save_session(self, session_hash: str, user_id: int, created_at: str, expires_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_sessions (session_hash, user_id, created_at, expires_at, revoked_at) VALUES (?, ?, ?, ?, NULL)",
                (session_hash, user_id, created_at, expires_at),
            )

    def resolve_session(self, session_hash: str, now: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT u.* FROM app_sessions s JOIN app_users u ON u.id = s.user_id
                WHERE s.session_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?
                """,
                (session_hash, now),
            ).fetchone()
        return self._app_user(row)

    def revoke_session(self, session_hash: str, revoked_at: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE app_sessions SET revoked_at = ? WHERE session_hash = ?", (revoked_at, session_hash))

    def record_oauth_state(self, state_hash: str, pending_identity: str, return_path: str, created_at: str, expires_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO oauth_login_states (state_hash, pending_identity, return_path, created_at, expires_at, used_at) VALUES (?, ?, ?, ?, ?, NULL)",
                (state_hash, pending_identity, return_path, created_at, expires_at),
            )

    def consume_oauth_state(self, state_hash: str, used_at: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_login_states WHERE state_hash = ? AND used_at IS NULL AND expires_at > ?",
                (state_hash, used_at),
            ).fetchone()
            if row is None:
                return None
            connection.execute("UPDATE oauth_login_states SET used_at = ? WHERE state_hash = ? AND used_at IS NULL", (used_at, state_hash))
        return dict(row)

    def save_atlassian_credential_metadata(
        self, *, user_id: int, account_id: str, storage_key: str, expires_at: str | None,
        scopes: str | None, cloud_id: str | None, site_url: str | None, now: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO atlassian_credentials
                    (user_id, atlassian_account_id, storage_key, expires_at, scopes, cloud_id, site_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    atlassian_account_id = excluded.atlassian_account_id,
                    storage_key = excluded.storage_key,
                    expires_at = excluded.expires_at,
                    scopes = excluded.scopes,
                    cloud_id = excluded.cloud_id,
                    site_url = excluded.site_url,
                    updated_at = excluded.updated_at
                """,
                (user_id, account_id, storage_key, expires_at, scopes, cloud_id, site_url, now, now),
            )

    def clear_atlassian_credential_metadata(self, user_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM atlassian_credentials WHERE user_id = ?", (user_id,))

    def audit_auth_event(self, event: str, created_at: str, user_id: int | None = None, detail: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_audit_events (user_id, event, created_at, detail) VALUES (?, ?, ?, ?)",
                (user_id, event, created_at, detail),
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

    def save_minutes_enrichment(
        self,
        proposal_id: str,
        *,
        base_version: int,
        state: str,
        suggestions: list[dict[str, Any]],
        message: str | None,
        started_at: str,
        completed_at: str | None = None,
        duration_ms: float | None = None,
        failure_code: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO minutes_enrichments
                    (proposal_id, base_version, state, suggestions, message, failure_code,
                     started_at, completed_at, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    base_version=excluded.base_version,
                    state=excluded.state,
                    suggestions=excluded.suggestions,
                    message=excluded.message,
                    failure_code=excluded.failure_code,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    duration_ms=excluded.duration_ms
                """,
                (proposal_id, base_version, state, json.dumps(suggestions, ensure_ascii=False),
                 message, failure_code, started_at, completed_at, duration_ms),
            )

    def get_minutes_enrichment(self, proposal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM minutes_enrichments WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "proposal_id": row["proposal_id"],
            "base_version": row["base_version"],
            "state": row["state"],
            "suggestions": json.loads(row["suggestions"]),
            "message": row["message"],
            "failure_code": row["failure_code"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "duration_ms": row["duration_ms"],
        }

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
        *,
        include_trashed: bool = False,
    ) -> list[tuple[dict[str, Any], dict[str, str | None]]]:
        trash_filter = "" if include_trashed else "WHERE pl.deleted_at IS NULL"
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT pv.document, pl.archived_at, pl.archived_by,
                       pl.deleted_at, pl.deleted_by, pl.purge_at,
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
                {trash_filter}
                ORDER BY pv.created_at DESC
                """
            ).fetchall()
        return [
            (
                json.loads(row["document"]),
                {
                    "archived_at": row["archived_at"],
                    "archived_by": row["archived_by"],
                    "deleted_at": row["deleted_at"],
                    "deleted_by": row["deleted_by"],
                    "purge_at": row["purge_at"],
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

    def set_trashed(
        self,
        proposal_id: str,
        *,
        deleted_at: str | None,
        deleted_by: str | None,
        purge_at: str | None,
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
                    (proposal_id, deleted_at, deleted_by, purge_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET
                    deleted_at = excluded.deleted_at,
                    deleted_by = excluded.deleted_by,
                    purge_at = excluded.purge_at
                """,
                (proposal_id, deleted_at, deleted_by, purge_at),
            )
        return True

    @staticmethod
    def _delete_proposal_records(connection: sqlite3.Connection, proposal_id: str) -> None:
        connection.execute("DELETE FROM jira_execution_intents WHERE proposal_id = ?", (proposal_id,))
        connection.execute("DELETE FROM jira_dry_runs WHERE proposal_id = ?", (proposal_id,))
        connection.execute("DELETE FROM minutes_enrichments WHERE proposal_id = ?", (proposal_id,))
        connection.execute("DELETE FROM proposal_versions WHERE proposal_id = ?", (proposal_id,))
        connection.execute("DELETE FROM proposal_lifecycle WHERE proposal_id = ?", (proposal_id,))

    def permanently_delete_trashed(self, proposal_id: str) -> str:
        """Permanently delete a proposal only while it is in the trash."""
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM proposal_versions WHERE proposal_id = ? LIMIT 1",
                (proposal_id,),
            ).fetchone()
            if exists is None:
                return "NOT_FOUND"
            lifecycle = connection.execute(
                "SELECT deleted_at FROM proposal_lifecycle WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if lifecycle is None or lifecycle["deleted_at"] is None:
                return "NOT_IN_TRASH"
            self._delete_proposal_records(connection, proposal_id)
        return "DELETED"

    def purge_expired_trash(self, now: str) -> int:
        """Permanently remove proposals whose 30-day recovery window expired."""
        with self._connect() as connection:
            ids = [
                row["proposal_id"]
                for row in connection.execute(
                    "SELECT proposal_id FROM proposal_lifecycle WHERE purge_at IS NOT NULL AND purge_at <= ?",
                    (now,),
                ).fetchall()
            ]
            for proposal_id in ids:
                self._delete_proposal_records(connection, proposal_id)
        return len(ids)

    def get_lifecycle(self, proposal_id: str) -> dict[str, str | None]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT archived_at, archived_by, deleted_at, deleted_by, purge_at,
                       display_name,
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
                "deleted_at": None,
                "deleted_by": None,
                "purge_at": None,
                "display_name": None,
                "display_name_updated_at": None,
                "display_name_updated_by": None,
            }
        return {
            "archived_at": row["archived_at"],
            "archived_by": row["archived_by"],
            "deleted_at": row["deleted_at"],
            "deleted_by": row["deleted_by"],
            "purge_at": row["purge_at"],
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

    def transition_execution_intent(
        self,
        intent: dict[str, Any],
        expected_status: str,
    ) -> bool:
        """Atomically claim an execution state before any external write begins."""

        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE jira_execution_intents
                SET status = ?, updated_at = ?, payload_hash = ?, document = ?
                WHERE execution_id = ? AND status = ?
                """,
                (
                    intent["status"],
                    intent["updated_at"],
                    intent["payload_hash"],
                    json.dumps(intent, ensure_ascii=False),
                    intent["execution_id"],
                    expected_status,
                ),
            )
        return updated.rowcount == 1

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
