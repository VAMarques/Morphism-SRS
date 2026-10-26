"""v3 wire format: nonce[12] || AES-GCM ciphertext || tag[16]."""
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def seal(key, data, aad):
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def open_sealed(key, data, aad):
    if len(data) < 28:
        raise ValueError("Truncated encrypted message")
    return AESGCM(key).decrypt(data[:12], data[12:], aad)


def encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def decode(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
