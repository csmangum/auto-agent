"""Shared download logic for corpus sources."""

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Default timeout for large file downloads (seconds)
DOWNLOAD_TIMEOUT = 300.0
# Extended timeout for very large files (e.g. CFR Title 45)
LARGE_FILE_TIMEOUT = 600.0


def download_file(
    url: str,
    dest_path: Path,
    *,
    timeout: float = DOWNLOAD_TIMEOUT,
    user_agent: str = "ClaimAgent-CorpusDownloader/1.0 (compliance research)",
) -> bool:
    """Download a file from URL to dest_path. Returns True on success."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": user_agent}
    try:
        with httpx.stream("GET", url, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=65536):
                    f.write(chunk)
        logger.info("Downloaded %s -> %s", url, dest_path)
        return True
    except httpx.HTTPStatusError as e:
        logger.error("HTTP %s for %s: %s", e.response.status_code, url, e)
        return False
    except httpx.RequestError as e:
        logger.error("Request failed for %s: %s", url, e)
        return False
    except OSError as e:
        logger.error("Write failed for %s: %s", dest_path, e)
        return False


def download_to_dir(
    url: str,
    output_dir: Path,
    filename: str | None = None,
    *,
    timeout: float = DOWNLOAD_TIMEOUT,
) -> Path | None:
    """Download URL to output_dir. Uses filename from URL if not provided. Returns path or None."""
    if filename is None:
        filename = url.split("/")[-1].split("?")[0] or "download"
    dest = output_dir / filename
    if download_file(url, dest, timeout=timeout):
        return dest
    return None
