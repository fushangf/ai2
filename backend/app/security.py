from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


def hash_password(password: str, iterations: int) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${base64.urlsafe_b64encode(digest).decode('utf-8')}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_str, salt, digest_b64 = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
    except Exception:
        return False

    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    expected = base64.urlsafe_b64decode(digest_b64.encode("utf-8"))
    return hmac.compare_digest(derived, expected)


def _b64encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def sign_token(payload: dict[str, Any], secret_key: str, expire_hours: int) -> str:
    body = payload.copy()
    body["exp"] = int(time.time()) + max(1, expire_hours) * 3600
    body_bytes = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64encode(body_bytes)
    signature = hmac.new(secret_key.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64encode(signature)}"


def decode_token(token: str, secret_key: str) -> dict[str, Any]:
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("无效令牌格式") from exc

    expected_sig = hmac.new(secret_key.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
    actual_sig = _b64decode(signature_part)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("令牌签名无效")

    payload = json.loads(_b64decode(payload_part).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("令牌已过期")
    return payload
