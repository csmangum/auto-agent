"""Authentication: API key lookup and JWT verification."""

import hashlib
import hmac
import logging
from dataclasses import dataclass

from claim_agent.config.settings import get_api_key_entries, get_jwt_secret
from claim_agent.rbac_roles import KNOWN_ROLES

logger = logging.getLogger(__name__)


@dataclass
class AuthContext:
    """Authenticated identity and role."""

    identity: str
    role: str


def _key_identity(key: str) -> str:
    """Stable identity for API key (hash prefix) for audit without exposing full key."""
    return "key-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _api_key_digest(key: str) -> bytes:
    """SHA-256 digest for timing-safe comparison (avoids short-circuit string equality)."""
    return hashlib.sha256(key.encode()).digest()


def verify_token(token: str) -> AuthContext | None:
    """Verify token and return AuthContext if valid. None if invalid."""

    if not token:
        return None

    token = token.strip()
    if not token:
        return None

    # API key lookup (timing-safe: compare SHA-256 digests with hmac.compare_digest)
    api_entries = get_api_key_entries()
    token_digest = _api_key_digest(token)
    for stored_key, entry in api_entries.items():
        if hmac.compare_digest(token_digest, _api_key_digest(stored_key)):
            ident = entry.identity if entry.identity else _key_identity(token)
            return AuthContext(identity=ident, role=entry.role)

    # JWT verification (optional)
    jwt_secret = get_jwt_secret()
    if jwt_secret:
        try:
            import jwt as pyjwt
        except ImportError:
            logger.warning(
                "JWT_SECRET is set but PyJWT is not installed. "
                "Install with: pip install 'claim-agent[jwt]' or pip install PyJWT"
            )
            return None
        try:
            payload = pyjwt.decode(token, jwt_secret, algorithms=["HS256"])
            token_use = payload.get("token_use")
            if token_use == "refresh":
                return None
            sub = payload.get("sub")
            role = str(payload.get("role", "adjuster"))
            if role not in KNOWN_ROLES:
                logger.debug("JWT role %r not in known roles %s", role, sorted(KNOWN_ROLES))
                return None
            if sub:
                return AuthContext(identity=str(sub), role=role)
        except Exception:
            return None

    return None


def is_auth_required() -> bool:
    """True if any auth config is set (API_KEYS, CLAIMS_API_KEY, or JWT_SECRET)."""
    return bool(get_api_key_entries() or get_jwt_secret())
