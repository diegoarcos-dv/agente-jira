from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings
from .models import LoginRequest, SessionResponse
from .repository import ProposalRepository


SESSION_COOKIE = "agente_jira_session"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    display_name: str
    session_id: str = ""
    user_id: int | None = None
    role: str = "USER"
    atlassian_account_id: str | None = None
    email: str | None = None


class AuthProvider(Protocol):
    def login(self, credentials: LoginRequest) -> SessionResponse: ...
    def resolve(self, token: str) -> AuthenticatedUser | None: ...
    def logout(self, token: str) -> None: ...


class FederatedAuthProvider:
    """Local authorization and opaque browser sessions for Atlassian identities."""

    def __init__(self, settings: Settings, repository: ProposalRepository):
        self.settings = settings
        self.repository = repository
        self.repository.ensure_authorized_user(
            username=settings.local_user,
            email=settings.local_user,
            display_name="Administrador local",
            role="ADMIN",
            status="PENDING",
        )

    def local_emergency_login(self, credentials: LoginRequest) -> SessionResponse:
        if not self.settings.emergency_local_auth_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inicio local no disponible.")
        if not self.settings.local_password:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Recuperación local no configurada.")
        if not (
            hmac.compare_digest(credentials.username, self.settings.local_user)
            and hmac.compare_digest(credentials.password, self.settings.local_password)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales de recuperación inválidas.")
        user = self.repository.get_app_user_by_username(self.settings.local_user)
        if user is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario de recuperación no autorizado.")
        # Recovery is explicitly opt-in and only available locally. It may
        # access the pending legacy administrator long enough to complete the
        # federated migration, without marking that account as OAuth-linked.
        return self.create_session(user, allow_pending_recovery=True)

    def login(self, credentials: LoginRequest) -> SessionResponse:
        return self.local_emergency_login(credentials)

    def create_session(
        self,
        user: dict[str, object],
        *,
        allow_pending_recovery: bool = False,
    ) -> SessionResponse:
        if user.get("status") != "ACTIVE" and not (
            allow_pending_recovery
            and user.get("status") == "PENDING"
            and user.get("username") == self.settings.local_user
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tu cuenta no está activa en el Agente Jira.")
        token = secrets.token_urlsafe(32)
        now = _now()
        self.repository.save_session(
            _hash(token), int(user["id"]), _iso(now), _iso(now + timedelta(seconds=self.settings.app_session_ttl_seconds)),
        )
        self.repository.audit_auth_event("LOGIN_SUCCESS", _iso(now), int(user["id"]))
        return SessionResponse(
            access_token="",
            user={
                "username": str(user["username"]),
                "display_name": str(user["display_name"]),
                "role": str(user["role"]),
                "email": str(user["email"]),
                "atlassian_account_id": str(user.get("atlassian_account_id") or ""),
            },
            session_token=token,
        )

    def resolve(self, token: str) -> AuthenticatedUser | None:
        user = self.repository.resolve_session(_hash(token), _iso(_now()))
        recovery_session = bool(
            user
            and self.settings.emergency_local_auth_enabled
            and user.get("status") == "PENDING"
            and user.get("username") == self.settings.local_user
        )
        if user is None or (user.get("status") != "ACTIVE" and not recovery_session):
            return None
        return AuthenticatedUser(
            username=str(user["username"]), display_name=str(user["display_name"]), session_id=_hash(token),
            user_id=int(user["id"]), role=str(user["role"]),
            atlassian_account_id=user.get("atlassian_account_id"), email=user.get("email"),
        )

    def logout(self, token: str) -> None:
        user = self.resolve(token)
        self.repository.revoke_session(_hash(token), _iso(_now()))
        self.repository.audit_auth_event("LOGOUT", _iso(_now()), user.user_id if user else None)


_provider = FederatedAuthProvider(get_settings(), ProposalRepository(get_settings().database_path))
_bearer = HTTPBearer(auto_error=False)


def get_auth_provider() -> AuthProvider:
    return _provider


def require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    cookie_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    provider: AuthProvider = Depends(get_auth_provider),
) -> AuthenticatedUser:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else cookie_token
    if not token:
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    user = provider.resolve(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o vencida.")
    request.state.session_token = token
    return user
