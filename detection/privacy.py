"""PII masking helpers for logs and operator-facing diagnostics.

Transaction, payee, location, and device fields are treated as sensitive
financial PII even when the data is synthetic. Logs must never contain
full VPAs, phone numbers, device IDs, amounts, or coordinates.
"""

from __future__ import annotations

import logging
from typing import Optional

_MASK_KEEP: int = 4


def mask_identifier(value: Optional[str]) -> str:
    """Mask a generic identifier, keeping only the last four characters.

    Used for phone numbers and device IDs. Empty/None becomes ``****``.
    """
    if not value:
        return "****"
    if len(value) <= _MASK_KEEP:
        return "*" * len(value)
    return ("*" * (len(value) - _MASK_KEEP)) + value[-_MASK_KEEP:]


def mask_vpa(vpa: Optional[str]) -> str:
    """Mask a UPI VPA (``local@psp``), preserving the PSP suffix.

    Example: ``anuraag.r@oksbi`` → ``a****g@oksbi``-style last-4-of-local
    plus the handle. A VPA in a log is enough to identify a person.
    """
    if not vpa:
        return "****"
    if "@" not in vpa:
        return mask_identifier(vpa)
    local, _, handle = vpa.partition("@")
    return f"{mask_identifier(local)}@{handle}"


def log_score(logger: logging.Logger, transaction_id: str, score: float) -> None:
    """Emit the only fields that are safe to write to a log sink."""
    logger.info("scored transaction_id=%s score=%.4f", transaction_id, score)
