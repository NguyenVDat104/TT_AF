"""Engine Cloud TTS: hỗ trợ Gemini TTS API, OpenAI-compatible TTS và FPT.AI."""

from __future__ import annotations

import base64
import wave
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from app.tts.base import estimate_word_timings_for_sentence, normalize_audio_to_wav48k


def _synthesize_gemini_tts(
    text: str,
    api_key: str,
    model: str,
    voice_name: str,
    out_wav: Path,
) -> float:
    model_id = model or "gemini-2.5-flash-preview-tts"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": f"Đọc lời quảng cáo TikTok tiếng Việt sau với giọng hào hứng, tự nhiên, rõ ràng: {text}"
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice_name or "Kore",
                    }
                }
            },
        },
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini TTS lỗi ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini TTS không trả về dữ liệu âm thanh.")
    parts = candidates[0].get("content", {}).get("parts", [])
    inline = parts[0].get("inlineData", {}) if parts else {}
    b64_data = inline.get("data", "")
    mime_type = inline.get("mimeType", "audio/pcm;rate=24000")
    if not b64_data:
        raise RuntimeError("Gemini TTS trả về dữ liệu rỗng.")

    raw_bytes = base64.b64decode(b64_data)
    raw_file = out_wav.with_suffix(".gemini_raw.wav")

    if "pcm" in mime_type.lower():
        # Gemini mặc định trả PCM 16-bit 24000Hz mono
        rate = 24000
        if "rate=" in mime_type:
            try:
                rate = int(mime_type.split("rate=")[1].split(";")[0])
            except Exception:
                rate = 24000
        with wave.open(str(raw_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(raw_bytes)
    else:
        raw_file.write_bytes(raw_bytes)

    duration = normalize_audio_to_wav48k(raw_file, out_wav)
    raw_file.unlink(missing_ok=True)
    return duration


def _synthesize_openai_compatible_tts(
    text: str,
    api_key: str,
    base_url: str,
    model: str,
    voice: str,
    out_wav: Path,
) -> float:
    endpoint = (base_url.rstrip("/") if base_url else "https://api.openai.com/v1") + "/audio/speech"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model or "tts-1",
        "input": text,
        "voice": voice or "alloy",
        "response_format": "mp3",
    }
    raw_mp3 = out_wav.with_suffix(".oai_raw.mp3")
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(endpoint, headers=headers, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI TTS lỗi ({resp.status_code}): {resp.text[:200]}")
        raw_mp3.write_bytes(resp.content)

    duration = normalize_audio_to_wav48k(raw_mp3, out_wav)
    raw_mp3.unlink(missing_ok=True)
    return duration


def synthesize_cloud_chunk(
    text: str,
    cfg: Dict[str, Any],
    out_wav: Path,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Tổng hợp 1 câu qua Cloud TTS API (Gemini hoặc OpenAI-compatible)."""
    api_key = str(cfg.get("cloud_tts_api_key", "")).strip()
    if not api_key:
        raise RuntimeError("Chưa cấu hình API Key cho Cloud TTS.")

    provider = str(cfg.get("cloud_tts_provider", "gemini")).lower()
    model = str(cfg.get("cloud_tts_model", ""))
    voice = str(cfg.get("cloud_tts_voice", "Kore"))
    base_url = str(cfg.get("cloud_tts_base_url", ""))

    if provider == "gemini":
        dur = _synthesize_gemini_tts(text, api_key, model, voice, out_wav)
    else:
        dur = _synthesize_openai_compatible_tts(text, api_key, base_url, model, voice, out_wav)

    return dur, estimate_word_timings_for_sentence(text, dur)
