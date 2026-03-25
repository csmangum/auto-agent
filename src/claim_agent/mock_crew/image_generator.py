"""Image generation for mock claim damage photos via OpenRouter."""

import base64
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, cast

import httpx

from claim_agent.config import get_settings

logger = logging.getLogger(__name__)

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_PLACEHOLDER_KEYS = frozenset(
    {"", "your_openrouter_key", "your_openai_key", "your-key-here", "your-key"}
)


def _get_api_key() -> str:
    """Get API key for OpenRouter (OPENAI_API_KEY or OPENROUTER_API_KEY)."""
    llm = get_settings().llm
    api_key = (llm.api_key.get_secret_value() or "").strip()
    if not api_key or api_key in _PLACEHOLDER_KEYS:
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    return api_key


def _build_prompt(claim_context: dict[str, Any]) -> str:
    """Build image generation prompt from claim context."""
    year = claim_context.get("vehicle_year", "")
    make = claim_context.get("vehicle_make", "")
    model = claim_context.get("vehicle_model", "")
    damage = claim_context.get("damage_description", "vehicle damage")
    incident = claim_context.get("incident_description", "accident")

    return f"""Generate a single realistic photo of vehicle damage for an insurance claim.

Vehicle: {year} {make} {model}
Damage description: {damage}
Incident: {incident}

Style: Single clear photo, daylight, showing the damaged area. No text or watermarks. Photorealistic."""


def _extract_base64_from_response(data: dict[str, Any]) -> str | None:
    """Extract base64 data URL from OpenRouter image generation response.

    Handles multiple response formats:
    - message.images[].imageUrl.url (OpenRouter docs)
    - choices[0].message.content[] with type image_url
    """
    try:
        choices = data.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}

        # Format 1: message.images
        images = msg.get("images") or []
        for img in images:
            url = (img.get("imageUrl") or img.get("image_url") or {}).get(
                "url", img.get("url", "")
            )
            if url and isinstance(url, str) and url.startswith("data:"):
                return cast(str, url)

        # Format 2: message.content (array of parts)
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    url = (
                        part.get("image_url") or part.get("imageUrl") or {}
                    ).get("url", part.get("url", ""))
                    if url and isinstance(url, str) and url.startswith("data:"):
                        return cast(str, url)
        elif isinstance(content, str) and "data:image" in content:
            # Some models return inline base64 in text
            match = re.search(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", content)
            if match:
                return match.group(0)

        return None
    except (KeyError, TypeError, IndexError):
        return None


def _save_image_from_data_url(data_url: str, out_path: Path) -> None:
    """Decode base64 data URL and save to file."""
    if ";base64," not in data_url:
        raise ValueError("Invalid data URL: missing base64 payload")
    b64 = data_url.split(";base64,", 1)[1]
    raw = base64.b64decode(b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)


def _create_placeholder_image(out_path: Path, claim_context: dict[str, Any]) -> None:
    """Create a minimal placeholder PNG (1x1 black pixel) when API fails."""
    # Minimal valid PNG: 1x1 black pixel (67 bytes)
    placeholder = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010100000000376ef9"
        "240000000a4944415478016360000000020001737501180000000049454e44ae"
        "426082"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(placeholder)


def generate_damage_image(
    claim_context: dict[str, Any],
    *,
    claim_id: str | None = None,
    fallback_on_error: bool = True,
) -> str:
    """Generate a damage photo for a claim via OpenRouter and save to attachment storage.

    Args:
        claim_context: Dict with vehicle_year, vehicle_make, vehicle_model,
            damage_description, incident_description (or equivalent keys).
        claim_id: Optional claim ID for filename (used when seed not set).
        fallback_on_error: If True, return placeholder image when API fails.

    Returns:
        file:// URL to the saved image.

    Raises:
        ValueError: If API key is missing, generator is disabled, or API fails
            (and fallback_on_error is False).
    """
    cfg = get_settings().mock_image
    if not cfg.generator_enabled:
        raise ValueError(
            "Mock image generator is disabled. Set MOCK_IMAGE_GENERATOR_ENABLED=true."
        )

    # Determine output path (and check cache when seed is set)
    base = get_settings().get_attachment_storage_base_path()

    seed = get_settings().mock_crew.seed
    if seed is not None:
        ctx_str = json.dumps(claim_context, sort_keys=True)
        h = hashlib.sha256(f"{ctx_str}:{seed}".encode()).hexdigest()[:12]
        filename = f"mock_damage_{h}.png"
    elif claim_id:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(claim_id))
        filename = f"mock_damage_{safe_id}_{uuid.uuid4().hex[:8]}.png"
    else:
        filename = f"mock_damage_{uuid.uuid4().hex[:8]}.png"

    out_path = base / "mock_generated" / filename

    # Cache hit: when seed is set, return existing file if present
    if seed is not None and out_path.exists():
        return f"file://{out_path.resolve()}"

    api_key = _get_api_key()
    if not api_key or api_key in _PLACEHOLDER_KEYS:
        if fallback_on_error:
            logger.warning("No API key for image generation; using placeholder")
            _create_placeholder_image(out_path, claim_context)
            return f"file://{out_path.resolve()}"
        raise ValueError(
            "OPENAI_API_KEY or OPENROUTER_API_KEY required for image generation. "
            "Replace placeholder values with a real key."
        )

    prompt = _build_prompt(claim_context)
    model = cfg.model.strip() or "google/gemini-2.0-flash-exp"

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/claim-agent",
    }

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{_OPENROUTER_BASE}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        if fallback_on_error:
            logger.warning("OpenRouter image generation failed: %s; using placeholder", e)
            _create_placeholder_image(out_path, claim_context)
            return f"file://{out_path.resolve()}"
        logger.warning("OpenRouter image generation failed: %s", e)
        raise ValueError(f"OpenRouter image generation failed: {e}") from e

    data_url = _extract_base64_from_response(data)
    if not data_url:
        if fallback_on_error:
            logger.warning("No image in OpenRouter response; using placeholder")
            _create_placeholder_image(out_path, claim_context)
            return f"file://{out_path.resolve()}"
        logger.warning("No image in OpenRouter response: %s", json.dumps(data)[:500])
        raise ValueError("OpenRouter did not return an image in the response")

    _save_image_from_data_url(data_url, out_path)

    return f"file://{out_path.resolve()}"
