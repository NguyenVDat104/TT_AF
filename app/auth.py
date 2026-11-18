"""Quản lý xác thực tài khoản (Login / Logout bằng Cookie phiên ký HMAC, băm mật khẩu PBKDF2 & Đổi mật khẩu)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from app import config as cfg_mod

SESSION_COOKIE_NAME = "tt_af_session"
SESSION_MAX_AGE_DEFAULT = 86400 * 7   # 7 ngày
SESSION_MAX_AGE_REMEMBER = 86400 * 30  # 30 ngày


def _get_or_create_secret_key() -> bytes:
    """Lấy khóa bí mật ký phiên từ biến môi trường hoặc tự sinh lưu bền vững."""
    env_secret = os.environ.get("SECRET_KEY", "").strip()
    if env_secret:
        return env_secret.encode("utf-8")

    cfg = cfg_mod.load_config()
    saved_secret = str(cfg.get("auth_secret_key", "")).strip()
    if not saved_secret:
        saved_secret = secrets.token_hex(32)
        cfg_mod.save_config({"auth_secret_key": saved_secret})
    return saved_secret.encode("utf-8")


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Băm mật khẩu an toàn bằng PBKDF2-HMAC-SHA256."""
    use_salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        use_salt.encode("utf-8"),
        120_000,
    )
    return f"pbkdf2_sha256${use_salt}${dk.hex()}"


def verify_password_hash(password: str, stored_hash: str) -> bool:
    """Kiểm tra mật khẩu khớp với chuỗi băm PBKDF2."""
    try:
        algo, salt, hex_digest = stored_hash.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        candidate = hash_password(password, salt=salt)
        return secrets.compare_digest(candidate, stored_hash)
    except Exception:
        return False


def is_auth_enabled() -> bool:
    """Mặc định bật tính năng đăng nhập (có thể tắt trong unit test nội bộ qua AUTH_DISABLED=1)."""
    if os.environ.get("AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        return False
    cfg = cfg_mod.load_config()
    return bool(cfg.get("auth_enabled", True))


def get_active_account_info() -> Tuple[str, Optional[str], str]:
    """Trả về (username, password_hash_custom, fallback_plain_password).

    Ưu tiên:
    1. Nếu người dùng đã đổi mật khẩu trên giao diện web (lưu auth_password_hash trong cai_dat.json) -> dùng mật khẩu mới đó.
    2. Nếu chưa đổi trên web -> dùng APP_USER (mặc định 'admin') và APP_PASSWORD từ biến môi trường Render (nếu chưa đặt APP_PASSWORD ở máy local thì mặc định là '123456').
    """
    cfg = cfg_mod.load_config()
    env_user = os.environ.get("APP_USER", "").strip() or "admin"
    env_pass = os.environ.get("APP_PASSWORD", "").strip()

    custom_user = str(cfg.get("auth_username", "")).strip()
    custom_hash = str(cfg.get("auth_password_hash", "")).strip()

    username = custom_user or env_user
    fallback_plain = env_pass if env_pass else "123456"
    return username, (custom_hash if custom_hash else None), fallback_plain


def is_using_default_local_password() -> bool:
    """Kiểm tra xem có đang dùng mật khẩu mặc định '123456' ở máy cá nhân không (để hiển thị gợi ý thân thiện trên trang Login)."""
    if os.environ.get("APP_PASSWORD", "").strip():
        return False
    cfg = cfg_mod.load_config()
    if str(cfg.get("auth_password_hash", "")).strip():
        return False
    return True


def verify_credentials(input_username: str, input_password: str) -> bool:
    """Xác thực tên đăng nhập và mật khẩu."""
    expected_user, custom_hash, fallback_plain = get_active_account_info()
    user_clean = (input_username or "").strip()
    if not secrets.compare_digest(user_clean.lower(), expected_user.lower()):
        return False

    if custom_hash:
        # Cho phép cả mật khẩu đã đổi trên UI HOẶC mật khẩu gốc APP_PASSWORD trên Render (phòng trường hợp quên)
        if verify_password_hash(input_password, custom_hash):
            return True
        env_pass = os.environ.get("APP_PASSWORD", "").strip()
        if env_pass and secrets.compare_digest(input_password, env_pass):
            return True
        return False

    return secrets.compare_digest(input_password, fallback_plain)


def update_account_credentials(current_password: str, new_username: str, new_password: str) -> str:
    """Đổi tên đăng nhập và mật khẩu quản trị."""
    cur_user, _, _ = get_active_account_info()
    if not verify_credentials(cur_user, current_password):
        raise ValueError("Mật khẩu hiện tại không chính xác.")

    clean_user = (new_username or "").strip() or cur_user
    if len(clean_user) < 3:
        raise ValueError("Tên đăng nhập phải có ít nhất 3 ký tự.")
    if len(new_password) < 4:
        raise ValueError("Mật khẩu mới phải có ít nhất 4 ký tự.")

    new_hash = hash_password(new_password)
    # Đổi luôn auth_secret_key để vô hiệu hóa các phiên đăng nhập cũ trên thiết bị khác
    cfg_mod.save_config(
        {
            "auth_username": clean_user,
            "auth_password_hash": new_hash,
            "auth_secret_key": secrets.token_hex(32),
        }
    )
    return clean_user


def create_session_token(username: str, max_age: int = SESSION_MAX_AGE_DEFAULT) -> str:
    """Tạo chuỗi token phiên ký HMAC-SHA256."""
    exp = int(time.time()) + max(60, int(max_age))
    payload = f"{username}|{exp}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    secret = _get_or_create_secret_key()
    sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: str) -> Optional[str]:
    """Kiểm tra tính hợp lệ và thời hạn của session token; trả về username nếu hợp lệ."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.rsplit(".", 1)
        secret = _get_or_create_secret_key()
        expected_sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, expected_sig):
            return None

        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii")).decode("utf-8")
        username, exp_str = decoded.split("|", 1)
        if int(exp_str) < int(time.time()):
            return None
        return username
    except Exception:
        return None


def get_authenticated_user_from_headers_or_cookies(
    cookie_token: Optional[str],
    auth_header: Optional[str],
) -> Optional[str]:
    """Kiểm tra đăng nhập qua Cookie phiên (trình duyệt) hoặc HTTP Basic Auth (API/Test)."""
    if cookie_token:
        user = verify_session_token(cookie_token)
        if user:
            return user

    if auth_header and auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            username, password = decoded.split(":", 1)
            if verify_credentials(username, password):
                return username
        except Exception:
            pass

    return None
