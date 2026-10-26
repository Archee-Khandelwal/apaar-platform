"""Step 2: hashing is keyed + deterministic, masking is right, the vault round-trips."""
from __future__ import annotations

import hashlib
from datetime import date

import pytest

from app.core import crypto
from app.core.crypto import (
    hash_email,
    hash_phone,
    hmac_hash,
    is_minor,
    is_valid_apaar,
    mask_apaar,
    mask_name,
    normalize_phone,
    vault_decrypt,
    vault_encrypt,
)


def test_hmac_hash_is_deterministic() -> None:
    assert hmac_hash("9876543210") == hmac_hash("9876543210")


def test_hmac_hash_is_keyed_not_plain_sha256() -> None:
    """A 12-digit APAAR ID would be brute-forceable if we used a plain digest."""
    value = "123456781234"
    digest = crypto.hash_apaar(value)
    assert digest != hashlib.sha256(value.encode()).hexdigest()
    assert digest != hashlib.sha256((crypto.settings.hmac_key + value).encode()).hexdigest()
    assert len(digest) == 64


def test_hmac_hash_changes_with_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    first = hmac_hash("9876543210")
    monkeypatch.setattr(crypto.settings, "hmac_key", "f" * 64)
    assert hmac_hash("9876543210") != first


def test_phone_normalisation_before_hashing() -> None:
    assert normalize_phone("+91 98765 43210") == "9876543210"
    assert normalize_phone("098765-43210") == "9876543210"
    assert normalize_phone("12345") is None
    assert hash_phone("+91-9876543210") == hash_phone("9876543210")


def test_email_normalisation_before_hashing() -> None:
    assert hash_email("  Rahul.Sharma@Example.COM ") == hash_email("rahul.sharma@example.com")


def test_empty_values_hash_to_none() -> None:
    assert hmac_hash(None) is None
    assert hmac_hash("   ") is None
    assert hash_phone(None) is None


def test_mask_apaar() -> None:
    assert mask_apaar("123456781234") == "XXXX-XXXX-1234"
    assert mask_apaar("1234-5678-1234") == "XXXX-XXXX-1234"
    assert mask_apaar(None) == "XXXX-XXXX-XXXX"


def test_mask_name() -> None:
    assert mask_name("Rahul Sharma") == "R**** S."
    assert mask_name("Aisha") == "A****"
    assert mask_name("Aisha Fatima Khan") == "A**** K."
    assert mask_name(None) == "***"
    assert mask_name("R") == "R*"


def test_mask_name_never_leaks_more_than_initials() -> None:
    masked = mask_name("Priyanka Venkataraman")
    assert "riyanka" not in masked
    assert "enkataraman" not in masked


def test_apaar_format_validation() -> None:
    assert is_valid_apaar("123456781234")
    assert is_valid_apaar("1234 5678 1234")
    assert not is_valid_apaar("12345678123")  # 11 digits
    assert not is_valid_apaar("1234567812345")  # 13 digits
    assert not is_valid_apaar("12345678123A")
    assert not is_valid_apaar(None)


def test_vault_round_trip() -> None:
    for value in ("Rahul Sharma", "123456781234", "2006-03-12"):
        assert vault_decrypt(vault_encrypt(value)) == value


def test_vault_ciphertext_is_not_the_plaintext() -> None:
    ciphertext = vault_encrypt("Rahul Sharma")
    assert ciphertext is not None
    assert "Rahul" not in ciphertext
    assert vault_encrypt("Rahul Sharma") != ciphertext  # Fernet includes a timestamp + IV


def test_is_minor() -> None:
    assert is_minor(date(2012, 5, 1), as_of=date(2026, 10, 26))
    assert not is_minor(date(2006, 3, 12), as_of=date(2026, 10, 26))
    assert is_minor("2009-12-01", as_of=date(2026, 10, 26))
    assert not is_minor(None)
