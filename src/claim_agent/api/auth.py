"""Authentication: API key lookup and JWT verification."""

import hashlib
from dataclasses import dataclass

from claim_agent.config.settings import get_api_keys_config, get_jwt_secret


@dataclass
class AuthContext:
    """Authenticated identity and role."""

    identity: str
    role: str


def _key_identity(key: str) -> str:
    """Stable identity for API key (hash prefix) for audit without exposing full key."""
    return "key-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def verify_token(token: str) -> AuthContext | None:
    """Verify token and return AuthContext if valid. None if invalid."""

    if not token:
        return None

    token = token.strip()
    if not token:
        return None

    # API key lookup
    api_keys = get_api_keys_config()
    if token in api_keys:
        return AuthContext(identity=_key_identity(token), role=api_keys[token])

    # JWT verification (optional)
    jwt_secret = get_jwt_secret()
    if jwt_secret:
        try:
            import jwt as pyjwt
        except ImportError:
            return None
        try:
            payload = pyjwt.decode(token, jwt_secret, algorithms=["HS256"])
            sub = payload.get("sub")
            role = payload.get("role", "adjuster")
            if sub:
                return AuthContext(identity=str(sub), role=str(role))
        except Exception:
            return None

    return None


def is_auth_required() -> bool:
    """True if any auth config is set (API_KEYS, CLAIMS_API_KEY, or JWT_SECRET)."""
    return bool(get_api_keys_config() or get_jwt_secret())
