from __future__ import annotations


def redact(text: str, *secrets: str | None) -> str:
    """Replace every non-empty secret in ``text`` so it never reaches logs or notifications."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text
