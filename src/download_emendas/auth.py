from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from typing import Any


@dataclass(frozen=True)
class StoredToken:
    label: str
    token_hash: str
    created_at_utc: str | None = None


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    return secrets.token_urlsafe(24)


class AccessTokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: tuple[int | None, list[StoredToken]] | None = None

    def load(self) -> list[StoredToken]:
        if not self.path.exists():
            return []

        version = self.path.stat().st_mtime_ns
        if self._cache and self._cache[0] == version:
            return self._cache[1]

        payload = json.loads(self.path.read_text(encoding="utf-8"))
        tokens = [
            StoredToken(
                label=str(entry.get("label", "token")),
                token_hash=str(entry["token_hash"]),
                created_at_utc=entry.get("created_at_utc"),
            )
            for entry in payload.get("tokens", [])
            if entry.get("token_hash")
        ]
        self._cache = (version, tokens)
        return tokens

    def verify(self, raw_token: str | None) -> bool:
        if not raw_token:
            return False

        hashed = hash_token(raw_token.strip())
        return any(hmac.compare_digest(token.token_hash, hashed) for token in self.load())

    def add(self, label: str, raw_token: str) -> StoredToken:
        token = StoredToken(
            label=label,
            token_hash=hash_token(raw_token),
            created_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        tokens = self.load()
        payload = {
            "tokens": [
                {
                    "label": item.label,
                    "token_hash": item.token_hash,
                    "created_at_utc": item.created_at_utc,
                }
                for item in [*tokens, token]
            ]
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._cache = None
        return token

    def export_payload(self) -> dict[str, Any]:
        return {
            "tokens": [
                {
                    "label": token.label,
                    "token_hash": token.token_hash,
                    "created_at_utc": token.created_at_utc,
                }
                for token in self.load()
            ]
        }
