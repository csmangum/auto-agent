"""Vision model logic for damage photo analysis."""

import base64
import json
import logging
import os
import re
from typing import Any
from urllib.parse import unquote, urlparse

import litellm

from claim_agent.config import get_settings
from claim_agent.config.settings import get_adapter_backend, get_mock_crew_config, get_mock_image_config
from claim_agent.mock_crew.vision_mock import analyze_damage_photo_mock

logger = logging.getLogger(__name__)

MAX_VISION_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


def _use_mock_vision() -> bool:
    """Return True if mock vision analysis should be used (no API call)."""
    if get_adapter_backend("vision") == "mock":
        return True
    crew_cfg = get_mock_crew_config()
    img_cfg = get_mock_image_config()
    return (
        crew_cfg.get("enabled") is True
        and img_cfg.get("vision_analysis_source") == "claim_context"
    )


def analyze_damage_photo_impl(
    image_url: str,
    damage_description: str | None = None,
    claim_context: dict[str, Any] | None = None,
) -> str:
    """Analyze a damage photo using a vision model or mock (claim-context derived)."""
    if _use_mock_vision():
        return analyze_damage_photo_mock(image_url, damage_description, claim_context)

    result: dict[str, Any] = {
        "severity": "unknown",
        "parts_affected": [],
        "consistency_with_description": "unknown",
        "notes": "",
        "error": None,
    }

    content_for_vision = image_url
    if image_url.startswith("file://"):
        try:
            path = os.path.realpath(unquote(urlparse(image_url).path))
            allowed_base = os.path.realpath(
                get_settings().paths.attachment_storage_path
            )
            if not path.startswith(allowed_base + os.sep) and path != allowed_base:
                result["error"] = "Access to this file path is not permitted"
                return json.dumps(result)
            if os.path.isfile(path):
                file_size = os.path.getsize(path)
                if file_size > MAX_VISION_FILE_BYTES:
                    result["error"] = f"File size ({file_size} bytes) exceeds the limit for vision analysis"
                    return json.dumps(result)
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                ext = path.rsplit(".", 1)[-1].lower() if "." in path else "jpg"
                mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}" if ext in ("png", "gif", "webp") else "image/jpeg"
                content_for_vision = f"data:{mime};base64,{b64}"
            else:
                result["error"] = "File not found"
                return json.dumps(result)
        except Exception as e:
            result["error"] = str(e)
            return json.dumps(result)

    try:
        model = get_settings().llm.vision_model.strip() or "gpt-4o"
        prompt = """Analyze this vehicle damage photo. Return a JSON object with:
- severity: "low" | "medium" | "high" | "total_loss"
- parts_affected: list of damaged parts (e.g. bumper, fender, door)
- consistency_with_description: "consistent" | "inconsistent" | "unknown" (if no description provided)
- notes: brief assessment"""
        if damage_description:
            prompt += f"\n\nClaimant's damage description: {damage_description}"
        else:
            prompt += "\n\nNo text description provided."

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": content_for_vision}},
                ],
            }
        ]
        resp = litellm.completion(model=model, messages=messages)
        text = resp.choices[0].message.content or ""
        # Flat JSON only; nested objects would require a more robust extractor
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            result.update({k: v for k, v in parsed.items() if k in result})
        else:
            result["notes"] = text[:500]
    except Exception as e:
        logger.warning("Vision analysis failed: %s", e, exc_info=True)
        result["error"] = str(e)

    return json.dumps(result)
