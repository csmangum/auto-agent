"""Download New York corpus sources (NYIL, 11 NYCRR).

Per docs/compliance-corpus-requirements.md Section 2.3:
- NY Insurance Law (NYIL) §2601, Article 51, §3411, §3420(f), §2610, §5102, §5104, §5106
- 11 NYCRR 216 (Regulation 64), 60-2 (Reg 35-D), 65-4 (Reg 68)
- NY Penal Law §176.05-176.30
- CPLR §1411, §214, §213, §4545
"""

import logging
from pathlib import Path

from .config import OUTPUT_DIR
from .downloader import download_file

logger = logging.getLogger(__name__)

# NY Senate blocks programmatic access (403). Use newyork.public.law as fallback.
NY_ARTICLE_URLS = [
    # (article_id, primary_url, fallback_url)
    ("A26", "https://www.nysenate.gov/legislation/laws/ISC/A26", "https://newyork.public.law/laws/n.y._insurance_law_article_26"),
    ("A34", "https://www.nysenate.gov/legislation/laws/ISC/A34", "https://newyork.public.law/laws/n.y._insurance_law_article_34"),
    ("A51", "https://www.nysenate.gov/legislation/laws/ISC/A51", "https://newyork.public.law/laws/n.y._insurance_law_article_51"),
]


def _fetch_ny_article(article_id: str, primary_url: str, fallback_url: str, output_dir: Path) -> Path | None:
    """Fetch a NY Insurance Law article. Tries primary, then fallback. Returns path or None."""
    dest = output_dir / f"NYIL_{article_id}.html"
    if download_file(primary_url, dest):
        return dest
    if download_file(fallback_url, dest):
        return dest
    return None


def download_new_york(output_dir: Path | None = None) -> list[Path]:
    """Download New York statutory sources. Returns list of successfully downloaded paths."""
    out = output_dir or Path.cwd() / OUTPUT_DIR
    ny_dir = out / "new_york"
    ny_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []

    for article_id, primary_url, fallback_url in NY_ARTICLE_URLS:
        path = _fetch_ny_article(article_id, primary_url, fallback_url, ny_dir)
        if path:
            results.append(path)

    # 11 NYCRR - NY DFS maintains selected regulations; full CRR at westlaw/ecfr
    crr_note = ny_dir / "11_NYCRR_README.txt"
    crr_note.write_text(
        "11 NYCRR (NY Compilation of Codes, Rules and Regulations)\n\n"
        "Relevant for auto compliance:\n"
        "- 11 NYCRR 216 (Regulation 64 - Unfair Claims Settlement)\n"
        "- 11 NYCRR 60-2 (Regulation 35-D - UM/SUM)\n"
        "- 11 NYCRR 65-4 (Regulation 68 - No-Fault)\n"
        "- 11 NYCRR 216.7 (total loss settlement)\n\n"
        "Sources: NY DFS (dfs.ny.gov), Westlaw NYCRR, or NY State Register.\n",
        encoding="utf-8",
    )
    results.append(crr_note)

    return results
