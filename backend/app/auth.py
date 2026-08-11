from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from typing import Protocol

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings
from .models import LoginRequest, SessionResponse


@dataclass(frozen=True)
class AuthenticatedUser:
    username: str
    display_name: str


class AuthProvider(Protocol):
    def login(self, credentials: LoginRequest) -> SessionResponse: ...

    def resolve(self, token: str) -> AuthenticatedUser | None: ...


class LocalAuthProvider:
    """Proveedor local reemplazable posteriormente por un adaptador Cognito."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._sessions: dict[str, AuthenticatedUser] = {}

    def login(self, credentials: LoginRequest) -> SessionResponse:
        valid_user = hmac.compare_digest(credentials.username, self.settings.local_user)
        valid_password = hmac.compare_digest(credentials.password, self.settings.local_password)
        if not (valid_user and valid_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario o contraseña incorrectos.",
            )
        token = secrets.token_urlsafe(32)
        user = AuthenticatedUser(
            username=credentials.username,
            display_name="Administrador local",
        )
        self._sessions[token] = user
        return SessionResponse(
            access_token=token,
            user={"username": user.username, "display_name": user.display_name},
        )

    def resolve(self, token: str) -> AuthenticatedUser | None:
        return self._sessions.get(token)


_provider = LocalAuthProvider(get_settings())
_bearer = HTTPBearer(auto_error=False)


def get_auth_provider() -> AuthProvider:
    return _provider


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    provider: AuthProvider = Depends(get_auth_provider),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Autenticación requerida.")
    user = provider.resolve(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Sesión inválida o vencida.")
    return user

