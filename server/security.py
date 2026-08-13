from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("密码至少需要 10 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def activation_code_hash(app_secret: str, code: str) -> str:
    normalized = "".join(code.strip().upper().split())
    return hmac.new(
        app_secret.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_activation_code(app_secret: str, code: str, expected: str) -> bool:
    return hmac.compare_digest(activation_code_hash(app_secret, code), expected)


def _activation_encryption_key(app_secret: str) -> bytes:
    return hashlib.sha256(
        b"teaching-choice/activation-code/aes-gcm/v1\0" + app_secret.encode("utf-8")
    ).digest()


def encrypt_activation_code(app_secret: str, student_no: str, code: str) -> str:
    """Encrypt a normalized activation code for administrator-only recovery.

    Authentication continues to use ``activation_code_hash``.  This encrypted copy is
    deliberately separate so a future display feature cannot weaken the login path.
    """

    normalized_code = "".join(code.strip().upper().split())
    nonce = secrets.token_bytes(12)
    aad = f"student:{student_no}".encode("utf-8")
    ciphertext = AESGCM(_activation_encryption_key(app_secret)).encrypt(
        nonce, normalized_code.encode("utf-8"), aad
    )
    encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
    return f"v1.{encoded}"


def decrypt_activation_code(app_secret: str, student_no: str, encoded: str) -> str:
    version, payload = encoded.split(".", 1)
    if version != "v1":
        raise ValueError("unsupported activation-code ciphertext version")
    payload += "=" * (-len(payload) % 4)
    packed = base64.urlsafe_b64decode(payload.encode("ascii"))
    if len(packed) < 29:
        raise ValueError("invalid activation-code ciphertext")
    nonce, ciphertext = packed[:12], packed[12:]
    aad = f"student:{student_no}".encode("utf-8")
    return AESGCM(_activation_encryption_key(app_secret)).decrypt(
        nonce, ciphertext, aad
    ).decode("utf-8")
