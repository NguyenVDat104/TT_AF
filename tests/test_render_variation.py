"""Kiểm thử FFmpeg thực tế: ghép video chuẩn 1080x1920 30fps, biến thiên v1/v2, đốt phụ đề .ass & chạy clip thật ở ô Banner."""

import json
import math
import struct
import subprocess
import wave
from pathlib import Path
from PIL import Image, ImageDraw

from app.config import DEFAULT_CONFIG, find_binary
from app.render import compose_video
from app.subtitle import generate_closeup_ass_subtitle
from app.tts.base import WordTiming


def _make_sample_wav(path: Path, seconds: float = 4.0) -> None:
    rate = 48000
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        buf = bytearray(frames * 2)
        for i in range(frames):
            val = int(4000 * math.sin(2 * math.pi * 330.0 * (i / rate)))
            struct.pack_into("<h", buf, i * 2, val)
        wf.writeframes(buf)


def _make_sample_clip(path: Path, duration: float = 3.0, color: str = "blue") -> None:
    ffmpeg_bin = find_binary("ffmpeg")
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=720x1280:rate=30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def _probe_video_info(mp4_path: Path) -> dict:
    ffprobe_bin = find_binary("ffprobe")
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def test_compose_video_static_banner_and_variations(tmp_path: Path):
    prod_dir = tmp_path / "sp_render"
    prod_dir.mkdir()

    # Tạo 2 ảnh khác màu rõ rệt để kiểm chứng đảo ô ở v2
    img_left = Image.new("RGB", (720, 1280), (210, 40, 40))
    ImageDraw.Draw(img_left).rectangle([200, 400, 520, 900], fill=(255, 220, 220))
    img_left.save(prod_dir / "anh_trai.jpg")

    img_right = Image.new("RGB", (720, 1280), (40, 90, 210))
    ImageDraw.Draw(img_right).rectangle([200, 400, 520, 900], fill=(220, 230, 255))
    img_right.save(prod_dir / "anh_phai.jpg")

    _make_sample_clip(prod_dir / "can_canh.mp4", duration=2.5)

    wav_path = tmp_path / "voice.wav"
    _make_sample_wav(wav_path, seconds=8.0)

    words = [
        WordTiming("Chất", 7.0, 7.4),
        WordTiming("liệu", 7.4, 7.8),
        WordTiming("siêu", 7.8, 8.2),
        WordTiming("bền!", 8.2, 8.8),
    ]
    ass_path = tmp_path / "_sub.ass"

    cfg = dict(DEFAULT_CONFIG)
    cfg["min_seconds"] = 12.0  # Rút ngắn thời lượng test để chạy nhanh

    generate_closeup_ass_subtitle(words, banner_duration=6.5, total_duration=12.0, out_ass_path=ass_path, cfg=cfg)

    out_v1 = tmp_path / "v1.mp4"
    res_v1 = compose_video(
        prod_dir=prod_dir,
        video_no=1,
        hook_text="Đây rồi! Mẫu ốp lưng chống bẩn cực xịn anh em ơi!",
        out_mp4=out_v1,
        cfg=cfg,
        voice_wav=wav_path,
        voice_duration=8.0,
        hook_duration=5.5,
        subtitle_ass=ass_path,
        work_dir=tmp_path / "work_v1",
    )
    assert out_v1.exists() and out_v1.stat().st_size > 10_000
    info_v1 = _probe_video_info(out_v1)
    v_stream = next(s for s in info_v1["streams"] if s["codec_type"] == "video")
    a_stream = next(s for s in info_v1["streams"] if s["codec_type"] == "audio")
    assert v_stream["width"] == 1080
    assert v_stream["height"] == 1920
    assert v_stream["codec_name"] == "h264"
    assert v_stream["pix_fmt"] == "yuv420p"
    assert a_stream["codec_name"] == "aac"
    assert int(a_stream["sample_rate"]) == 48000

    # Kiểm tra biến thể v2 có đảo vị trí ô và màu dải chữ khác v1
    out_v2 = tmp_path / "v2.mp4"
    res_v2 = compose_video(
        prod_dir=prod_dir,
        video_no=2,
        hook_text="Mẫu thứ hai đảo bố cục chống trùng lặp!",
        out_mp4=out_v2,
        cfg=cfg,
        voice_wav=wav_path,
        voice_duration=8.0,
        hook_duration=5.5,
        subtitle_ass=ass_path,
        work_dir=tmp_path / "work_v2",
    )
    assert out_v2.exists()
    assert res_v2["variation"]["swap_slots"] is True
    assert res_v2["variation"]["band_hex"] != res_v1["variation"]["band_hex"]


def test_compose_video_with_live_clip_in_left_banner_slot(tmp_path: Path):
    """Kiểm thử tính năng Bản 4: Ô Banner Trái chạy Video Clip thật + Ô Phải là Ảnh + Cận cảnh là Ảnh."""
    prod_dir = tmp_path / "sp_live_slot"
    prod_dir.mkdir()

    _make_sample_clip(prod_dir / "anh_trai.mp4", duration=2.0)
    Image.new("RGB", (800, 1200), (60, 160, 90)).save(prod_dir / "anh_phai.jpg")
    Image.new("RGB", (1000, 1500), (140, 80, 180)).save(prod_dir / "can_canh.jpg")

    cfg = dict(DEFAULT_CONFIG)
    cfg["voice_enabled"] = False
    cfg["min_seconds"] = 10.0
    cfg["default_seconds"] = 10.0

    out_mp4 = tmp_path / "live_slot.mp4"
    compose_video(
        prod_dir=prod_dir,
        video_no=1,
        hook_text="Ô bên trái chạy video người dùng sản phẩm thật!",
        out_mp4=out_mp4,
        cfg=cfg,
        work_dir=tmp_path / "work_live",
    )
    assert out_mp4.exists() and out_mp4.stat().st_size > 10_000
    info = _probe_video_info(out_mp4)
    v_stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert v_stream["width"] == 1080
    assert v_stream["height"] == 1920
