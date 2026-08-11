from __future__ import annotations

import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class DataProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob(value: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(value)
    return (
        _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))),
        buffer,
    )


class WindowsDpapiProtector:
    """Encrypt OAuth material for the current Windows user with DPAPI."""

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("DPAPI sólo está disponible en Windows.")
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def protect(self, value: bytes) -> bytes:
        return self._transform("CryptProtectData", value)

    def unprotect(self, value: bytes) -> bytes:
        return self._transform("CryptUnprotectData", value)

    def _transform(self, operation: str, value: bytes) -> bytes:
        source, source_buffer = _blob(value)
        result = _DataBlob()
        function = getattr(self._crypt32, operation)
        if operation == "CryptProtectData":
            success = function(
                ctypes.byref(source),
                "Agente Jira OAuth",
                None,
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(result),
            )
        else:
            success = function(
                ctypes.byref(source),
                None,
                None,
                None,
                None,
                self._CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(result),
            )
        del source_buffer
        if not success:
            raise OSError(ctypes.get_last_error(), "Windows no pudo proteger el estado OAuth.")
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            self._kernel32.LocalFree(result.pbData)


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    return value.dict(exclude_none=True)


class EncryptedFileOAuthStorage(TokenStorage):
    """Atomic, per-user OAuth storage; the persisted bytes are never plaintext."""

    def __init__(
        self,
        directory: Path,
        username: str,
        protector: DataProtector,
    ) -> None:
        identity = hashlib.sha256(username.strip().casefold().encode("utf-8")).hexdigest()
        self.path = directory / f"{identity}.oauth"
        self.protector = protector
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None
        self._load()

    @property
    def has_credentials(self) -> bool:
        return self.tokens is not None and self.client_info is not None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens
        self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info
        self._save()

    def clear(self) -> None:
        self.tokens = None
        self.client_info = None
        self.path.unlink(missing_ok=True)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            document = json.loads(self.protector.unprotect(self.path.read_bytes()))
            if document.get("tokens"):
                self.tokens = OAuthToken.model_validate(document["tokens"])
            if document.get("client_info"):
                self.client_info = OAuthClientInformationFull.model_validate(
                    document["client_info"]
                )
        except Exception as exc:
            raise RuntimeError(
                "No fue posible recuperar la autorización Atlassian guardada. "
                "Desconecta y vuelve a autorizar la cuenta."
            ) from exc

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "version": 1,
            "tokens": _model_dump(self.tokens) if self.tokens else None,
            "client_info": _model_dump(self.client_info) if self.client_info else None,
        }
        encrypted = self.protector.protect(
            json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)
