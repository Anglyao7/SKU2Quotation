"""Small local credential primitive for development-only password accounts.

The production profile never reads this table: identities and password policy
remain with the configured enterprise provider. Scrypt is part of Python's
standard library, so newly provisioned merchant and customer accounts work in
the local demo without a new password dependency.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os


_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32


def normalize_local_identifier(value: str) -> str:
    return value.strip().casefold()


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )


def new_local_password_material(password: str) -> tuple[str, str]:
    salt = os.urandom(_SALT_BYTES)
    digest = _derive(password, salt)
    return (
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_local_password(*, password: str, salt: str, password_hash: str) -> bool:
    try:
        raw_salt = base64.urlsafe_b64decode(salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(password_hash.encode("ascii"))
        actual = _derive(password, raw_salt)
    except (ValueError, UnicodeError):
        return False
    return hmac.compare_digest(actual, expected)
