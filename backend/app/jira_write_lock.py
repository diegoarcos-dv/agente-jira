from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any


class GlobalJiraWriteLockError(RuntimeError):
    """Safe, non-secret error raised before an MCP/Jira write transport call."""

    def __init__(self, message: str, *, code: str, state: str) -> None:
        super().__init__(message)
        self.code = code
        self.state = state


class GlobalJiraWriteLock:
    """One process-local, fail-closed authorization window for Jira writes."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl_seconds = max(60, min(int(ttl_seconds), 3600))
        self._mutex = threading.RLock()
        self._state = "LOCKED"
        self._expires_at: datetime | None = None
        self._enabled_by: str | None = None
        self._last_changed_at = self._now()
        self._events: list[dict[str, Any]] = []
        self._record_locked("STARTUP_LOCKED", "system", "LOCKED")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None

    def _record_locked(self, event: str, actor: str, state: str, reason: str | None = None) -> None:
        self._events.append(
            {
                "event": event,
                "actor": actor,
                "at": self._iso(self._last_changed_at),
                "expires_at": self._iso(self._expires_at),
                "state": state,
                "reason": reason,
            }
        )
        del self._events[:-200]

    def _expire_locked(self, now: datetime) -> None:
        if self._state == "UNLOCKED_TEMPORARY" and self._expires_at and now >= self._expires_at:
            self._state = "EXPIRED"
            self._expires_at = None
            self._enabled_by = None
            self._last_changed_at = now
            self._record_locked("AUTO_EXPIRED", "system", "EXPIRED", "TTL_EXPIRED")

    def status(self) -> dict[str, Any]:
        with self._mutex:
            self._expire_locked(self._now())
            return {
                "state": self._state,
                "locked": self._state != "UNLOCKED_TEMPORARY",
                "expires_at": self._iso(self._expires_at),
                "ttl_seconds": self.ttl_seconds,
                "enabled_by": self._enabled_by,
                "last_changed_at": self._iso(self._last_changed_at),
                "last_event": self._events[-1] if self._events else None,
            }

    def audit(self) -> list[dict[str, Any]]:
        with self._mutex:
            self._expire_locked(self._now())
            return [dict(event) for event in self._events]

    def unlock(self, actor: str, *, authorized: bool) -> dict[str, Any]:
        with self._mutex:
            if not authorized:
                self._last_changed_at = self._now()
                self._record_locked("UNLOCK_REJECTED", actor, self._state, "UNAUTHORIZED")
                raise GlobalJiraWriteLockError(
                    "No tienes autorización para habilitar escrituras Jira.",
                    code="JIRA_WRITE_UNLOCK_FORBIDDEN",
                    state=self._state,
                )
            now = self._now()
            self._state = "UNLOCKED_TEMPORARY"
            self._expires_at = now + timedelta(seconds=self.ttl_seconds)
            self._enabled_by = actor
            self._last_changed_at = now
            self._record_locked("UNLOCKED_TEMPORARY", actor, self._state, "USER_REQUEST")
            return self.status()

    def lock(self, actor: str, *, reason: str = "MANUAL_LOCK") -> dict[str, Any]:
        with self._mutex:
            now = self._now()
            self._state = "LOCKED"
            self._expires_at = None
            self._enabled_by = None
            self._last_changed_at = now
            self._record_locked("MANUAL_LOCK", actor, self._state, reason)
            return self.status()

    def assert_can_write(self, actor: str, tool_name: str = "createJiraIssue") -> None:
        """Atomically authorize the point immediately before transport invocation."""

        with self._mutex:
            self._ensure_unlocked_locked(actor)
            self._record_locked("WRITE_STARTED", actor, self._state, tool_name)

    def ensure_unlocked(self, actor: str) -> None:
        """Check the current lock without claiming a transport write."""

        with self._mutex:
            self._ensure_unlocked_locked(actor)

    def _ensure_unlocked_locked(self, actor: str) -> None:
        now = self._now()
        self._expire_locked(now)
        if self._state == "UNLOCKED_TEMPORARY":
            return
        code = "JIRA_WRITE_LOCK_EXPIRED" if self._state == "EXPIRED" else "JIRA_WRITE_GLOBALLY_LOCKED"
        message = (
            "La autorización de escritura venció. Habilítala nuevamente."
            if code == "JIRA_WRITE_LOCK_EXPIRED"
            else "Las escrituras en Jira están bloqueadas. Puedes seguir revisando y validando actividades."
        )
        self._last_changed_at = now
        self._record_locked("WRITE_REJECTED", actor, self._state, code)
        raise GlobalJiraWriteLockError(message, code=code, state=self._state)
