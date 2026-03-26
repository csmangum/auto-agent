"""Filter to abridge repeated CrewAI prompt blocks in stdout.

Shows full content the first time; replaces subsequent identical blocks with
a short "[...abridged...]" placeholder.
"""

import hashlib
import logging
import sys
from contextlib import contextmanager
from typing import TextIO

logger = logging.getLogger(__name__)

_PROMPT_BLOCK_MARKERS = ("CLAIM DATA", "CLASSIFICATION RULES", "Reply with a JSON")
_ABRIDGED_PLACEHOLDER = "\n[...abridged: claim data and classification rules (see above)]\n"


def _is_prompt_block(text: str) -> bool:
    """True if text looks like the repeated router/crew prompt block."""
    return all(marker in text for marker in _PROMPT_BLOCK_MARKERS)


def _content_hash(text: str) -> str:
    """Stable hash for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _AbridgingWriter:
    """Wraps a stream and abridges repeated prompt blocks."""

    def __init__(self, target: TextIO):
        self._target = target
        self._seen_hashes: set[str] = set()
        self._buffer = ""

    def write(self, s: str) -> int:
        self._buffer += s
        # Only process when we have a complete panel (╭...╰)
        while "╭" in self._buffer and "╰" in self._buffer:
            i = self._buffer.find("╭")
            j = self._buffer.find("╰", i)
            if j < 0:
                break
            line_end = self._buffer.find("\n", j) + 1
            if line_end == 0:
                line_end = len(self._buffer)
            before = self._buffer[:i]
            panel = self._buffer[i:line_end]
            self._buffer = self._buffer[line_end:]
            self._target.write(before)
            if _is_prompt_block(panel):
                h = _content_hash(panel)
                if h in self._seen_hashes:
                    self._target.write(_ABRIDGED_PLACEHOLDER)
                else:
                    self._seen_hashes.add(h)
                    self._target.write(panel)
            else:
                self._target.write(panel)
        return len(s)

    def flush(self) -> None:
        if self._buffer:
            self._target.write(self._buffer)
            self._buffer = ""
        self._target.flush()

    def __getattr__(self, name: str):
        return getattr(self._target, name)


@contextmanager
def abridge_crew_output():
    """Context manager that abridges repeated CrewAI prompt blocks on stdout."""
    try:
        from claim_agent.config import get_settings

        if not get_settings().crew_verbose:
            yield
            return
    except Exception:
        logger.debug("Could not read crew_verbose setting; skipping output abridging", exc_info=True)
        yield
        return

    if getattr(sys.stdout, "_claim_agent_abridging", False):
        yield
        return

    original = sys.stdout
    wrapper = _AbridgingWriter(original)
    wrapper._claim_agent_abridging = True  # type: ignore[attr-defined]
    sys.stdout = wrapper
    try:
        yield
    finally:
        wrapper.flush()
        sys.stdout = original
