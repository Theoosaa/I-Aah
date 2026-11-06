"""Encryption of the data file and the legacy format."""

import base64

import pytest
from cryptography.fernet import Fernet

from iaah.core.crypto import (
    LEGACY_ITERATIONS,
    MAGIC_LEGACY,
    Cipher,
    decrypt,
    is_encrypted,
    unlock,
)
from iaah.core.errors import PasswordRequiredError, StorageError, WrongPasswordError

FAST_ITERATIONS = 1_000  # fast key derivation for tests; the format stores the count
SALT = b"0123456789abcdef"


def test_round_trip_and_wrong_password() -> None:
    cipher = Cipher.derive("geheim", SALT, FAST_ITERATIONS)
    blob = cipher.encrypt(b"data")
    assert is_encrypted(blob)
    assert unlock(blob, "geheim") == (b"data", cipher)
    assert decrypt(blob, cipher) == b"data"
    with pytest.raises(WrongPasswordError):
        unlock(blob, "falsch")


def test_session_cipher_with_other_salt_needs_the_password() -> None:
    blob = Cipher.derive("geheim", SALT, FAST_ITERATIONS).encrypt(b"data")
    other = Cipher.derive("geheim", b"fedcba9876543210", FAST_ITERATIONS)
    with pytest.raises(PasswordRequiredError):
        decrypt(blob, other)


def test_legacy_blob_is_readable_and_upgraded() -> None:
    legacy_key = Cipher.derive("geheim", SALT, LEGACY_ITERATIONS).key
    blob = MAGIC_LEGACY + base64.b64encode(SALT) + b"\n" + Fernet(legacy_key).encrypt(b"alt")
    content, cipher = unlock(blob, "geheim")
    assert content == b"alt"
    assert cipher.salt != SALT  # future writes use a fresh salt and the current format


@pytest.mark.parametrize(
    "blob",
    [
        b"IAAHENC2\nnotanumber\nxx\ntoken",
        b"IAAHENC2\n0\nMDEy\ntoken",
        b"IAAHENC2\n99999999999999999999\nMDEy\ntoken",  # would overflow or stall derivation
        b"IAAHENC2\n" + b"9" * 5000 + b"\nMDEy\ntoken",
        b"IAAHENC2\n5",
        b"plain",
    ],
)
def test_damaged_envelope_raises_storage_error(blob: bytes) -> None:
    with pytest.raises(StorageError):
        unlock(blob, "pw")


def test_key_never_shows_in_repr() -> None:
    cipher = Cipher.derive("geheim", SALT, FAST_ITERATIONS)
    assert cipher.key.decode() not in repr(cipher)
