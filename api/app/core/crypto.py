"""Keyed hashing, the encrypted vault, and masking.

CLAUDE.md section 5 rules 1, 2, 3 and 6 are implemented here and nowhere else:

* Contact details (phone / email / guardian phone) are stored ONLY as
  ``HMAC-SHA256(HMAC_KEY, normalised_value)``. Matching happens on those hashes.
* Raw APAAR ID, full name and DOB live ONLY in the Fernet-encrypted ``vault`` table.
* We use a keyed HMAC, never ``sha256(secret + value)``: an APAAR ID is 12 digits, so an
  unkeyed digest is brute-forceable in seconds.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date, datetime

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_DIGITS = re.compile(r"\D+")
APAAR_LENGTH = 12


class CryptoConfigError(RuntimeError):
    """Raised when a key needed to protect student data is missing."""


# --------------------------------------------------------------------------- normalisation


def normalize_phone(value: str | int | None) -> str | None:
    """Indian phone numbers: keep the last 10 digits, so +91-98765 43210 == 9876543210."""
    if value is None:
        return None
    digits = _DIGITS.sub("", str(value))
    if len(digits) < 10:
        return None
    return digits[-10:]


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    return cleaned or None


def normalize_apaar(value: str | int | None) -> str | None:
    """Strip spaces/dashes from an APAAR ID. Returns the digits only, length unchecked."""
    if value is None:
        return None
    digits = _DIGITS.sub("", str(value))
    return digits or None


def normalize_name(value: str | None) -> str | None:
    """Collapse whitespace and casefold, for identity matching only. Never stored."""
    if value is None:
        return None
    cleaned = " ".join(str(value).split()).casefold()
    return cleaned or None


def is_valid_apaar(value: str | None) -> bool:
    digits = normalize_apaar(value)
    return bool(digits) and len(digits) == APAAR_LENGTH and digits.isdigit()


# --------------------------------------------------------------------------- keyed hashing


def hmac_key() -> bytes:
    """The raw HMAC key. Used by app/services/tokens.py to sign verification tokens."""
    return _hmac_key()


def _hmac_key() -> bytes:
    key = settings.hmac_key
    if not key or key.startswith("replace-me"):
        raise CryptoConfigError("HMAC_KEY is not set — run `make keys` before storing any data.")
    return key.encode("utf-8")


def hmac_hash(value: str | int | None) -> str | None:
    """Keyed digest of an already-normalised value. ``None`` in, ``None`` out."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hmac.new(_hmac_key(), text.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_phone(value: str | int | None) -> str | None:
    return hmac_hash(normalize_phone(value))


def hash_email(value: str | None) -> str | None:
    return hmac_hash(normalize_email(value))


def hash_apaar(value: str | int | None) -> str | None:
    return hmac_hash(normalize_apaar(value))


def hash_name(value: str | None) -> str | None:
    """Only used for identity-duplicate matching; the name itself stays in the vault."""
    return hmac_hash(normalize_name(value))


# --------------------------------------------------------------------------- vault (Fernet)


def _fernet() -> Fernet:
    key = settings.vault_key
    if not key or key.startswith("replace-me"):
        raise CryptoConfigError("VAULT_KEY is not set — run `make keys` before storing any data.")
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def vault_encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(str(plaintext).encode("utf-8")).decode("utf-8")


def vault_decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - defensive
        raise CryptoConfigError("Vault value could not be decrypted with the current VAULT_KEY") from exc


# --------------------------------------------------------------------------- masking


def mask_apaar(value: str | int | None) -> str:
    """``"123456781234"`` -> ``"XXXX-XXXX-1234"`` (CLAUDE.md section 5 rule 6)."""
    digits = normalize_apaar(value)
    if not digits:
        return "XXXX-XXXX-XXXX"
    return f"XXXX-XXXX-{digits[-4:]}" if len(digits) >= 4 else "XXXX-XXXX-XXXX"


def mask_name(value: str | None) -> str:
    """``"Rahul Sharma"`` -> ``"R***** S."`` — first initial, stars, surname initial."""
    if not value:
        return "***"
    parts = [part for part in str(value).split() if part]
    if not parts:
        return "***"
    first = parts[0]
    head = f"{first[0].upper()}{'*' * max(len(first) - 1, 1)}"
    if len(parts) == 1:
        return head
    return f"{head} {parts[-1][0].upper()}."


def dob_to_year(value: date | datetime | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.year
    if isinstance(value, date):
        return value.year
    text = str(value).strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def is_minor(dob: date | datetime | str | None, as_of: date | None = None) -> bool:
    """True when the student is under 18 (CLAUDE.md section 5 rule 12)."""
    if dob is None:
        return False
    if isinstance(dob, str):
        try:
            dob = date.fromisoformat(dob[:10])
        except ValueError:
            return False
    if isinstance(dob, datetime):
        dob = dob.date()
    reference = as_of or date.today()
    years = reference.year - dob.year - ((reference.month, reference.day) < (dob.month, dob.day))
    return years < 18
