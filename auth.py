import hashlib
import os
import base64


def hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return base64.b64encode(salt + key).decode()


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        raw = base64.b64decode(stored)
        salt, expected = raw[:32], raw[32:]
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        return actual == expected
    except Exception:
        return False
