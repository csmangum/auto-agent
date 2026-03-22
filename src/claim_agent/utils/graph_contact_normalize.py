"""Normalize phone/email for claim relationship graph matching (fraud snapshot)."""

from __future__ import annotations

# Minimum digit length after normalization to avoid junk links (extensions, typos).
_MIN_PHONE_DIGITS = 7


def normalize_party_email_for_graph(email: object | None) -> str | None:
    """Lowercase trimmed email; None if empty or not a plausible address."""
    if not isinstance(email, str):
        return None
    s = email.strip().lower()
    if not s or "@" not in s:
        return None
    return s


def normalize_party_phone_for_graph(phone: object | None) -> str | None:
    """Digit-only key for graph linking.

    Strips to digits; drops values shorter than seven digits. For 11-digit NANP
    numbers starting with country code 1, uses the trailing 10 digits so
    ``(555) 555-0100`` and ``+1 555-555-0100`` align.
    """
    if not isinstance(phone, str):
        return None
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < _MIN_PHONE_DIGITS:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def sql_expr_phone_normalized_postgres(alias: str = "cp") -> str:
    """SQL fragment matching :func:`normalize_party_phone_for_graph` for PostgreSQL."""
    p = f"{alias}.phone"
    inner = f"regexp_replace(trim(coalesce({p}, '')), '[^0-9]', '', 'g')"
    return f"""(
  CASE
    WHEN length({inner}) < {_MIN_PHONE_DIGITS} THEN ''
    WHEN length({inner}) = 11 AND left({inner}, 1) = '1'
    THEN substr({inner}, 2)
    ELSE {inner}
  END
)"""
