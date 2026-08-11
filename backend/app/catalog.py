from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_accents)


@dataclass(frozen=True)
class CatalogUser:
    display_name: str
    email: str
    account_id: str
    aliases: tuple[str, ...] = ()
    active: bool = True


class FakeAssigneeCatalog:
    def __init__(self, users: tuple[CatalogUser, ...] | None = None):
        self.users = users or DEFAULT_USERS

    def resolve(self, captured_name: str) -> dict[str, str | None]:
        normalized = normalize_name(captured_name)
        candidates = []
        for user in self.users:
            names = (user.display_name, *user.aliases)
            if normalized in {normalize_name(name) for name in names}:
                candidates.append(user)

        if len(candidates) > 1:
            return {
                "display_name": captured_name.strip(),
                "email": None,
                "account_id": None,
                "resolution": "AMBIGUOUS",
            }
        if not candidates:
            return {
                "display_name": captured_name.strip(),
                "email": None,
                "account_id": None,
                "resolution": "NOT_FOUND",
            }
        user = candidates[0]
        if not user.active:
            resolution = "INACTIVE"
        else:
            resolution = "RESOLVED"
        return {
            "display_name": user.display_name,
            "email": user.email,
            "account_id": user.account_id,
            "resolution": resolution,
        }

    def get_by_account_id(self, account_id: str) -> dict[str, str | None] | None:
        user = next((candidate for candidate in self.users if candidate.account_id == account_id), None)
        if user is None:
            return None
        return {
            "display_name": user.display_name,
            "email": user.email,
            "account_id": user.account_id,
            "resolution": "RESOLVED" if user.active else "INACTIVE",
        }

    def list_users(self) -> list[dict[str, str | bool]]:
        return [
            {
                "display_name": user.display_name,
                "email": user.email,
                "account_id": user.account_id,
                "active": user.active,
            }
            for user in self.users
        ]


DEFAULT_USERS = (
    CatalogUser(
        "Giselle Bello",
        "giselle.bello@example.com",
        "local-account-giselle",
        ("Giselle",),
    ),
    CatalogUser(
        "Wilfrido Hernández",
        "wilfrido.hernandez@example.com",
        "local-account-wilfrido",
        ("Wilfrido",),
    ),
    CatalogUser(
        "José Martínez",
        "jose.martinez@example.com",
        "local-account-jose",
        ("José", "Jose"),
    ),
    CatalogUser(
        "Benjamín Blanco",
        "benjamin.blanco@example.com",
        "local-account-benjamin",
        ("Benjamin Blanco",),
    ),
    CatalogUser(
        "Alfredo Aguilera",
        "alfredo.aguilera@example.com",
        "local-account-alfredo",
    ),
    CatalogUser(
        "Lorena Salazar",
        "lorena.salazar@example.com",
        "local-account-lorena",
    ),
    CatalogUser(
        "Raúl Gallardo",
        "raul.gallardo@example.com",
        "local-account-raul",
        ("Raul Gallardo", "Sistemas Raúl Gallardo"),
    ),
    CatalogUser(
        "Alejandro Pablo",
        "alejandro.pablo@example.com",
        "local-account-alejandro",
    ),
    CatalogUser(
        "Vicente Martínez",
        "vicente.martinez@example.com",
        "local-account-vicente",
        ("Vicente Martínez Alejandro Pablo",),
    ),
)
