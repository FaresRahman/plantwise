"""Encrypts database credentials at rest for the Database Import feature's
optional "persistent connection" mode.

The default import mode (one-time) never calls into this module at all —
credentials arrive in the request, get used to build a ConnectionParams,
and are discarded the moment the import finishes; nothing is ever written
to the database. This module only exists for the opt-in persistent-connection
path (app.modules.db_import.models.DbConnection), and the encrypted blob it
produces is the only form a password is ever allowed to reach storage in —
plaintext passwords must never be persisted, logged, or echoed back in an
API response.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.DB_CRED_ENCRYPTION_KEY.encode())


def encrypt_credential(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_credential(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as exc:
        # Only reachable if DB_CRED_ENCRYPTION_KEY was rotated without
        # re-encrypting existing rows, or the stored bytes were corrupted —
        # never leak the raw ciphertext/key material in the error.
        raise ValueError("Could not decrypt stored credential — the encryption key may have changed.") from exc
