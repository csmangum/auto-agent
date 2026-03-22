"""Vision model logic for damage photo analysis."""

import base64
import json
import logging
import os
import re
from typing import Any
from urllib.parse import unquote, urlparse

import litellm

from claim_agent.adapters.registry import get_reverse_image_adapter
from claim_agent.config import get_settings
from claim_agent.config.settings import (
    get_adapter_backend,
    get_fraud_config,
    get_mock_crew_config,
    get_mock_image_config,
)
from claim_agent.mock_crew.vision_mock import analyze_damage_photo_mock
from claim_agent.observability.logger import get_current_claim_log_context
from claim_agent.utils.image_metadata import analyze_photo_forensics, extract_exif_metadata

logger = logging.getLogger(__name__)

MAX_VISION_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


def _effective_claim_context(claim_context: dict[str, Any] | None) -> dict[str, Any]:
    """Merge explicit claim_context with thread-local workflow context (explicit wins)."""
    return {**get_current_claim_log_context(), **(claim_context or {})}


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
        return analyze_damage_photo_mock(
            image_url, damage_description, _effective_claim_context(claim_context)
        )

    result: dict[str, Any] = {
        "severity": "unknown",
        "parts_affected": [],
        "consistency_with_description": "unknown",
        "notes": "",
        "photo_forensics": {"anomalies": [], "metadata": {}},
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
                exif_metadata = extract_exif_metadata(path)
                eff = _effective_claim_context(claim_context)
                fraud_cfg = get_fraud_config()
                result["photo_forensics"] = analyze_photo_forensics(
                    exif_metadata,
                    incident_date=eff.get("incident_date"),
                    incident_latitude=eff.get("incident_latitude"),
                    incident_longitude=eff.get("incident_longitude"),
                    photo_gps_incident_max_distance=float(
                        fraud_cfg.get("photo_gps_incident_max_distance", 50.0)
                    ),
                    photo_gps_incident_distance_unit=str(
                        fraud_cfg.get("photo_gps_incident_distance_unit", "miles")
                    ),
                )
                with open(path, "rb") as f:
                    _image_bytes = f.read()
                # Optional reverse-image / stock-photo check (feature-flagged).
                # Default is ``mock`` (deterministic, no network). Set
                # ``REVERSE_IMAGE_ADAPTER=stub`` to skip this block so we never call
                # the stub (which raises NotImplementedError) and FNOL stays unblocked.
                if get_adapter_backend("reverse_image") != "stub":
                    try:
                        ri_adapter = get_reverse_image_adapter()
                        web_matches = ri_adapter.match_web_occurrences(_image_bytes)
                        result["photo_forensics"]["reverse_image_matches"] = web_matches
                        if web_matches:
                            top_score = max(
                                (m.get("match_score", 0) for m in web_matches), default=0
                            )
                            if top_score >= 0.8:
                                result["photo_forensics"]["anomalies"] = list(
                                    result["photo_forensics"].get("anomalies", [])
                                ) + ["reverse_image_stock_photo_match"]
                    except Exception:
                        logger.warning(
                            "Reverse-image lookup failed; continuing without it",
                            exc_info=True,
                        )
                b64 = base64.b64encode(_image_bytes).decode("ascii")
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
            result.update({k: v for k, v in parsed.items() if k in result and k != "photo_forensics"})
        else:
            result["notes"] = text[:500]
    except Exception as e:
        logger.warning("Vision analysis failed: %s", e, exc_info=True)
        result["error"] = str(e)

    return json.dumps(result)
