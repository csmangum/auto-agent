"""Download federal corpus sources (USC, CFR).

Per docs/compliance-corpus-requirements.md Section 3:
- HIPAA (45 CFR 160, 164), HITECH (42 USC 17931-17940)
- GLBA (15 USC 6801-6809), Reg P (12 CFR 1016)
- FCRA (15 USC 1681), FDCPA (15 USC 1692)
- Medicare MSP (42 USC 1395y(b)), MMSEA Section 111
- 18 USC 1033-1034 (insurance fraud)
- NMVTIS (49 USC 30502, 28 CFR Part 25)
- ESIGN (15 USC 7001)
"""

import logging
import time
from pathlib import Path

from .config import FEDERAL_SOURCES, OUTPUT_DIR
from .downloader import LARGE_FILE_TIMEOUT, download_file, download_to_dir

logger = logging.getLogger(__name__)

# CMS Medicare - no bulk API; manual or scrape
CMS_MSP_URL = "https://www.cms.gov/medicare-coordination-benefits-recovery"
CMS_SECTION_111_URL = "https://www.cms.gov/medicare-coordination-benefits-recovery/mandatory-insurance-reporting"

# Retry settings for transient network errors on large files
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF = 5.0  # seconds between retries


def _download_with_retry(url: str, dest_path: Path, timeout: float, max_attempts: int = _RETRY_ATTEMPTS) -> Path | None:
    """Download a file with retry/backoff on transient failures. Returns path or None."""
    for attempt in range(1, max_attempts + 1):
        if download_file(url, dest_path, timeout=timeout):
            return dest_path
        if attempt < max_attempts:
            wait = _RETRY_BACKOFF * attempt
            logger.warning("Attempt %d/%d failed for %s; retrying in %.0fs", attempt, max_attempts, url, wait)
            time.sleep(wait)
    logger.error("All %d attempts failed for %s", max_attempts, url)
    return None


def download_federal(output_dir: Path | None = None) -> list[Path]:
    """Download federal statutory and regulatory sources. Returns list of downloaded paths."""
    out = output_dir or Path.cwd() / OUTPUT_DIR
    fed_dir = out / "federal"
    fed_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for src in FEDERAL_SOURCES:
        url = src["url"]
        fid = src["id"]
        fmt = src.get("format", "xml")
        ext = ".zip" if fmt == "zip" else ".xml"
        dest = fed_dir / f"{fid}{ext}"
        if fid == "cfr_title_45":
            path = _download_with_retry(url, dest, timeout=LARGE_FILE_TIMEOUT)
        else:
            path = download_to_dir(url, fed_dir, filename=f"{fid}{ext}")
        if path:
            results.append(path)

    # CMS Medicare - no bulk download; add acquisition note
    cms_note = fed_dir / "CMS_Medicare_README.txt"
    cms_note.write_text(
        "CMS Medicare Secondary Payer (MSP) & Section 111\n\n"
        "Sources:\n"
        f"- {CMS_MSP_URL}\n"
        f"- {CMS_SECTION_111_URL}\n\n"
        "Relevant: MSP conditional payment recovery, MMSEA Section 111 reporting, "
        "MSA guidelines.\n",
        encoding="utf-8",
    )
    results.append(cms_note)

    return results
