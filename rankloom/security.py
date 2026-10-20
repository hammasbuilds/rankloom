"""Password hashing, TOTP (RFC 6238), recovery codes and a sealed box for stored tokens.

Everything here is the standard library. The sealed box is HMAC-SHA256 in counter mode for the
keystream plus an HMAC-SHA256 tag over nonce and ciphertext (encrypt-then-MAC), with separate
keys derived for each job, so a stored GitHub token is unreadable and tamper-evident without
the app key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time

# --- passwords ---------------------------------------------------------------------------------

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD = 10
_COMMON = {
    "password12",
    "password123",
    "1234567890",
    "qwertyuiop",
    "iloveyou12",
    "letmein123",
    "welcome123",
    "admin12345",
    "pakistan123",
    "abc1234567",
    "passw0rd12",
    "football12",
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, want = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    dk = hashlib.scrypt(
        password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=len(_unb64(want))
    )
    return hmac.compare_digest(dk, _unb64(want))


def password_problem(password: str, email: str = "") -> str | None:
    """Why a new password is refused, or None when it is acceptable."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(password) > 256:
        return "Use at most 256 characters."
    if password.lower() in _COMMON or len(set(password)) < 4:
        return "That password is too easy to guess."
    # Compared with separators removed: "diegoreviewer1" is built from diego.reviewer@...
    local = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())
    if len(local) >= 4 and local in re.sub(r"[^a-z0-9]", "", password.lower()):
        return "Do not build the password from your email address."
    return None


# --- tokens ------------------------------------------------------------------------------------


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- TOTP --------------------------------------------------------------------------------------

TOTP_STEP = 30
TOTP_DIGITS = 6


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _b32decode(secret: str) -> bytes:
    s = secret.upper().replace(" ", "")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(secret: str, counter: int, digits: int = TOTP_DIGITS, digest: str = "sha1") -> str:
    mac = hmac.new(_b32decode(secret), struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def totp_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // TOTP_STEP)


def verify_totp(secret: str, code: str, last_step: int = 0, at: float | None = None) -> int | None:
    """The matched time step, or None. Steps at or before `last_step` are refused (no replay)."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != TOTP_DIGITS:
        return None
    current = totp_step(at)
    for step in (current - 1, current, current + 1):
        if step <= last_step:
            continue
        if hmac.compare_digest(hotp(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, email: str, issuer: str = "Rankloom") -> str:
    from urllib.parse import quote

    label = quote(f"{issuer}:{email}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_STEP}"
    )


def new_recovery_codes(count: int = 10) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return [
        "-".join("".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(2))
        for _ in range(count)
    ]


def recovery_hash(code: str) -> str:
    return hashlib.sha256(code.strip().lower().replace(" ", "").encode()).hexdigest()


# --- sealed box --------------------------------------------------------------------------------


class SealedBox:
    TAG = 32
    NONCE = 16

    def __init__(self, key: bytes):
        if len(key) < 32:
            raise ValueError("app key must be at least 32 bytes")
        self._enc = hmac.new(key, b"rankloom/enc", "sha256").digest()
        self._mac = hmac.new(key, b"rankloom/mac", "sha256").digest()

    def _stream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            out += hmac.new(self._enc, nonce + struct.pack(">Q", counter), "sha256").digest()
            counter += 1
        return bytes(out[:length])

    def seal(self, plaintext: str) -> bytes:
        data = plaintext.encode()
        nonce = secrets.token_bytes(self.NONCE)
        ct = bytes(a ^ b for a, b in zip(data, self._stream(nonce, len(data)), strict=True))
        tag = hmac.new(self._mac, nonce + ct, "sha256").digest()
        return nonce + ct + tag

    def open(self, blob: bytes) -> str:
        if len(blob) < self.NONCE + self.TAG:
            raise ValueError("sealed value is too short")
        nonce, ct, tag = blob[: self.NONCE], blob[self.NONCE : -self.TAG], blob[-self.TAG :]
        want = hmac.new(self._mac, nonce + ct, "sha256").digest()
        if not hmac.compare_digest(tag, want):
            raise ValueError("sealed value was altered or sealed with another key")
        return bytes(a ^ b for a, b in zip(ct, self._stream(nonce, len(ct)), strict=True)).decode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
