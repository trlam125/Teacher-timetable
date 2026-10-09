from __future__ import annotations

import hashlib
import hmac
import secrets
from app.config import SECRET_KEY
from itsdangerous import URLSafeTimedSerializer


class Passwords:
    @staticmethod
    def hash(password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), 200_000
        ).hex()
        return f"pbkdf2_sha256${salt}${digest}"

    @staticmethod
    def verify(password: str, encoded: str) -> bool:
        try:
            algo, salt, digest = encoded.split("$", 2)
            if algo != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), salt.encode(), 200_000
            ).hex()
            return hmac.compare_digest(actual, digest)
        except Exception:
            return False


pwd = Passwords()

signer = URLSafeTimedSerializer(SECRET_KEY, salt="session")

reset_signer = URLSafeTimedSerializer(SECRET_KEY, salt="password-reset")

captcha_signer = URLSafeTimedSerializer(SECRET_KEY, salt="forgot-password-captcha")

registration_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="registration-verification"
)

email_change_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="email-change-confirmation"
)

email_change_otp_signer = URLSafeTimedSerializer(
    SECRET_KEY, salt="email-change-verification"
)

