from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from ..auth import AuthenticatedUser
from .models import VoiceConversationContext


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VoiceContextStore:
    """Small SQLite-backed state separated by authenticated local session."""

    def __init__(
        self,
        database_path: Path,
        ttl_seconds: int,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.database_path = database_path
        self.ttl_seconds = max(60, ttl_seconds)
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_contexts (
                    session_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    document TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_voice_contexts_expiration
                ON voice_contexts (expires_at)
                """
            )

    def _identity(self, user: AuthenticatedUser) -> str:
        return user.session_id or f"local:{user.username}"

    def _new_context(self, user: AuthenticatedUser) -> VoiceConversationContext:
        now = self.clock()
        return VoiceConversationContext(
            session_id=self._identity(user),
            username=user.username,
            updated_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
        )

    def purge_expired(self) -> int:
        now = self.clock().isoformat()
        with self._connect() as connection:
            result = connection.execute(
                "DELETE FROM voice_contexts WHERE expires_at <= ?",
                (now,),
            )
        return result.rowcount

    def get(self, user: AuthenticatedUser) -> VoiceConversationContext:
        self.purge_expired()
        session_id = self._identity(user)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT username, document FROM voice_contexts
                WHERE session_id = ? AND expires_at > ?
                """,
                (session_id, self.clock().isoformat()),
            ).fetchone()
        if row is None or row["username"] != user.username:
            return self._new_context(user)
        try:
            return VoiceConversationContext.model_validate_json(row["document"])
        except (ValueError, json.JSONDecodeError):
            self.clear(user)
            return self._new_context(user)

    def save(self, context: VoiceConversationContext) -> VoiceConversationContext:
        now = self.clock()
        context.updated_at = now.isoformat()
        context.expires_at = (now + timedelta(seconds=self.ttl_seconds)).isoformat()
        document = context.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO voice_contexts
                    (session_id, username, updated_at, expires_at, document)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    username = excluded.username,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    document = excluded.document
                """,
                (
                    context.session_id,
                    context.username,
                    context.updated_at,
                    context.expires_at,
                    document,
                ),
            )
        return context

    def clear(self, user: AuthenticatedUser) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM voice_contexts WHERE session_id = ? AND username = ?",
                (self._identity(user), user.username),
            )

    def count(self) -> int:
        self.purge_expired()
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM voice_contexts").fetchone()
        return int(row["count"])
