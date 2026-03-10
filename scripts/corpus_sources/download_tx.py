"""Download Texas corpus sources (TIC, CPRC, Penal Code).

Per docs/compliance-corpus-requirements.md Section 2.1:
- Texas Insurance Code (TIC) Ch 542, 701, §2301.009, §1952.301-304, §541.060, §542.014
- 28 TAC §5.4001-5.4104 (requires manual/API request - see config TX_TAC_NOTE)
- Texas Civil Practice & Remedies Code §33.001-017, §16.003-004
- Texas Penal Code §35.02
"""

import logging
from pathlib import Path

from .config import OUTPUT_DIR, TX_SOURCES, TX_TAC_NOTE
from .downloader import download_to_dir

logger = logging.getLogger(__name__)


def download_texas(output_dir: Path | None = None) -> list[Path]:
    """Download Texas statutory sources. Returns list of successfully downloaded paths."""
    out = output_dir or Path.cwd() / OUTPUT_DIR
    tx_dir = out / "texas"
    tx_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for src in TX_SOURCES:
        url = src["url"]
        fid = src["id"]
        ext = ".pdf"
        path = download_to_dir(url, tx_dir, filename=f"{fid}{ext}")
        if path:
            results.append(path)

    # 28 TAC is not directly downloadable; write a stub note
    tac_note_path = tx_dir / "28_TAC_README.txt"
    tac_note_path.write_text(
        f"28 TAC (Texas Administrative Code) - Insurance rules\n\n{TX_TAC_NOTE}\n\n"
        "Relevant sections for auto compliance:\n"
        "- 28 TAC §5.4001-5.4005 (repair shop choice, parts, appraisal)\n"
        "- 28 TAC §5.4070 (parts, labor rate surveys)\n"
        "- 28 TAC §5.4104 (ACV, comparables, salvage deductions)\n",
        encoding="utf-8",
    )
    results.append(tac_note_path)
    logger.info("Wrote 28 TAC acquisition note to %s", tac_note_path)

    return results
