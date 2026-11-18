"""Lõi xử lý giọng đọc: tách câu <= 140 ký tự, tách phần Hook/Body, cache SHA-1 WAV 48kHz, ghép wave & mốc từ."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import TAM_DIR, find_binary

SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM


@dataclass
class WordTiming:
    word: str
    start: float  # giây (tính từ đầu toàn bộ lời đọc)
    end: float


@dataclass
class VoiceSynthesisResult:
    wav_path: Path
    total_duration: float
    hook_duration: float
    word_timings: List[WordTiming] = field(default_factory=list)
    provider_used: str = "edge"
    cached_hits: int = 0
    total_chunks: int = 0


def _split_long_clause(clause: str, max_chars: int = 140) -> List[str]:
    """Nếu câu dài hơn 140 ký tự, cắt thêm ở dấu phẩy hoặc khoảng trắng gần nhất."""
    clause = re.sub(r"\s+", " ", clause).strip()
    if not clause:
        return []
    if len(clause) <= max_chars:
        return [clause]

    comma_parts = [p.strip() for p in re.split(r"(?<=,)\s*", clause) if p.strip()]
    chunks: List[str] = []
    current = ""

    for part in comma_parts:
        candidate = f"{current} {part}".strip() if current else part
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            if len(part) <= max_chars:
                current = part
            else:
                # Cắt thêm theo từ nếu không có dấu phẩy
                words = part.split(" ")
                sub = ""
                for w in words:
                    cand_w = f"{sub} {w}".strip() if sub else w
                    if len(cand_w) <= max_chars:
                        sub = cand_w
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = w
                current = sub
    if current:
        chunks.append(current)
    return chunks


def split_sentences(text: str, max_chars: int = 140) -> List[str]:
    """Tách lời đọc thành câu theo dấu . ! ? … ; câu dài hơn 140 ký tự cắt thêm ở dấu phẩy."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if not cleaned:
        return []

    raw_sentences = re.split(r"(?<=[.!?…;])\s+", cleaned)
    result: List[str] = []
    for sent in raw_sentences:
        sent = sent.strip()
        if not sent:
            continue
        result.extend(_split_long_clause(sent, max_chars=max_chars))
    return result


def _norm_compare(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def split_hook_and_body_sentences(
    hook_text: str,
    doc_text: str,
    max_chars: int = 140,
) -> Tuple[List[str], List[str]]:
    """Tách lời đọc DOC thành 2 danh sách: các câu thuộc phần HOOK và các câu thuộc phần THÂN.

    Nhờ đó dù câu HOOK chứa nhiều dấu chấm than ("Đây rồi! Đúng là cái mẫu..."),
    toàn bộ phần HOOK vẫn được tính đúng vào hook_duration và được nhấn giọng đồng nhất.
    """
    hook_clean = re.sub(r"\s+", " ", (hook_text or "")).strip()
    doc_clean = re.sub(r"\s+", " ", (doc_text or "")).strip()

    if not doc_clean and hook_clean:
        doc_clean = hook_clean

    all_sentences = split_sentences(doc_clean, max_chars=max_chars)
    if not all_sentences:
        return [], []

    if not hook_clean:
        return [all_sentences[0]], all_sentences[1:]

    norm_hook = _norm_compare(hook_clean)
    if not norm_hook:
        return [all_sentences[0]], all_sentences[1:]

    hook_sentences: List[str] = []
    body_sentences: List[str] = []
    accum_norm = ""

    for idx, sent in enumerate(all_sentences):
        if idx == 0 or len(accum_norm) < len(norm_hook):
            hook_sentences.append(sent)
            accum_norm += _norm_compare(sent)
        else:
            body_sentences.append(sent)

    return hook_sentences, body_sentences


def normalize_audio_to_wav48k(src_audio: Path, dst_wav: Path) -> float:
    """Chuyển đổi file âm thanh bất kỳ (MP3/WAV) về chuẩn WAV 48kHz mono 16-bit PCM và trả về độ dài (giây)."""
    ffmpeg_bin = find_binary("ffmpeg")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    tmp_wav = dst_wav.with_suffix(".tmp.wav")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(src_audio),
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-c:a",
        "pcm_s16le",
        str(tmp_wav),
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        timeout=30,
        creationflags=creationflags,
        check=False,
    )
    if res.returncode != 0 or not tmp_wav.exists() or tmp_wav.stat().st_size == 0:
        raise RuntimeError(
            f"FFmpeg không thể chuẩn hóa âm thanh sang WAV 48kHz: {res.stderr.decode('utf-8', errors='ignore')[:200]}"
        )

    os.replace(tmp_wav, dst_wav)
    return get_wav_duration(dst_wav)


def get_wav_duration(wav_path: Path) -> float:
    """Đọc thời lượng chính xác của file WAV chuẩn."""
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / float(rate) if rate > 0 else 0.0


def estimate_word_timings_for_sentence(sentence: str, duration: float) -> List[Dict[str, Any]]:
    """Nội suy mốc thời gian từng từ khi engine không trả về WordBoundary (như VoiceStudio / Cloud)."""
    words = [w for w in re.split(r"\s+", sentence.strip()) if w]
    if not words or duration <= 0:
        return []
    # Trọng số theo độ dài ký tự + dấu câu cuối từ
    weights: List[float] = []
    for w in words:
        base_w = max(1.0, len(re.sub(r"\W+", "", w)) * 0.8)
        if w.endswith((",", ";", ":")):
            base_w += 1.2
        elif w.endswith((".", "!", "?", "…")):
            base_w += 1.8
        weights.append(base_w)

    total_w = sum(weights) or 1.0
    timings: List[Dict[str, Any]] = []
    cursor = 0.0
    for w, weight in zip(words, weights):
        w_dur = duration * (weight / total_w)
        timings.append(
            {
                "word": w,
                "start": round(cursor, 3),
                "end": round(cursor + w_dur, 3),
            }
        )
        cursor += w_dur
    return timings


def _make_sentence_cache_key(
    provider: str,
    voice_sig: str,
    sentence: str,
) -> str:
    payload = f"{provider}||{voice_sig}||{sentence.strip()}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _synthesize_single_chunk(
    sentence: str,
    is_hook: bool,
    cfg: Dict[str, Any],
    cache_dir: Path,
) -> Tuple[Path, float, List[Dict[str, Any]], bool, str]:
    """Tạo giọng cho 1 câu đơn (hoặc lấy từ cache SHA-1).

    Trả về: (wav_path, duration, relative_words, was_cached, provider_used)
    """
    from app.tts.cloud_engine import synthesize_cloud_chunk
    from app.tts.edge_engine import synthesize_edge_chunk
    from app.tts.voicestudio_engine import synthesize_voicestudio_chunk

    cache_dir.mkdir(parents=True, exist_ok=True)
    provider = str(cfg.get("tts_provider", "edge")).lower()

    if provider == "edge":
        voice = str(cfg.get("edge_voice", "vi-VN-NamMinhNeural"))
        if is_hook and cfg.get("hook_boost_enabled", True):
            rate = str(cfg.get("hook_boost_rate", "+12%"))
            pitch = str(cfg.get("hook_boost_pitch", "+2Hz"))
        else:
            rate = str(cfg.get("edge_rate", "+6%"))
            pitch = str(cfg.get("edge_pitch", "+0Hz"))
        voice_sig = f"edge|{voice}|{rate}|{pitch}"
    elif provider == "cloud":
        c_prov = str(cfg.get("cloud_tts_provider", "gemini"))
        c_model = str(cfg.get("cloud_tts_model", ""))
        c_voice = str(cfg.get("cloud_tts_voice", ""))
        voice_sig = f"cloud|{c_prov}|{c_model}|{c_voice}|hook={is_hook}"
    else:
        vs_eng = str(cfg.get("voice_engine", "voxcpm2"))
        vs_prof = str(cfg.get("voice_profile_id", ""))
        vs_inst = str(cfg.get("voice_instruct", ""))
        vs_seed = str(cfg.get("voice_seed", 1234))
        vs_speed = str(cfg.get("voice_speed", 1.0))
        voice_sig = f"vs|{vs_eng}|{vs_prof}|{vs_inst}|{vs_seed}|{vs_speed}"

    sha1 = _make_sentence_cache_key(provider, voice_sig, sentence)
    cached_wav = cache_dir / f"{sha1}.wav"
    cached_words = cache_dir / f"{sha1}.words.json"

    if cached_wav.exists() and cached_wav.stat().st_size > 100:
        try:
            dur = get_wav_duration(cached_wav)
            if dur > 0.05:
                if cached_words.exists():
                    rel_words = json.loads(cached_words.read_text(encoding="utf-8"))
                else:
                    rel_words = estimate_word_timings_for_sentence(sentence, dur)
                return cached_wav, dur, rel_words, True, provider
        except Exception:
            pass

    # Chưa có trong cache -> gọi engine tương ứng
    rel_words: List[Dict[str, Any]] = []
    used_provider = provider

    if provider == "edge":
        dur, rel_words = synthesize_edge_chunk(
            text=sentence,
            voice=voice,
            rate=rate,
            pitch=pitch,
            out_wav=cached_wav,
        )
    elif provider == "cloud":
        try:
            dur, rel_words = synthesize_cloud_chunk(
                text=sentence,
                cfg=cfg,
                out_wav=cached_wav,
            )
        except Exception as exc:
            # Tự động fallback về Edge-TTS nếu Cloud API chưa điền key hoặc lỗi mạng tạm thời
            if cfg.get("cloud_fallback_to_edge", True):
                used_provider = "edge"
                dur, rel_words = synthesize_edge_chunk(
                    text=sentence,
                    voice=str(cfg.get("edge_voice", "vi-VN-NamMinhNeural")),
                    rate=str(cfg.get("edge_rate", "+6%")),
                    pitch=str(cfg.get("edge_pitch", "+0Hz")),
                    out_wav=cached_wav,
                )
            else:
                raise exc
    else:
        dur, rel_words = synthesize_voicestudio_chunk(
            text=sentence,
            cfg=cfg,
            out_wav=cached_wav,
        )

    if not rel_words:
        rel_words = estimate_word_timings_for_sentence(sentence, dur)

    try:
        cached_words.write_text(json.dumps(rel_words, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return cached_wav, dur, rel_words, False, used_provider


def concatenate_wav_chunks(
    chunk_wavs: List[Path],
    out_wav: Path,
    gap_seconds: float = 0.15,
) -> Tuple[float, List[float]]:
    """Ghép các câu WAV 48kHz mono 16-bit bằng module wave, cách nhau gap_seconds im lặng.

    Trả về (tổng_thời_lượng, danh_sách_thời_điểm_bắt_đầu_mỗi_câu).
    """
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_wav.with_suffix(".tmp.wav")
    gap_frames = max(0, int(round(gap_seconds * SAMPLE_RATE)))
    silence_bytes = b"\x00" * (gap_frames * SAMPLE_WIDTH * CHANNELS)

    start_offsets: List[float] = []
    total_frames = 0

    with wave.open(str(tmp_out), "wb") as out_wf:
        out_wf.setnchannels(CHANNELS)
        out_wf.setsampwidth(SAMPLE_WIDTH)
        out_wf.setframerate(SAMPLE_RATE)

        for idx, wav_path in enumerate(chunk_wavs):
            if idx > 0 and gap_frames > 0:
                out_wf.writeframes(silence_bytes)
                total_frames += gap_frames

            start_offsets.append(total_frames / float(SAMPLE_RATE))
            with wave.open(str(wav_path), "rb") as in_wf:
                frames_data = in_wf.readframes(in_wf.getnframes())
                out_wf.writeframes(frames_data)
                total_frames += len(frames_data) // (SAMPLE_WIDTH * CHANNELS)

    os.replace(tmp_out, out_wav)
    return total_frames / float(SAMPLE_RATE), start_offsets


def synthesize_script_voice(
    hook_text: str,
    doc_text: str,
    out_wav: Path,
    cache_dir: Path,
    cfg: Dict[str, Any],
    log_fn: Optional[Any] = None,
) -> VoiceSynthesisResult:
    """Tổng hợp toàn bộ giọng đọc cho 1 kịch bản video, trả về thời lượng tổng, thời lượng Hook và mốc từng từ."""
    hook_sents, body_sents = split_hook_and_body_sentences(hook_text, doc_text)
    all_items: List[Tuple[str, bool]] = [(s, True) for s in hook_sents] + [(s, False) for s in body_sents]

    if not all_items:
        raise ValueError("Kịch bản không có nội dung lời đọc để tạo giọng.")

    gap_sec = float(cfg.get("voice_gap_seconds", 0.15))
    chunk_wavs: List[Path] = []
    chunk_durations: List[float] = []
    chunk_rel_words: List[List[Dict[str, Any]]] = []
    cached_hits = 0
    provider_used = str(cfg.get("tts_provider", "edge"))

    for idx, (sentence, is_hook) in enumerate(all_items, start=1):
        wav_p, dur, rel_words, was_cached, used_prov = _synthesize_single_chunk(
            sentence=sentence,
            is_hook=is_hook,
            cfg=cfg,
            cache_dir=cache_dir,
        )
        provider_used = used_prov
        if was_cached:
            cached_hits += 1
        if log_fn:
            tag = "cache" if was_cached else used_prov
            log_fn(f"  + Câu {idx}/{len(all_items)} ({tag}, {dur:.1f}s): {sentence[:55]}...")
        chunk_wavs.append(wav_p)
        chunk_durations.append(dur)
        chunk_rel_words.append(rel_words)

    total_duration, start_offsets = concatenate_wav_chunks(
        chunk_wavs=chunk_wavs,
        out_wav=out_wav,
        gap_seconds=gap_sec,
    )

    # Tính thời lượng toàn bộ phần Hook (bao gồm khoảng nghỉ giữa các câu trong Hook nếu Hook > 1 câu)
    num_hook = max(1, len(hook_sents))
    hook_sents_dur = sum(chunk_durations[:num_hook])
    hook_gaps_dur = max(0, num_hook - 1) * gap_sec
    hook_duration = hook_sents_dur + hook_gaps_dur

    # Quy đổi mốc thời gian từng từ sang trục thời gian toàn video
    global_words: List[WordTiming] = []
    for offset, rel_list in zip(start_offsets, chunk_rel_words):
        for w_item in rel_list:
            global_words.append(
                WordTiming(
                    word=str(w_item.get("word", "")),
                    start=round(offset + float(w_item.get("start", 0.0)), 3),
                    end=round(offset + float(w_item.get("end", 0.0)), 3),
                )
            )

    return VoiceSynthesisResult(
        wav_path=out_wav,
        total_duration=round(total_duration, 3),
        hook_duration=round(hook_duration, 3),
        word_timings=global_words,
        provider_used=provider_used,
        cached_hits=cached_hits,
        total_chunks=len(all_items),
    )


def synthesize_test_sentence(text: str, cfg: Dict[str, Any]) -> Path:
    """Tạo thử 1 câu giọng đọc để người dùng nghe thử trên tab Cài đặt."""
    TAM_DIR.mkdir(parents=True, exist_ok=True)
    test_cache = TAM_DIR / "_test_voice_cache"
    out_wav = TAM_DIR / "voice_test_preview.wav"
    res = synthesize_script_voice(
        hook_text=text,
        doc_text=text,
        out_wav=out_wav,
        cache_dir=test_cache,
        cfg=cfg,
    )
    return res.wav_path


def check_tts_status(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra trạng thái kết nối của nguồn TTS đang chọn."""
    from app.tts.voicestudio_engine import check_voicestudio_connection

    provider = str(cfg.get("tts_provider", "edge")).lower()
    if provider == "edge":
        return {
            "ok": True,
            "provider": "edge",
            "engine": cfg.get("edge_voice", "vi-VN-NamMinhNeural"),
            "message": "Edge-TTS sẵn sàng (~2 giây/video, không tốn VRAM).",
        }
    if provider == "cloud":
        api_key = str(cfg.get("cloud_tts_api_key", "")).strip()
        c_prov = str(cfg.get("cloud_tts_provider", "gemini"))
        if not api_key:
            return {
                "ok": False,
                "provider": "cloud",
                "engine": c_prov,
                "message": f"Chưa nhập API Key cho Cloud TTS ({c_prov}). Sẽ tự động dùng Edge-TTS dự phòng.",
            }
        return {
            "ok": True,
            "provider": "cloud",
            "engine": f"{c_prov} ({cfg.get('cloud_tts_model', '')})",
            "message": f"Cloud TTS ({c_prov}) đã cấu hình API Key.",
        }
    return check_voicestudio_connection(cfg)


def list_tts_profiles(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Lấy danh sách giọng đọc khả dụng theo nguồn TTS."""
    from app.tts.voicestudio_engine import get_voicestudio_profiles

    provider = str(cfg.get("tts_provider", "edge")).lower()
    if provider == "edge":
        return [
            {
                "id": "vi-VN-NamMinhNeural",
                "name": "Nam Minh (Giọng Nam trẻ trung, năng động - Khuyên dùng)",
                "provider": "edge",
            },
            {
                "id": "vi-VN-HoaiMyNeural",
                "name": "Hoài My (Giọng Nữ tự nhiên, truyền cảm - Thời trang/Mỹ phẩm)",
                "provider": "edge",
            },
        ]
    if provider == "cloud":
        return [
            {"id": "Kore", "name": "Gemini - Kore (Giọng Nữ năng lượng)", "provider": "cloud"},
            {"id": "Puck", "name": "Gemini - Puck (Giọng Nam sôi nổi)", "provider": "cloud"},
            {"id": "Aoede", "name": "Gemini - Aoede (Giọng Nữ tự nhiên)", "provider": "cloud"},
            {"id": "alloy", "name": "OpenAI - Alloy", "provider": "cloud"},
            {"id": "nova", "name": "OpenAI - Nova", "provider": "cloud"},
        ]
    return get_voicestudio_profiles(cfg)
