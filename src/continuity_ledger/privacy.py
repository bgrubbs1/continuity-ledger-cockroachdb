"""Fail-closed checks for the deliberately synthetic contest dataset."""

from __future__ import annotations

import re


class PrivacyBoundaryError(ValueError):
    """Raised when input resembles private or prohibited data."""


_PATTERNS = (
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone", re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")),
    ("IPv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("Windows user path", re.compile(r"[A-Z]:\\Users\\[^\\\s]+", re.I)),
    ("credential", re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]", re.I)),
)

_PROHIBITED_CONTEXT = re.compile(
    r"\b(?:employer|customer|coworker|home address|private network|production credential)\b",
    re.I,
)


def assert_synthetic_text(*values: str) -> None:
    """Reject common private markers before an event reaches any store."""

    for value in values:
        if not isinstance(value, str):
            raise PrivacyBoundaryError("All inspected values must be strings")
        for label, pattern in _PATTERNS:
            if pattern.search(value):
                raise PrivacyBoundaryError(f"Input rejected by synthetic-data boundary: {label}")
        if _PROHIBITED_CONTEXT.search(value):
            raise PrivacyBoundaryError("Input rejected by synthetic-data context boundary")

