"""FastAPI dependencies for the unified external portal.

A single ``require_unified_portal_session`` dependency resolves the caller's
role and accessible claims from whichever credential they present:

1. **Unified token** (``X-Portal-Token`` header) – new ``external_portal_tokens``
   table; carries explicit ``role`` + ``scopes``.  Preferred for new integrations.

2. **Repair shop per-claim token** (``X-Repair-Shop-Access-Token`` header) –
   legacy; role is inferred as ``repair_shop``.

3. **Claimant access token** (``X-Claim-Access-Token`` header) –
   legacy; role is inferred as ``claimant``.

4. **Policy + VIN** (``X-Policy-Number`` + ``X-Vin`` headers) – legacy claimant
   mode; role is inferred as ``claimant``.

5. **Email** (``X-Email`` header) – legacy claimant mode when
   ``DSAR_VERIFICATION_REQUIRED=false``; role is ``claimant``.

The ``role`` field in :class:`UnifiedPortalSession` lets callers gate features
without having to inspect which legacy headers were sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request

from claim_agent.config import get_settings
from claim_agent.services.portal_verification import get_claim_ids_for_claimant
from claim_agent.services.repair_shop_portal_tokens import verify_repair_shop_token
from claim_agent.services.unified_portal_tokens import verify_unified_portal_token


@dataclass
class UnifiedPortalSession:
    """Verified external-portal session with explicit role.

    Attributes:
        role: The portal role resolved from the credential (``claimant``,
            ``repair_shop``, or ``tpa``).
        claim_ids: Claims this session can access.  For repair-shop per-claim
            tokens this is a single-element list; for claimant tokens it may
            contain multiple claims.
        shop_id: Shop identifier resolved from a repair-shop credential;
            ``None`` for claimant/tpa roles.
        scopes: Fine-grained permission strings from a unified token (empty
            list for legacy tokens – callers should treat an empty list as
            "full legacy access" for the resolved role).
        identity: Human-readable identity string for audit logs.
    """

    role: str
    claim_ids: list[str]
    shop_id: str | None
    scopes: list[str] = field(default_factory=list)
    identity: str = "portal"


async def require_unified_portal_session(request: Request) -> UnifiedPortalSession:
    """Dependency: resolve role + claim access from any presented credential.

    Raises HTTP 401 when no valid credential is found.
    Raises HTTP 503 when the relevant portal feature is disabled.
    """
    # --- 1. Unified token (X-Portal-Token) --------------------------------
    unified_raw = (request.headers.get("x-portal-token") or "").strip()
    if unified_raw:
        rec = verify_unified_portal_token(unified_raw)
        if rec is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired portal token.",
            )
        settings = get_settings()
        if rec.role == "claimant":
            if not settings.portal.enabled:
                raise HTTPException(status_code=503, detail="Claimant portal is disabled")
        elif rec.role == "repair_shop":
            if not settings.repair_shop_portal.enabled:
                raise HTTPException(status_code=503, detail="Repair shop portal is disabled")
        elif rec.role == "tpa":
            if not settings.third_party_portal.enabled:
                raise HTTPException(status_code=503, detail="Third-party portal is disabled")

        if not rec.claim_id:
            raise HTTPException(
                status_code=401,
                detail="Unified portal tokens must specify a claim_id.",
            )
        claim_ids = [rec.claim_id]
        return UnifiedPortalSession(
            role=rec.role,
            claim_ids=claim_ids,
            shop_id=rec.shop_id,
            scopes=rec.scopes,
            identity=f"unified-token:{rec.token_id}",
        )

    # --- 2. Repair shop per-claim token (X-Repair-Shop-Access-Token) -------
    shop_raw = (request.headers.get("x-repair-shop-access-token") or "").strip()
    claim_id_hint = (request.headers.get("x-claim-id") or "").strip() or None
    if shop_raw and claim_id_hint:
        settings = get_settings()
        if not settings.repair_shop_portal.enabled:
            raise HTTPException(status_code=503, detail="Repair shop portal is disabled")
        rec_shop = verify_repair_shop_token(claim_id_hint, shop_raw)
        if rec_shop is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired access. Provide X-Repair-Shop-Access-Token.",
            )
        return UnifiedPortalSession(
            role="repair_shop",
            claim_ids=[rec_shop.claim_id],
            shop_id=rec_shop.shop_id,
            identity=rec_shop.shop_id or f"repair-portal-token:{rec_shop.token_id}",
        )

    # --- 3–5. Claimant credentials (legacy portal session) ----------------
    token = (request.headers.get("x-claim-access-token") or "").strip() or None
    pn = (request.headers.get("x-policy-number") or "").strip() or None
    vin = (request.headers.get("x-vin") or "").strip() or None
    email = (request.headers.get("x-email") or "").strip() or None

    if token or (pn and vin) or email:
        settings = get_settings()
        if not settings.portal.enabled:
            raise HTTPException(status_code=503, detail="Claimant portal is disabled")
        ids = get_claim_ids_for_claimant(
            token=token,
            policy_number=pn,
            vin=vin,
            email=email,
        )
        if ids:
            identity: str = (
                email
                or (pn and f"policy:{pn[:4]}***")
                or "portal-claimant"
            )
            return UnifiedPortalSession(
                role="claimant",
                claim_ids=ids,
                shop_id=None,
                identity=identity,
            )

    raise HTTPException(
        status_code=401,
        detail=(
            "Authentication required. Provide X-Portal-Token, X-Repair-Shop-Access-Token, "
            "X-Claim-Access-Token, or policy/VIN credentials."
        ),
    )


def require_portal_scopes(*required: str):
    """Build a FastAPI dependency that enforces unified-token scopes.

    Legacy sessions (empty ``scopes``) retain full access for the resolved role.
    When ``scopes`` is non-empty, the caller must hold every scope in *required*.

    Usage::

        @router.post("/example")
        def example(session: UnifiedPortalSession = Depends(require_portal_scopes("upload_doc"))):
            ...
    """

    required_set = frozenset(required)

    async def _dep(session: UnifiedPortalSession = Depends(require_unified_portal_session)) -> UnifiedPortalSession:
        if not session.scopes:
            return session
        missing = sorted(required_set - set(session.scopes))
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Missing required portal scope(s): {missing}",
            )
        return session

    return _dep
