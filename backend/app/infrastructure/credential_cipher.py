"""Authenticated encryption for backend-only provider credentials."""

import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialCipher:
    """Encrypt provider credentials using a deployment-owned AES-256-GCM key."""

    def __init__(self, encoded_master_key: str) -> None:
        try:
            key = base64.urlsafe_b64decode(encoded_master_key.encode("ascii"))
        except Exception as error:
            raise ValueError("credential_master_key_invalid") from error
        if len(key) != 32:
            raise ValueError("credential_master_key_invalid")
        self._key = key
        self._cipher = AESGCM(key)

    @staticmethod
    def generate_master_key() -> str:
        """Generate a URL-safe key suitable for deployment secret configuration."""
        return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode(
            "ascii"
        )

    def encrypt(self, plaintext: str, associated_data: str) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        ciphertext = self._cipher.encrypt(
            nonce, plaintext.encode("utf-8"), associated_data.encode("utf-8")
        )
        return nonce, ciphertext

    def decrypt(self, nonce: bytes, ciphertext: bytes, associated_data: str) -> str:
        plaintext = self._cipher.decrypt(
            nonce, ciphertext, associated_data.encode("utf-8")
        )
        return plaintext.decode("utf-8")

    def fingerprint(self, credential: str) -> str:
        return hmac.new(
            self._key, credential.encode("utf-8"), hashlib.sha256
        ).hexdigest()


def masked_hint(credential: str) -> str:
    """Return only a non-sensitive four-character suffix."""
    return f"...{credential[-4:]}" if len(credential) >= 4 else "..."
