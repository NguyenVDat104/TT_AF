"""Tạo phụ đề động (.ass - Advanced SubStation Alpha) kiểu CapCut cho nửa sau của video (hỗ trợ cả Windows & Linux)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from app.tts.base import WordTiming


def _hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """Chuyển mã màu #RRGGBB sang định dạng &HAABBGGRR của ASS."""
    h = (hex_color or "#FFE600").lstrip("#")
    if len(h) != 6:
        h = "FFE600"
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _format_ass_time(seconds: float) -> str:
    """Định dạng giây sang H:MM:SS.cc của ASS."""
    s = max(0.0, float(seconds))
    hours = int(s // 3600)
    minutes = int((s % 3600) // 60)
    secs = int(s % 60)
    centis = int(round((s - int(s)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def generate_closeup_ass_subtitle(
    word_timings: List[WordTiming],
    banner_duration: float,
    total_duration: float,
    out_ass_path: Path,
    cfg: Dict[str, Any],
) -> Path | None:
    """Sinh file phụ đề .ass chỉ xuất hiện từ thời điểm kết thúc banner (t >= banner_duration - 0.12s)."""
    if not cfg.get("subtitle_enabled", True) or not word_timings:
        return None

    cutoff = max(0.0, banner_duration - 0.12)
    closeup_words = [w for w in word_timings if w.end > cutoff and w.word.strip()]
    if not closeup_words:
        return None

    words_per_chunk = max(2, min(7, int(cfg.get("subtitle_words_per_chunk", 4))))
    font_size = max(36, min(78, int(cfg.get("subtitle_font_size", 52))))
    margin_v = max(120, min(600, int(cfg.get("subtitle_margin_v", 280))))
    primary_color = _hex_to_ass_color(str(cfg.get("subtitle_color", "#FFE600")), alpha=0)
    outline_color = "&H00000000"
    back_color = "&H64000000"

    # Trên Windows dùng Arial; trên Linux/Docker (Render) dùng DejaVu Sans hỗ trợ trọn dấu tiếng Việt
    default_font_family = "Arial" if os.name == "nt" else "DejaVu Sans"

    phrases: List[Dict[str, Any]] = []
    cur_words: List[WordTiming] = []

    for w in closeup_words:
        cur_words.append(w)
        ends_punct = w.word.endswith((".", "!", "?", ",", ";", ":", "…"))
        if len(cur_words) >= words_per_chunk or ends_punct:
            start_t = max(banner_duration, cur_words[0].start)
            end_t = min(total_duration, max(start_t + 0.25, cur_words[-1].end + 0.08))
            phrases.append(
                {
                    "text": " ".join(x.word for x in cur_words),
                    "start": start_t,
                    "end": end_t,
                }
            )
            cur_words = []

    if cur_words:
        start_t = max(banner_duration, cur_words[0].start)
        end_t = min(total_duration, max(start_t + 0.25, cur_words[-1].end + 0.12))
        phrases.append(
            {
                "text": " ".join(x.word for x in cur_words),
                "start": start_t,
                "end": end_t,
            }
        )

    for i in range(len(phrases) - 1):
        if phrases[i]["end"] > phrases[i + 1]["start"]:
            phrases[i]["end"] = max(phrases[i]["start"] + 0.15, phrases[i + 1]["start"] - 0.02)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTokSub,{default_font_family},{font_size},{primary_color},&H00FFFFFF,{outline_color},{back_color},-1,0,0,0,100,100,1,0,1,4.5,2.0,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header.strip()]
    for ph in phrases:
        t0 = _format_ass_time(ph["start"])
        t1 = _format_ass_time(ph["end"])
        clean_txt = _escape_ass_text(ph["text"].upper() if cfg.get("hook_uppercase", True) else ph["text"])
        anim_tag = r"{\fscx108\fscy108\t(0,75,\fscx100\fscy100)}"
        lines.append(f"Dialogue: 0,{t0},{t1},TikTokSub,,0,0,0,,{anim_tag}{clean_txt}")

    out_ass_path.parent.mkdir(parents=True, exist_ok=True)
    out_ass_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_ass_path
