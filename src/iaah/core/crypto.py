"""Password-based encryption of the data file – and reading the legacy app's encrypted file.

Fernet (AES-128-CBC + HMAC-SHA256) with a key from PBKDF2-HMAC-SHA256. The current format
``IAAHENC2`` stores the iteration count and the salt in the header; the legacy app's
``IAAHENC1`` (fixed 200 000 iterations) stays readable. Content read from a legacy blob is
re-encrypted with a fresh salt and the current iteration count on the next write.
"""

import base64
import binascii
import os
from dataclasses import dataclass, field
from typing import Final, Self

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from iaah.core.errors import PasswordRequiredError, StorageError, WrongPasswordError

MAGIC_LEGACY: Final = b"IAAHENC1\n"  # legacy app: salt, token; 200 000 iterations
MAGIC: Final = b"IAAHENC2\n"  # iterations, salt, token
LEGACY_ITERATIONS: Final = 200_000
ITERATIONS: Final = 600_000  # OWASP guidance for PBKDF2-HMAC-SHA256
MIN_ITERATIONS: Final = 1
# A damaged header must neither overflow nor stall key derivation for minutes.
MAX_ITERATIONS: Final = 10 * ITERATIONS
SALT_BYTES: Final = 16
KEY_BYTES: Final = 32
NEWLINE: Final = b"\n"
PASSWORD_ENCODING: Final = "utf-8"


@dataclass(frozen=True, slots=True)
class Cipher:
    """A derived key plus the parameters written into the header. The key never shows in
    ``repr`` (log lines)."""

    key: bytes = field(repr=False)
    salt: bytes
    iterations: int

    @classmethod
    def create(cls, password: str) -> Self:
        """A new key with a fresh salt and the current iteration count."""
        return cls.derive(password, os.urandom(SALT_BYTES), ITERATIONS)

    @classmethod
    def derive(cls, password: str, salt: bytes, iterations: int) -> Self:
        """The key for ``password`` with these parameters (slow on purpose)."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, iterations=iterations
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode(PASSWORD_ENCODING)))
        return cls(key, salt, iterations)

    def encrypt(self, data: bytes) -> bytes:
        """``IAAHENC2`` blob: magic, iterations, salt, Fernet token."""
        header = MAGIC + str(self.iterations).encode() + NEWLINE + base64.b64encode(self.salt)
        return header + NEWLINE + Fernet(self.key).encrypt(data)


@dataclass(frozen=True, slots=True)
class _Envelope:
    salt: bytes
    iterations: int
    token: bytes
    legacy: bool


def is_encrypted(blob: bytes) -> bool:
    """Whether ``blob`` is an encrypted I-Aah file (either format)."""
    return blob.startswith((MAGIC, MAGIC_LEGACY))


def unlock(blob: bytes, password: str) -> tuple[bytes, Cipher]:
    """Decrypt with a password; returns the content and the cipher for future writes (a fresh
    current-format cipher when the blob uses the legacy format)."""
    envelope = _open_envelope(blob)
    cipher = Cipher.derive(password, envelope.salt, envelope.iterations)
    content = _decrypt(envelope, cipher)
    return content, Cipher.create(password) if envelope.legacy else cipher


def decrypt(blob: bytes, cipher: Cipher) -> bytes:
    """Decrypt with the session's cipher; a blob written with other parameters needs the
    password again."""
    envelope = _open_envelope(blob)
    if (envelope.salt, envelope.iterations) != (cipher.salt, cipher.iterations):
        raise PasswordRequiredError("file was encrypted with a different key")
    return _decrypt(envelope, cipher)


def _open_envelope(blob: bytes) -> _Envelope:
    try:
        if blob.startswith(MAGIC_LEGACY):
            salt, token = blob[len(MAGIC_LEGACY) :].split(NEWLINE, 1)
            return _Envelope(base64.b64decode(salt), LEGACY_ITERATIONS, token, legacy=True)
        if blob.startswith(MAGIC):
            iterations, salt, token = blob[len(MAGIC) :].split(NEWLINE, 2)
            return _Envelope(base64.b64decode(salt), _iterations(iterations), token, legacy=False)
    except (ValueError, binascii.Error) as error:
        raise StorageError("damaged encrypted file") from error
    raise StorageError("not an encrypted file")


def _iterations(raw: bytes) -> int:
    iterations = int(raw)
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise ValueError(f"invalid iteration count {iterations}")
    return iterations


def _decrypt(envelope: _Envelope, cipher: Cipher) -> bytes:
    try:
        return Fernet(cipher.key).decrypt(envelope.token)
    except InvalidToken:
        raise WrongPasswordError("wrong password or damaged file") from None
