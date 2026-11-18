"""Engine Edge-TTS + Tự động đồng bộ lệch giờ đồng hồ & Dự phòng mượt sang Google Vietnamese TTS (gTTS)."""

from __future__ import annotations

import asyncio
import email.utils
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

from app.config import find_binary
from app.tts.base import (
    CHANNELS,
    SAMPLE_RATE,
    estimate_word_timings_for_sentence,
    get_wav_duration,
    normalize_audio_to_wav48k,
)

_CLOCK_SYNCED = False


def _sync_edge_tts_clock_skew_once() -> None:
    """Đồng bộ độ lệch đồng hồ máy tính với máy chủ Microsoft để tránh lỗi NoAudioReceived do sai ngày giờ Windows."""
    global _CLOCK_SYNCED
    if _CLOCK_SYNCED:
        return
    _CLOCK_SYNCED = True
    try:
        import edge_tts.drm as drm_mod

        with httpx.Client(timeout=4.0) as client:
            resp = client.head("https://www.microsoft.com")
            date_hdr = resp.headers.get("Date") or resp.headers.get("date")
            if date_hdr:
                parsed_dt = email.utils.parsedate_to_datetime(date_hdr)
                server_ts = parsed_dt.timestamp()
                local_ts = time.time()
                skew = server_ts - local_ts
                if abs(skew) > 30 and hasattr(drm_mod, "DRM") and hasattr(drm_mod.DRM, "adj_clock_skew_seconds"):
                    drm_mod.DRM.adj_clock_skew_seconds(skew)
    except Exception:
        pass


async def _run_edge_tts_async(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    raw_mp3_path: Path,
) -> List[Dict[str, Any]]:
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )
    word_boundaries: List[Dict[str, Any]] = []
    with open(raw_mp3_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                data = chunk.get("data")
                if data:
                    audio_file.write(data)
            elif chunk_type == "WordBoundary":
                offset_sec = float(chunk.get("offset", 0)) / 10_000_000.0
                dur_sec = float(chunk.get("duration", 0)) / 10_000_000.0
                w_text = str(chunk.get("text", "")).strip()
                if w_text:
                    word_boundaries.append(
                        {
                            "word": w_text,
                            "start": round(offset_sec, 3),
                            "end": round(offset_sec + max(0.05, dur_sec), 3),
                        }
                    )
    return word_boundaries


def _parse_rate_to_tempo(rate_str: str, base_tempo: float = 1.15) -> float:
    """Quy đổi chuỗi tốc độ kiểu '+12%' thành hệ số atempo của FFmpeg cho gTTS."""
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)%$", (rate_str or "").strip())
    if not m:
        return base_tempo
    pct = float(m.group(1))
    tempo = base_tempo * (1.0 + pct / 100.0)
    return max(0.75, min(1.85, round(tempo, 3)))


def _synthesize_gtts_vietnamese_fallback(
    text: str,
    rate: str,
    out_wav: Path,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Tầng dự phòng tự động bằng Google Translate Neural TTS tiếng Việt + FFmpeg atempo."""
    from gtts import gTTS

    raw_mp3 = out_wav.with_suffix(".gtts_raw.mp3")
    tts = gTTS(text=text, lang="vi", slow=False)
    tts.save(str(raw_mp3))

    # gTTS mặc định đọc hơi chậm so với nhịp TikTok -> tăng nhịp tự nhiên qua atempo
    tempo = _parse_rate_to_tempo(rate, base_tempo=1.18)
    ffmpeg_bin = find_binary("ffmpeg")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    tmp_wav = out_wav.with_suffix(".tmp.wav")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(raw_mp3),
        "-filter:a",
        f"atempo={tempo:.3f}",
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-c:a",
        "pcm_s16le",
        str(tmp_wav),
    ]
    res = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=creationflags, check=False)
    raw_mp3.unlink(missing_ok=True)

    if res.returncode != 0 or not tmp_wav.exists() or tmp_wav.stat().st_size == 0:
        raise RuntimeError("Không thể chuẩn hóa âm thanh từ gTTS sang WAV 48kHz.")

    os.replace(tmp_wav, out_wav)
    duration = get_wav_duration(out_wav)
    return duration, estimate_word_timings_for_sentence(text, duration)


def synthesize_edge_chunk(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    out_wav: Path,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Gọi Edge-TTS (có đồng bộ lệch giờ); nếu Microsoft từ chối token thì tự động chuyển sang gTTS tiếng Việt."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    raw_mp3 = out_wav.with_suffix(".raw.mp3")
    _sync_edge_tts_clock_skew_once()

    for attempt in range(2):
        try:
            word_boundaries = asyncio.run(
                _run_edge_tts_async(
                    text=text,
                    voice=voice or "vi-VN-NamMinhNeural",
                    rate=rate or "+6%",
                    pitch=pitch or "+0Hz",
                    raw_mp3_path=raw_mp3,
                )
            )
            if raw_mp3.exists() and raw_mp3.stat().st_size > 100:
                duration = normalize_audio_to_wav48k(raw_mp3, out_wav)
                raw_mp3.unlink(missing_ok=True)
                if not word_boundaries:
                    word_boundaries = estimate_word_timings_for_sentence(text, duration)
                return duration, word_boundaries
        except Exception:
            time.sleep(0.3 * (attempt + 1))

    raw_mp3.unlink(missing_ok=True)

    # Tự động chuyển mượt sang Google Vietnamese TTS (gTTS) để không bao giờ lỗi hàng đợi
    return _synthesize_gtts_vietnamese_fallback(text=text, rate=rate, out_wav=out_wav)
