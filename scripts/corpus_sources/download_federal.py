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
from pathlib import Path

from .config import FEDERAL_SOURCES, OUTPUT_DIR
from .downloader import download_to_dir

logger = logging.getLogger(__name__)


def download_federal(output_dir: Path | None = None) -> list[Path]:
    """Download federal statutory and regulatory sources. Returns list of downloaded paths."""
    out = output_dir or Path.cwd() / OUTPUT_DIR
    fed_dir = out / "federal"
    fed_dir.mkdir(parents=True, exist_ok=True)

    from .downloader import LARGE_FILE_TIMEOUT

    results: list[Path] = []
    for src in FEDERAL_SOURCES:
        url = src["url"]
        fid = src["id"]
        fmt = src.get("format", "xml")
        ext = ".zip" if fmt == "zip" else ".xml"
        kwargs = {"timeout": LARGE_FILE_TIMEOUT} if fid == "cfr_title_45" else {}
        path = download_to_dir(url, fed_dir, filename=f"{fid}{ext}", **kwargs)
        if path:
            results.append(path)

    # CMS Medicare - no bulk download; add acquisition note
    cms_note = fed_dir / "CMS_Medicare_README.txt"
    cms_note.write_text(
        "CMS Medicare Secondary Payer (MSP) & Section 111\n\n"
        "Sources:\n"
        "- https://www.cms.gov/medicare-coordination-benefits-recovery\n"
        "- https://www.cms.gov/medicare-coordination-benefits-recovery/mandatory-insurance-reporting\n\n"
        "Relevant: MSP conditional payment recovery, MMSEA Section 111 reporting, "
        "MSA guidelines.\n",
        encoding="utf-8",
    )
    results.append(cms_note)

    return results
