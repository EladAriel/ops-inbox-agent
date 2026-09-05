"""PII masking for audit records — knowledge/pii_handling.md."""
from __future__ import annotations

import re
from typing import Any

_SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# 555-0142 or 617-555-0199 or 555.0142
_PHONE_RE = re.compile(
    r"\b(?:\d{3}[-.\s]?)?\d{3}[-.\s]?\d{4}\b"
)
_ADDRESS_RE = re.compile(
    r"\b\d+\s+[A-Za-z0-9.'\-]+(?:\s+[A-Za-z0-9.'\-]+)*\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Ct|Court)\b",
    re.IGNORECASE,
)


def mask_pii_text(text: str) -> tuple[str, bool]:
    """Return (masked_text, found_pii)."""
    if not text:
        return text, False
    found = False

    def _ssn(m: re.Match[str]) -> str:
        nonlocal found
        found = True
        return f"***-**-{m.group(3)}"

    def _mark(repl: str):
        def _fn(_m: re.Match[str]) -> str:
            nonlocal found
            found = True
            return repl

        return _fn

    out = _SSN_RE.sub(_ssn, text)
    out = _EMAIL_RE.sub(_mark("[REDACTED_EMAIL]"), out)
    out = _ADDRESS_RE.sub(_mark("[REDACTED_ADDRESS]"), out)
    out = _PHONE_RE.sub(_mark("[REDACTED_PHONE]"), out)
    return out, found


def mask_pii_in_value(value: Any) -> tuple[Any, bool]:
    """Recursively mask PII in strings nested in dicts/lists; return (value, found)."""
    if isinstance(value, str):
        return mask_pii_text(value)
    if isinstance(value, dict):
        found_any = False
        out: dict[Any, Any] = {}
        for k, v in value.items():
            masked, hit = mask_pii_in_value(v)
            out[k] = masked
            found_any = found_any or hit
        return out, found_any
    if isinstance(value, list):
        found_any = False
        out_list: list[Any] = []
        for item in value:
            masked, hit = mask_pii_in_value(item)
            out_list.append(masked)
            found_any = found_any or hit
        return out_list, found_any
    if isinstance(value, tuple):
        found_any = False
        items: list[Any] = []
        for item in value:
            masked, hit = mask_pii_in_value(item)
            items.append(masked)
            found_any = found_any or hit
        return tuple(items), found_any
    return value, False
