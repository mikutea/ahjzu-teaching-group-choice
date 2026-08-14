from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .student_identity import StudentIdentityError, normalize_activation_code


PBKDF2_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
PASSWORD_DIGEST_BYTES = 32
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 256


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not (
        PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH
    ):
        raise ValueError(
            f"密码长度必须为 {PASSWORD_MIN_LENGTH} 至 {PASSWORD_MAX_LENGTH} 个字符"
        )
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def _decode_canonical_urlsafe_base64(
    value: str, *, expected_bytes: int
) -> bytes | None:
    expected_length = ((expected_bytes + 2) // 3) * 4
    if len(value) != expected_length:
        return None
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        return None
    if len(decoded) != expected_bytes:
        return None
    canonical = base64.urlsafe_b64encode(decoded)
    return decoded if hmac.compare_digest(canonical, encoded) else None


def _parse_password_hash(encoded: object) -> tuple[bytes, bytes] | None:
    if not isinstance(encoded, str):
        return None
    parts = encoded.split("$")
    if len(parts) != 4:
        return None
    algorithm, iterations, salt_text, digest_text = parts
    if algorithm != "pbkdf2_sha256" or iterations != str(PBKDF2_ITERATIONS):
        return None
    salt = _decode_canonical_urlsafe_base64(
        salt_text, expected_bytes=PASSWORD_SALT_BYTES
    )
    digest = _decode_canonical_urlsafe_base64(
        digest_text, expected_bytes=PASSWORD_DIGEST_BYTES
    )
    if salt is None or digest is None:
        return None
    return salt, digest


def validate_password_hash(encoded: object) -> bool:
    """Return whether a stored administrator hash is exactly the current format."""

    return _parse_password_hash(encoded) is not None


def verify_password(password: str, encoded: str) -> bool:
    parsed = _parse_password_hash(encoded)
    if (
        parsed is None
        or not isinstance(password, str)
        or len(password) > PASSWORD_MAX_LENGTH
    ):
        return False
    salt, expected = parsed
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(actual, expected)


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


def verify_activation_ciphertext(
    app_secret: str,
    student_no: str,
    encoded: str,
    expected_hash: str,
    submitted_code: str | None = None,
) -> bool:
    """Validate that the recoverable credential is current and internally consistent."""

    try:
        recovered = decrypt_activation_code(app_secret, student_no, encoded)
        normalized = normalize_activation_code(recovered)
        submitted = (
            normalize_activation_code(submitted_code)
            if submitted_code is not None
            else None
        )
    except (
        AttributeError,
        TypeError,
        ValueError,
        UnicodeError,
        binascii.Error,
        InvalidTag,
        StudentIdentityError,
    ):
        return False
    if not hmac.compare_digest(recovered, normalized):
        return False
    if not verify_activation_code(app_secret, recovered, expected_hash):
        return False
    return submitted is None or hmac.compare_digest(recovered, submitted)
