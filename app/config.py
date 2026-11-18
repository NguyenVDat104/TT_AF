"""Quản lý cấu hình toàn cục (cai_dat.json), Hồ sơ Kênh, biến môi trường Cloud/Render và đường dẫn hệ thống."""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
ASSETS_DIR = APP_DIR / "assets"
STATIC_DIR = APP_DIR / "static"
PROMPT_TEMPLATE_PATH = BASE_DIR / "MAU_LENH_VIET_KICH_BAN.txt"

# Hỗ trợ DATA_DIR riêng khi chạy trên Render / Docker (ví dụ /app/data hoặc /var/data nếu gắn Persistent Disk)
_ENV_DATA_DIR = os.environ.get("DATA_DIR", "").strip()
DATA_ROOT = Path(_ENV_DATA_DIR).resolve() if _ENV_DATA_DIR else BASE_DIR

SAN_PHAM_DIR = DATA_ROOT / "san_pham"
SAN_SANG_DANG_DIR = DATA_ROOT / "san_sang_dang"
TAM_DIR = DATA_ROOT / "_tam"
CONFIG_PATH = DATA_ROOT / "cai_dat.json"

# Tự động nhận diện môi trường Cloud (Render / Linux container) và chế độ tiết kiệm RAM (512MB)
IS_CLOUD = bool(
    os.environ.get("RENDER")
    or os.environ.get("RAILWAY_ENVIRONMENT")
    or os.environ.get("CLOUD_MODE", "").strip() in ("1", "true", "yes")
    or os.name != "nt"
)
IS_LOW_MEMORY = bool(
    os.environ.get("RENDER")
    or os.environ.get("LOW_MEMORY_MODE", "").strip().lower() in ("1", "true", "yes")
)

_CONFIG_LOCK = threading.RLock()

DEFAULT_CHANNEL_PRESETS: Dict[str, Dict[str, Any]] = {
    "mac_dinh": {
        "name": "Kênh Mặc định (Đỏ Đô)",
        "band_color": "#7A1016",
        "band_color_v2": "#5C0B10",
        "band_color_v3": "#1E2229",
        "edge_voice": "vi-VN-NamMinhNeural",
        "default_hashtags": "#xuhuong #fyp #tiktokshop",
    },
    "thoi_trang_nu": {
        "name": "Kênh Thời trang Nữ (Đỏ Rượu / Kem)",
        "band_color": "#8B1E3F",
        "band_color_v2": "#6B142E",
        "band_color_v3": "#2D1E2F",
        "edge_voice": "vi-VN-HoaiMyNeural",
        "default_hashtags": "#thoitrangnu #ootd #xuhuong #tiktokshop",
    },
    "phu_kien_cong_nghe": {
        "name": "Kênh Phụ kiện & Gia dụng (Xanh Đen / Cam)",
        "band_color": "#142850",
        "band_color_v2": "#0F4C75",
        "band_color_v3": "#1B262C",
        "edge_voice": "vi-VN-NamMinhNeural",
        "default_hashtags": "#phukiendienthoai #giadungtienich #xuhuong #tiktokshop",
    },
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "active_channel": "mac_dinh",
    "channel_presets": DEFAULT_CHANNEL_PRESETS,
    # Giọng đọc (TTS)
    "voice_enabled": True,
    "tts_provider": "edge",  # "edge" | "cloud" | "voicestudio"
    "edge_voice": "vi-VN-NamMinhNeural",
    "edge_rate": "+6%",
    "edge_pitch": "+0Hz",
    "hook_boost_enabled": True,
    "hook_boost_rate": "+12%",
    "hook_boost_pitch": "+2Hz",
    # Cloud TTS
    "cloud_tts_provider": "gemini",  # "gemini" | "openai"
    "cloud_tts_api_key": "",
    "cloud_tts_model": "gemini-2.5-flash-preview-tts",
    "cloud_tts_voice": "Kore",
    "cloud_tts_base_url": "",
    # VoiceStudio Local (Bản 1.1)
    "voicestudio_url": "http://localhost:3900",
    "voice_engine": "voxcpm2",
    "voice_language": "Vietnamese",
    "voice_profile_id": "",
    "voice_instruct": "A young Vietnamese man, energetic and excited, friendly social media sales voice",
    "voice_seed": 1234,
    "voice_speed": 1.0,
    "voice_gap_seconds": 0.15,
    # Khuôn video & Dải chữ
    "band_color": "#7A1016",
    "band_color_v2": "#5C0B10",
    "band_color_v3": "#1E2229",
    "band_ratio_top": 0.667,
    "hook_uppercase": True,
    "hook_font_size": 60,
    "font_path": "",
    "pattern_path": "",
    "pattern_opacity": 0.18,
    "banner_zoom": True,
    # Chống trùng lặp (Anti-Duplicate v1..v3)
    "anti_duplicate_enabled": True,
    "auto_swap_slots_v2": True,
    "auto_vary_band_color": True,
    "auto_vary_closeup_speed": True,
    # Phụ đề động nửa sau (.ass)
    "subtitle_enabled": True,
    "subtitle_words_per_chunk": 4,
    "subtitle_font_size": 52,
    "subtitle_margin_v": 280,
    "subtitle_color": "#FFE600",
    # Mã hóa & Thời lượng
    "video_encoder": "libx264",  # "libx264" | "h264_nvenc"
    "low_memory_mode": IS_LOW_MEMORY,
    "sharpen": 0.5,
    "crf": 21 if IS_LOW_MEMORY else 20,
    "min_seconds": 18.0,
    "banner_min_seconds": 6.5,
    "banner_max_seconds": 12.0,
    "closeup_min_seconds": 5.0,
    "default_seconds": 19.0,
    # Âm thanh nền & Hashtag
    "music_path": "",
    "music_volume": 0.12,
    "default_hashtags": "#xuhuong #fyp #tiktokshop",
}


def ensure_directories() -> None:
    """Đảm bảo tất cả thư mục làm việc tồn tại."""
    for folder in (SAN_PHAM_DIR, SAN_SANG_DANG_DIR, TAM_DIR, ASSETS_DIR, STATIC_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def find_binary(name: str) -> str:
    """Tìm đường dẫn thực thi của ffmpeg / ffprobe trên cả Windows và Linux."""
    found = shutil.which(name)
    if found:
        return found

    if os.name == "nt":
        exe_name = f"{name}.exe" if not name.endswith(".exe") else name
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            winget_link = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / exe_name
            if winget_link.exists():
                return str(winget_link)

            packages_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
            if packages_dir.exists():
                for match in packages_dir.glob(f"Gyan.FFmpeg*/ffmpeg-*/bin/{exe_name}"):
                    if match.exists():
                        return str(match)

    return name


def load_config() -> Dict[str, Any]:
    """Đọc cai_dat.json; nếu chưa có thì khởi tạo với DEFAULT_CONFIG."""
    ensure_directories()
    with _CONFIG_LOCK:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if CONFIG_PATH.exists():
            try:
                raw = CONFIG_PATH.read_text(encoding="utf-8-sig")
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    merged_presets = dict(DEFAULT_CHANNEL_PRESETS)
                    if isinstance(loaded.get("channel_presets"), dict):
                        merged_presets.update(loaded["channel_presets"])
                    cfg.update(loaded)
                    cfg["channel_presets"] = merged_presets
            except Exception:
                pass
        else:
            save_config(cfg)

        if IS_LOW_MEMORY:
            cfg["low_memory_mode"] = True
        return cfg


def save_config(new_values: Dict[str, Any]) -> Dict[str, Any]:
    """Cập nhật và ghi cai_dat.json an toàn (atomic write)."""
    ensure_directories()
    with _CONFIG_LOCK:
        current = json.loads(json.dumps(DEFAULT_CONFIG))
        if CONFIG_PATH.exists():
            try:
                loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    current.update(loaded)
            except Exception:
                pass

        # Lọc bỏ các trường trạng thái chỉ đọc từ API
        clean_updates = {k: v for k, v in new_values.items() if k not in ("is_cloud", "has_ephemeral_disk")}
        current.update(clean_updates)

        if new_values.get("apply_channel_preset") and current.get("active_channel"):
            ch_key = current["active_channel"]
            preset = current.get("channel_presets", {}).get(ch_key)
            if isinstance(preset, dict):
                for k in ("band_color", "band_color_v2", "band_color_v3", "edge_voice", "default_hashtags"):
                    if k in preset and preset[k]:
                        current[k] = preset[k]
            current.pop("apply_channel_preset", None)

        tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, CONFIG_PATH)
        return current
