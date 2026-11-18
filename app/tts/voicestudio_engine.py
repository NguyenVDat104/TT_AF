"""Engine VoiceStudio Local (VoxCPM2 tại http://localhost:3900) đúng đặc tả Bản 1.1."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from app.tts.base import estimate_word_timings_for_sentence, normalize_audio_to_wav48k


def check_voicestudio_connection(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra GET /health và GET /engines của VoiceStudio."""
    base_url = str(cfg.get("voicestudio_url", "http://localhost:3900")).rstrip("/")
    target_engine = str(cfg.get("voice_engine", "voxcpm2")).lower()
    try:
        with httpx.Client(timeout=5.0) as client:
            r_health = client.get(f"{base_url}/health")
            if r_health.status_code != 200:
                return {
                    "ok": False,
                    "provider": "voicestudio",
                    "engine": target_engine,
                    "message": f"VoiceStudio trả mã lỗi {r_health.status_code} tại {base_url}/health",
                }
            r_eng = client.get(f"{base_url}/engines")
            if r_eng.status_code == 200:
                eng_data = r_eng.json()
                engines = eng_data.get("engines", eng_data) if isinstance(eng_data, dict) else eng_data
                if isinstance(engines, list):
                    for item in engines:
                        if isinstance(item, dict) and str(item.get("id", item.get("name", ""))).lower() == target_engine:
                            if not item.get("available", True):
                                return {
                                    "ok": False,
                                    "provider": "voicestudio",
                                    "engine": target_engine,
                                    "message": f"Engine {target_engine} chưa được cài hoặc chưa available trong VoiceStudio.",
                                }
            return {
                "ok": True,
                "provider": "voicestudio",
                "engine": target_engine,
                "message": f"Đã kết nối VoiceStudio ({target_engine}) tại {base_url}.",
            }
    except Exception as exc:
        return {
            "ok": False,
            "provider": "voicestudio",
            "engine": target_engine,
            "message": f"Không kết nối được VoiceStudio tại {base_url}: {exc}",
        }


def get_voicestudio_profiles(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lấy danh sách giọng đã lưu từ GET /profiles của VoiceStudio."""
    base_url = str(cfg.get("voicestudio_url", "http://localhost:3900")).rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base_url}/profiles")
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("profiles", data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    return [
                        {
                            "id": str(p.get("id", p.get("profile_id", ""))),
                            "name": str(p.get("name", p.get("id", "Profile"))),
                            "provider": "voicestudio",
                        }
                        for p in items
                        if isinstance(p, dict)
                    ]
    except Exception:
        pass
    return []


def synthesize_voicestudio_chunk(
    text: str,
    cfg: Dict[str, Any],
    out_wav: Path,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Gọi POST /generate (multipart) tới VoiceStudio (timeout 300s trên GPU)."""
    base_url = str(cfg.get("voicestudio_url", "http://localhost:3900")).rstrip("/")
    engine = str(cfg.get("voice_engine", "voxcpm2"))
    language = str(cfg.get("voice_language", "Vietnamese"))
    profile_id = str(cfg.get("voice_profile_id", "")).strip()
    instruct = str(
        cfg.get(
            "voice_instruct",
            "A young Vietnamese man, energetic and excited, friendly social media sales voice",
        )
    )
    seed = str(cfg.get("voice_seed", 1234))
    speed = str(cfg.get("voice_speed", 1.0))

    form_data: Dict[str, str] = {
        "text": text,
        "language": language,
        "engine": engine,
        "seed": seed,
        "speed": speed,
    }
    if profile_id:
        form_data["profile_id"] = profile_id
    else:
        form_data["instruct"] = instruct

    files_multipart = {k: (None, v) for k, v in form_data.items()}
    raw_wav = out_wav.with_suffix(".vs_raw.wav")

    with httpx.Client(timeout=305.0) as client:
        resp = client.post(f"{base_url}/generate", files=files_multipart)
        if resp.status_code != 200:
            raise RuntimeError(f"VoiceStudio lỗi ({resp.status_code}): {resp.text[:250]}")

        content_type = resp.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            jdata = resp.json()
            audio_url = jdata.get("audio_url") or jdata.get("url")
            if not audio_url:
                raise RuntimeError(f"VoiceStudio không trả về audio_url: {jdata}")
            if str(audio_url).startswith("/"):
                audio_url = f"{base_url}{audio_url}"
            r_audio = client.get(str(audio_url))
            r_audio.raise_for_status()
            raw_wav.write_bytes(r_audio.content)
        else:
            raw_wav.write_bytes(resp.content)

    duration = normalize_audio_to_wav48k(raw_wav, out_wav)
    raw_wav.unlink(missing_ok=True)
    return duration, estimate_word_timings_for_sentence(text, duration)
