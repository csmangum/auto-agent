"""Download Florida corpus sources (Florida Statutes).

Per docs/compliance-corpus-requirements.md Section 2.2:
- FS §626.9541 (unfair claims)
- FS §627.730-7405 (No-Fault/PIP)
- FS §319.30 (total loss)
- FS §627.4265, 627.426, 627.70131 (deadlines)
- FS §627.7263, 626.9743, 627.7288 (disclosures)
- FS §627.727 (UM/UIM)
- FS §817.234, 626.989, 626.9891 (fraud)
- FS §501.976 (aftermarket parts)
- FL Admin Code 69O-166
"""

import logging
from pathlib import Path

from .config import FL_SOURCES, OUTPUT_DIR
from .downloader import download_to_dir

logger = logging.getLogger(__name__)


def download_florida(output_dir: Path | None = None) -> list[Path]:
    """Download Florida statutory sources. Returns list of successfully downloaded paths."""
    out = output_dir or Path.cwd() / OUTPUT_DIR
    fl_dir = out / "florida"
    fl_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for src in FL_SOURCES:
        url = src["url"]
        fid = src["id"]
        ext = ".zip" if src.get("format") == "zip" else ""
        filename = f"{fid}{ext}" if ext else None
        path = download_to_dir(url, fl_dir, filename=filename)
        if path:
            results.append(path)

    # FL Admin Code 69O-166 - typically at flrules.org; add note
    admin_note = fl_dir / "FL_Admin_Code_69O-166_README.txt"
    admin_note.write_text(
        "Florida Administrative Code - 69O-166 (Insurance)\n\n"
        "Available at: https://www.flrules.org/\n"
        "Relevant: 69O-166 (total loss, salvage).\n",
        encoding="utf-8",
    )
    logger.info("Wrote FL Admin Code note to %s", admin_note)
    results.append(admin_note)

    return results
