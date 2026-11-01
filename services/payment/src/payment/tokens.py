"""Card tokenization with a local cache, so repeat customers skip the vault round trip."""

import hashlib
import time
import uuid
from dataclasses import dataclass

TOKEN_TTL_S = 900


@dataclass(frozen=True)
class Token:
    id: str
    last4: str
    created_at: float


class InvalidTokenError(Exception):
    pass


class TokenCache:
    """`mode` selects the cache key: "v1" per card, "v2" per issuer prefix (fewer vault calls)."""

    def __init__(self, mode: str = "v1") -> None:
        self.mode = mode
        self._tokens: dict[str, Token] = {}

    def _key(self, number: str) -> str:
        material = number[:6] if self.mode == "v2" else number
        return hashlib.sha256(material.encode()).hexdigest()

    def token_for(self, number: str, now: float | None = None) -> Token:
        now = time.time() if now is None else now
        key = self._key(number)
        token = self._tokens.get(key)
        if token is None or now - token.created_at > TOKEN_TTL_S:
            token = Token(id=f"tok_{uuid.uuid4().hex[:16]}", last4=number[-4:], created_at=now)
            self._tokens[key] = token
        return token


def verify(token: Token, number: str) -> None:
    if token.last4 != number[-4:]:
        raise InvalidTokenError(f"invalid token {token.id} for card ending {number[-4:]}")
