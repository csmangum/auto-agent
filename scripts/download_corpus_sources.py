#!/usr/bin/env python3
"""Download corpus sources for compliance RAG per docs/compliance-corpus-requirements.md.

Downloads:
- Texas: TIC, CPRC, Penal Code PDFs; 28 TAC note
- Florida: Florida Statutes zip
- New York: NY Insurance Law articles (HTML); 11 NYCRR note
- Federal: USC bulk XML zip; CFR Titles 12, 28, 45 (XML); CMS note

Output: data/corpus_sources/{texas,florida,new_york,federal}/

Usage:
    python scripts/download_corpus_sources.py [--state TX|FL|NY|FED|ALL] [--output DIR]
"""

import argparse
import logging
import sys
from pathlib import Path

# Project root - ensure we can import scripts.corpus_sources
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.corpus_sources.config import OUTPUT_DIR
from scripts.corpus_sources.download_federal import download_federal
from scripts.corpus_sources.download_fl import download_florida
from scripts.corpus_sources.download_ny import download_new_york
from scripts.corpus_sources.download_tx import download_texas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download corpus sources for compliance RAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--state",
        choices=["TX", "FL", "NY", "FED", "ALL"],
        default="ALL",
        help="State/jurisdiction to download (default: ALL)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_ROOT / OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    args = parser.parse_args()

    output = args.output if args.output.is_absolute() else _ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)

    all_results: list[Path] = []
    if args.state in ("TX", "ALL"):
        logger.info("Downloading Texas sources...")
        all_results.extend(download_texas(output))
    if args.state in ("FL", "ALL"):
        logger.info("Downloading Florida sources...")
        all_results.extend(download_florida(output))
    if args.state in ("NY", "ALL"):
        logger.info("Downloading New York sources...")
        all_results.extend(download_new_york(output))
    if args.state in ("FED", "ALL"):
        logger.info("Downloading Federal sources...")
        all_results.extend(download_federal(output))

    logger.info("Downloaded %d files to %s", len(all_results), output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
