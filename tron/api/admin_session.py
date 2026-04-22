"""Browser admin UI session (JWT in httpOnly cookie), separate from X-API-Key automation."""

from __future__ import annotations

import time
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError

ADMIN_COOKIE_NAME = "tron_admin_sess"
ADMIN_JWT_TYP = "tron_admin"


def issue_admin_jwt(secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "typ": ADMIN_JWT_TYP,
        "sub": "admin",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_admin_jwt(token: str, secret: str) -> bool:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("typ") == ADMIN_JWT_TYP and payload.get("sub") == "admin"
    except InvalidTokenError:
        return False
