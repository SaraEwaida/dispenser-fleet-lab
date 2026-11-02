"""Single redaction utility used by request logs and audit logs.

Anything that could identify a (fictional) patient or carries free-text diagnostic detail is masked
before it is written anywhere persistent.
"""

import re
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = {
    "first_name", "last_name", "full_name", "date_of_birth", "dob", "email", "reporter_email", "phone",
    "address", "allergies", "diagnostic_notes", "password", "password_hash", "access_token", "token",
    "authorization", "reporter_name",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\w-])\+?\d[\d ()-]{7,}\d")
_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]+")


def redact_text(value: str) -> str:
    value = _BEARER_RE.sub("Bearer " + REDACTED, value)
    value = _EMAIL_RE.sub(REDACTED, value)
    value = _PHONE_RE.sub(REDACTED, value)
    return value


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact a structure. Keys in SENSITIVE_KEYS are fully masked; strings are pattern-scrubbed."""
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return None if value is None else REDACTED
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    return f"{local[0]}***@{domain}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"
