"""Dựng lớp Banner (_top.png, _band.png), biến thiên chống trùng lặp v1..v3 và ghép video FFmpeg (tối ưu RAM cho cả Windows & Render Free 512MB)."""

from __future__ import annotations

import gc
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.config import ASSETS_DIR, IS_LOW_MEMORY, TAM_DIR, find_binary
from app.content import VIDEO_EXTS, resolve_product_media
from app.crop import (
    get_product_frames,
    load_image_for_media,
    render_slot_image,
)

VIDEO_W = 1080
VIDEO_H = 1920
TOP_H = 1280
BAND_H = 640
SLOT_W = 540
SLOT_H = 1280
FPS = 30


def compute_video_durations(
    voice_enabled: bool,
    voice_duration: float,
    hook_duration: float,
    cfg: Dict[str, Any],
) -> Tuple[float, float, float]:
    """Tính (total_duration, banner_duration, closeup_duration)."""
    min_sec = float(cfg.get("min_seconds", 18.0))
    banner_min = float(cfg.get("banner_min_seconds", 6.5))
    banner_max = float(cfg.get("banner_max_seconds", 12.0))
    closeup_min = float(cfg.get("closeup_min_seconds", 5.0))
    default_sec = float(cfg.get("default_seconds", 19.0))

    if not voice_enabled or voice_duration <= 0.05:
        total = max(min_sec, default_sec)
        banner = round(total * 0.5, 2)
        closeup = round(total - banner, 2)
        return total, banner, closeup

    total = max(min_sec, round(voice_duration + 0.7, 2))
    banner = max(banner_min, min(banner_max, round(hook_duration + 0.5, 2)))
    if total - banner < closeup_min:
        banner = max(3.0, round(total - closeup_min, 2))
    closeup = round(total - banner, 2)
    return total, banner, closeup


def load_hook_font(font_size: int, cfg: Dict[str, Any]) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Tìm font chữ tiếng Việt đậm trên cả Windows và Linux (Render Docker)."""
    candidates: List[Path] = []
    custom_font = str(cfg.get("font_path", "")).strip()
    if custom_font:
        candidates.append(Path(custom_font))
    candidates.extend(
        [
            ASSETS_DIR / "font.ttf",
            # Windows system fonts
            Path(r"C:\Windows\Fonts\arialbd.ttf"),
            Path(r"C:\Windows\Fonts\segoeuib.ttf"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
            # Linux / Debian Docker fonts (hỗ trợ đầy đủ dấu tiếng Việt)
            Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
        ]
    )
    for fp in candidates:
        if fp.exists() and fp.is_file():
            try:
                return ImageFont.truetype(str(fp), font_size)
            except Exception:
                continue
    return ImageFont.load_default()


def _parse_hex_rgb(hex_color: str, default: Tuple[int, int, int] = (122, 16, 22)) -> Tuple[int, int, int]:
    h = (hex_color or "").strip().lstrip("#")
    if len(h) == 6:
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            pass
    return default


def _wrap_text_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> List[str]:
    words = [w for w in text.split() if w]
    if not words:
        return []
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        test_line = f"{cur} {w}"
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            cur = test_line
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def get_variation_params(video_no: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Lấy bộ thông số biến thiên chống trùng lặp cho v1, v2, v3."""
    anti_dup = bool(cfg.get("anti_duplicate_enabled", True))
    v_idx = int(video_no or 1)

    swap_slots = False
    band_hex = str(cfg.get("band_color", "#7A1016"))
    accent_bar_rgb = (255, 255, 255)
    closeup_offset = 0.0
    closeup_speed = 1.0
    eq_filter = ""

    if anti_dup:
        if v_idx == 2:
            swap_slots = bool(cfg.get("auto_swap_slots_v2", True))
            if cfg.get("auto_vary_band_color", True):
                band_hex = str(cfg.get("band_color_v2") or "#5C0B10")
            accent_bar_rgb = (255, 224, 102)
            closeup_offset = 1.2
            if cfg.get("auto_vary_closeup_speed", True):
                closeup_speed = 1.03
            eq_filter = "eq=saturation=1.04:contrast=1.02"
        elif v_idx >= 3:
            if cfg.get("auto_vary_band_color", True):
                band_hex = str(cfg.get("band_color_v3") or "#1E2229")
            accent_bar_rgb = (245, 230, 211)
            closeup_offset = 2.4
            if cfg.get("auto_vary_closeup_speed", True):
                closeup_speed = 1.05
            eq_filter = "eq=contrast=1.03:gamma=0.98"

    return {
        "swap_slots": swap_slots,
        "band_hex": band_hex,
        "accent_bar_rgb": accent_bar_rgb,
        "closeup_offset": closeup_offset,
        "closeup_speed": closeup_speed,
        "eq_filter": eq_filter,
    }


def make_band_overlay(
    hook_text: str,
    out_band_png: Path,
    cfg: Dict[str, Any],
    video_no: int = 1,
) -> Path:
    """Dựng Lớp 2 _band.png (1080 x 1920 RGBA)."""
    var = get_variation_params(video_no, cfg)
    band_rgb = _parse_hex_rgb(var["band_hex"])
    accent_rgb = var["accent_bar_rgb"]

    canvas = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    band_img = Image.new("RGBA", (VIDEO_W, BAND_H), (*band_rgb, 255))

    pattern_str = str(cfg.get("pattern_path", "")).strip()
    pattern_file = Path(pattern_str) if pattern_str else (ASSETS_DIR / "hoa_tiet.png")
    if pattern_file.exists() and pattern_file.is_file():
        try:
            pat = Image.open(pattern_file).convert("RGBA")
            pat_resized = pat.resize((VIDEO_W, BAND_H), Image.Resampling.BILINEAR)
            opacity = max(0.0, min(1.0, float(cfg.get("pattern_opacity", 0.18))))
            alpha_ch = pat_resized.getchannel("A").point(lambda p: int(p * opacity))
            pat_resized.putalpha(alpha_ch)
            band_img = Image.alpha_composite(band_img, pat_resized)
        except Exception:
            pass

    canvas.paste(band_img, (0, TOP_H))
    draw = ImageDraw.Draw(canvas)

    cream_color = (245, 230, 211, 255)
    draw.rectangle([0, TOP_H, VIDEO_W, TOP_H + 4], fill=cream_color)

    display_text = (hook_text or "").strip()
    if cfg.get("hook_uppercase", True):
        display_text = display_text.upper()

    if display_text:
        margin_left = 120
        margin_right = 80
        max_text_w = VIDEO_W - margin_left - margin_right
        start_size = max(40, int(cfg.get("hook_font_size", 60)))
        chosen_font = load_hook_font(start_size, cfg)
        lines: List[str] = []

        for sz in range(start_size, 39, -2):
            font_candidate = load_hook_font(sz, cfg)
            wrapped = _wrap_text_lines(draw, display_text, font_candidate, max_text_w)
            chosen_font = font_candidate
            lines = wrapped
            if len(wrapped) <= 4:
                break

        sample_bbox = draw.textbbox((0, 0), "Ág", font=chosen_font)
        line_h = max(32, sample_bbox[3] - sample_bbox[1])
        line_step = int(round(line_h * 1.25))
        total_text_h = line_h + max(0, len(lines) - 1) * line_step

        start_y = TOP_H + max(40, (BAND_H - total_text_h) // 2)

        bar_top = max(TOP_H + 24, start_y - 6)
        bar_bottom = min(VIDEO_H - 24, start_y + total_text_h + 10)
        draw.rectangle([75, bar_top, 79, bar_bottom], fill=(*accent_rgb, 255))

        y_cursor = start_y
        for line in lines:
            draw.text((margin_left + 2, y_cursor + 2), line, font=chosen_font, fill=(0, 0, 0, 95))
            draw.text((margin_left, y_cursor), line, font=chosen_font, fill=(255, 255, 255, 255))
            y_cursor += line_step

    out_band_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_band_png, "PNG")
    return out_band_png


def make_banner(
    prod_dir: Path,
    hook_text: str,
    cfg: Dict[str, Any],
    video_no: int = 1,
    out_dir: Optional[Path] = None,
) -> Dict[str, Path]:
    """Dựng _top.png (1080 x 1280), _band.png (1080 x 1920 RGBA) và _banner_preview.png (1080 x 1920)."""
    target_dir = out_dir or (prod_dir / "_video")
    target_dir.mkdir(parents=True, exist_ok=True)

    frames = get_product_frames(prod_dir)
    media_map = resolve_product_media(prod_dir)
    var = get_variation_params(video_no, cfg)

    left_key, right_key = ("anh_phai", "anh_trai") if var["swap_slots"] else ("anh_trai", "anh_phai")

    def _build_slot_img(slot_key: str) -> Image.Image:
        m_path = media_map.get(slot_key)
        f_info = frames.get(slot_key, {})
        if m_path is None or not m_path.exists():
            return Image.new("RGB", (SLOT_W, SLOT_H), (45, 45, 50))
        src_img = load_image_for_media(m_path)
        return render_slot_image(
            src_img,
            SLOT_W,
            SLOT_H,
            cx=float(f_info.get("cx", 0.5)),
            cy=float(f_info.get("cy", 0.5)),
            z=float(f_info.get("z", 1.0)),
        )

    left_img = _build_slot_img(left_key)
    right_img = _build_slot_img(right_key)

    top_img = Image.new("RGB", (VIDEO_W, TOP_H), (0, 0, 0))
    top_img.paste(left_img, (0, 0))
    top_img.paste(right_img, (SLOT_W, 0))

    top_path = target_dir / f"_top_v{video_no}.png"
    band_path = target_dir / f"_band_v{video_no}.png"
    preview_path = target_dir / f"_banner_preview_v{video_no}.png"

    top_img.save(top_path, "PNG")
    make_band_overlay(hook_text=hook_text, out_band_png=band_path, cfg=cfg, video_no=video_no)

    full_preview = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 255))
    full_preview.paste(top_img.convert("RGBA"), (0, 0))
    band_rgba = Image.open(band_path).convert("RGBA")
    full_preview = Image.alpha_composite(full_preview, band_rgba)
    full_preview.convert("RGB").save(preview_path, "PNG")

    return {
        "top_png": top_path,
        "band_png": band_path,
        "preview_png": preview_path,
    }


def _build_video_slot_filter(
    input_idx: int,
    placement: Dict[str, Any],
    duration: float,
    out_label: str,
    start_offset: float = 0.0,
    speed: float = 1.0,
    blur_setting: str = "28:2",
    darken_val: float = -0.10,
) -> str:
    """Sinh biểu thức filter_complex cho 1 ô là Video Clip (540x1280 hoặc 1080x1920)."""
    slot_w = int(placement["slot_w"])
    slot_h = int(placement["slot_h"])
    scaled_w = int(placement["scaled_w"])
    scaled_h = int(placement["scaled_h"])
    pos_x = int(placement["x"])
    pos_y = int(placement["y"])
    needs_blur = bool(placement["needs_blur_bg"])

    pts_expr = f"setpts=(PTS-STARTPTS)/{speed:.3f}" if abs(speed - 1.0) > 0.005 else "setpts=PTS-STARTPTS"
    raw_duration_needed = duration * max(1.0, speed) + start_offset + 0.15

    base_trim = (
        f"[{input_idx}:v]trim=start={start_offset:.2f}:end={raw_duration_needed:.2f},"
        f"{pts_expr},fps={FPS},trim=duration={duration:.2f},setpts=PTS-STARTPTS,setsar=1"
    )

    if not needs_blur:
        crop_x = max(0, -pos_x)
        crop_y = max(0, -pos_y)
        return (
            f"{base_trim},scale={scaled_w}:{scaled_h},"
            f"crop={slot_w}:{slot_h}:{crop_x}:{crop_y},setsar=1,format=rgba[{out_label}]"
        )

    bg_lbl = f"{out_label}_bg"
    fg_lbl = f"{out_label}_fg"
    bg_proc = f"{out_label}_bgp"
    fg_proc = f"{out_label}_fgp"
    return (
        f"{base_trim},split=2[{bg_lbl}][{fg_lbl}];"
        f"[{bg_lbl}]scale={slot_w}:{slot_h}:force_original_aspect_ratio=increase,"
        f"crop={slot_w}:{slot_h},boxblur={blur_setting},eq=brightness={darken_val:.2f}[{bg_proc}];"
        f"[{fg_lbl}]scale={scaled_w}:{scaled_h},setsar=1[{fg_proc}];"
        f"[{bg_proc}][{fg_proc}]overlay={pos_x}:{pos_y}:format=auto,setsar=1,format=rgba[{out_label}]"
    )


def compose_video(
    prod_dir: Path,
    video_no: int,
    hook_text: str,
    out_mp4: Path,
    cfg: Dict[str, Any],
    voice_wav: Optional[Path] = None,
    voice_duration: float = 0.0,
    hook_duration: float = 0.0,
    subtitle_ass: Optional[Path] = None,
    work_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Ráp video hoàn chỉnh 1080x1920 30fps bằng 1 lệnh FFmpeg filter_complex.

    Khi chạy ở chế độ tiết kiệm RAM (Render Free 512MB):
    - Thu gom rác bộ nhớ Pillow (gc.collect) trước khi gọi FFmpeg.
    - Giới hạn luồng xử lý (-threads 1, -filter_threads 1) và dùng preset ultrafast + rc-lookahead=10
      giúp đỉnh tiêu thụ RAM của cả Python + FFmpeg giữ ở mức ~190–250 MB (không bị OOM Killed).
    """
    w_dir = work_dir or (TAM_DIR / f"render_{prod_dir.name}_v{video_no}")
    w_dir.mkdir(parents=True, exist_ok=True)

    voice_enabled = bool(cfg.get("voice_enabled", True)) and voice_wav is not None and voice_wav.exists()
    total_dur, banner_dur, closeup_dur = compute_video_durations(
        voice_enabled=voice_enabled,
        voice_duration=voice_duration,
        hook_duration=hook_duration,
        cfg=cfg,
    )

    banner_files = make_banner(
        prod_dir=prod_dir,
        hook_text=hook_text,
        cfg=cfg,
        video_no=video_no,
        out_dir=w_dir,
    )
    top_png = banner_files["top_png"]
    band_png = banner_files["band_png"]

    frames = get_product_frames(prod_dir)
    media_map = resolve_product_media(prod_dir)
    var = get_variation_params(video_no, cfg)

    left_key, right_key = ("anh_phai", "anh_trai") if var["swap_slots"] else ("anh_trai", "anh_phai")
    left_media = media_map.get(left_key)
    right_media = media_map.get(right_key)
    closeup_media = media_map.get("can_canh")

    if closeup_media is None or not closeup_media.exists():
        raise FileNotFoundError(f"Sản phẩm {prod_dir.name} thiếu tư liệu cận cảnh (can_canh).")

    left_is_live_clip = (
        left_media is not None
        and left_media.suffix.lower() in VIDEO_EXTS
        and bool(frames.get(left_key, {}).get("use_video", True))
    )
    right_is_live_clip = (
        right_media is not None
        and right_media.suffix.lower() in VIDEO_EXTS
        and bool(frames.get(right_key, {}).get("use_video", True))
    )
    closeup_is_clip = closeup_media.suffix.lower() in VIDEO_EXTS

    inputs: List[str] = []
    filter_parts: List[str] = []
    input_counter = 0

    def _add_input(args_list: List[str]) -> int:
        nonlocal input_counter
        inputs.extend(args_list)
        idx = input_counter
        input_counter += 1
        return idx

    banner_zoom_on = bool(cfg.get("banner_zoom", True))
    low_mem = bool(cfg.get("low_memory_mode", IS_LOW_MEMORY))

    # 1. Nhánh Banner nửa đầu [v_banner]
    if not left_is_live_clip and not right_is_live_clip:
        idx_top = _add_input(["-loop", "1", "-t", f"{banner_dur:.2f}", "-r", str(FPS), "-i", str(top_png.resolve())])
        idx_band = _add_input(["-loop", "1", "-t", f"{banner_dur:.2f}", "-r", str(FPS), "-i", str(band_png.resolve())])
        if banner_zoom_on:
            filter_parts.append(
                f"[{idx_top}:v]scale=w='trunc(1080*(1+0.04*t/{banner_dur:.2f})/2)*2':"
                f"h='trunc(1280*(1+0.04*t/{banner_dur:.2f})/2)*2':eval=frame,"
                f"crop=1080:1280,pad=1080:1920:0:0:black,setsar=1[top_z];"
                f"[top_z][{idx_band}:v]overlay=0:0:format=auto,fps={FPS},format=rgba,setsar=1[v_banner]"
            )
        else:
            filter_parts.append(
                f"[{idx_top}:v]pad=1080:1920:0:0:black,setsar=1[top_z];"
                f"[top_z][{idx_band}:v]overlay=0:0:format=auto,fps={FPS},format=rgba,setsar=1[v_banner]"
            )
    else:
        slot_labels: List[str] = []
        for pos_tag, s_key, is_clip, m_path in (
            ("left", left_key, left_is_live_clip, left_media),
            ("right", right_key, right_is_live_clip, right_media),
        ):
            lbl = f"slot_{pos_tag}"
            slot_labels.append(lbl)
            f_info = frames.get(s_key, {})
            if is_clip and m_path is not None:
                idx_s = _add_input(["-stream_loop", "-1", "-i", str(m_path.resolve())])
                filter_parts.append(
                    _build_video_slot_filter(
                        input_idx=idx_s,
                        placement=f_info,
                        duration=banner_dur,
                        out_label=lbl,
                        start_offset=0.0,
                        speed=1.0,
                    )
                )
            else:
                static_slot_png = w_dir / f"_slot_{pos_tag}_v{video_no}.png"
                src_im = (
                    load_image_for_media(m_path)
                    if (m_path and m_path.exists())
                    else Image.new("RGB", (SLOT_W, SLOT_H), (45, 45, 50))
                )
                slot_rendered = render_slot_image(
                    src_im,
                    SLOT_W,
                    SLOT_H,
                    cx=float(f_info.get("cx", 0.5)),
                    cy=float(f_info.get("cy", 0.5)),
                    z=float(f_info.get("z", 1.0)),
                )
                slot_rendered.save(static_slot_png, "PNG")
                idx_s = _add_input(
                    ["-loop", "1", "-t", f"{banner_dur:.2f}", "-r", str(FPS), "-i", str(static_slot_png.resolve())]
                )
                if banner_zoom_on:
                    filter_parts.append(
                        f"[{idx_s}:v]scale=w='trunc(540*(1+0.04*t/{banner_dur:.2f})/2)*2':"
                        f"h='trunc(1280*(1+0.04*t/{banner_dur:.2f})/2)*2':eval=frame,"
                        f"crop=540:1280,fps={FPS},format=rgba,setsar=1[{lbl}]"
                    )
                else:
                    filter_parts.append(f"[{idx_s}:v]fps={FPS},format=rgba,setsar=1[{lbl}]")

        idx_band = _add_input(["-loop", "1", "-t", f"{banner_dur:.2f}", "-r", str(FPS), "-i", str(band_png.resolve())])
        filter_parts.append(
            f"[{slot_labels[0]}][{slot_labels[1]}]hstack=inputs=2,pad=1080:1920:0:0:black,setsar=1[top_comb];"
            f"[top_comb][{idx_band}:v]overlay=0:0:format=auto,fps={FPS},format=rgba,setsar=1[v_banner]"
        )

    # 2. Nhánh Cận cảnh nửa sau [v_closeup]
    cc_frame = frames.get("can_canh", {})
    if closeup_is_clip:
        idx_cc = _add_input(["-stream_loop", "-1", "-i", str(closeup_media.resolve())])
        filter_parts.append(
            _build_video_slot_filter(
                input_idx=idx_cc,
                placement=cc_frame,
                duration=closeup_dur,
                out_label="v_closeup",
                start_offset=float(var["closeup_offset"]),
                speed=float(var["closeup_speed"]),
                blur_setting="20:1" if low_mem else "30:2",
                darken_val=-0.08,
            )
        )
    else:
        cc_png = w_dir / f"_closeup_v{video_no}.png"
        cc_img = load_image_for_media(closeup_media)
        cc_rendered = render_slot_image(
            cc_img,
            VIDEO_W,
            VIDEO_H,
            cx=float(cc_frame.get("cx", 0.5)),
            cy=float(cc_frame.get("cy", 0.5)),
            z=float(cc_frame.get("z", 1.0)),
        )
        cc_rendered.save(cc_png, "PNG")
        idx_cc = _add_input(["-loop", "1", "-t", f"{closeup_dur:.2f}", "-r", str(FPS), "-i", str(cc_png.resolve())])
        filter_parts.append(
            f"[{idx_cc}:v]scale=w='trunc(1080*(1+0.12*t/{closeup_dur:.2f})/2)*2':"
            f"h='trunc(1920*(1+0.12*t/{closeup_dur:.2f})/2)*2':eval=frame,"
            f"crop=1080:1920,fps={FPS},format=rgba,setsar=1[v_closeup]"
        )

    # 3. Nối 2 đoạn + Làm nét unsharp + Biến thiên màu + Đốt phụ đề động .ass
    sharpen_val = max(0.0, min(2.0, float(cfg.get("sharpen", 0.5))))
    post_filters: List[str] = [f"unsharp=5:5:{sharpen_val:.2f}:5:5:0.0"]
    if var["eq_filter"]:
        post_filters.append(var["eq_filter"])

    if subtitle_ass is not None and subtitle_ass.exists() and cfg.get("subtitle_enabled", True):
        local_ass = w_dir / f"_sub_v{video_no}.ass"
        if subtitle_ass.resolve() != local_ass.resolve():
            local_ass.write_bytes(subtitle_ass.read_bytes())
        post_filters.append(f"ass={local_ass.name}")

    post_filters.append("format=yuv420p")
    post_chain = ",".join(post_filters)
    filter_parts.append(
        f"[v_banner]setsar=1[v_ban_sar];[v_closeup]setsar=1[v_cc_sar];"
        f"[v_ban_sar][v_cc_sar]concat=n=2:v=1:a=0,{post_chain}[v_out]"
    )

    # 4. Nhánh Âm thanh [a_out]
    music_str = str(cfg.get("music_path", "")).strip()
    music_file = Path(music_str) if music_str else None
    has_music = music_file is not None and music_file.exists() and music_file.is_file()
    music_vol = max(0.0, min(1.0, float(cfg.get("music_volume", 0.12))))

    if voice_enabled and voice_wav is not None:
        idx_voice = _add_input(["-i", str(voice_wav.resolve())])
        if has_music and music_file is not None:
            idx_music = _add_input(["-stream_loop", "-1", "-i", str(music_file.resolve())])
            filter_parts.append(
                f"[{idx_voice}:a]apad=whole_dur={total_dur:.2f}[a_v];"
                f"[{idx_music}:a]atrim=0:{total_dur:.2f},volume={music_vol:.2f}[a_m];"
                f"[a_v][a_m]amix=inputs=2:duration=first:normalize=0,aresample=48000[a_out]"
            )
        else:
            filter_parts.append(
                f"[{idx_voice}:a]apad=whole_dur={total_dur:.2f},atrim=0:{total_dur:.2f},aresample=48000[a_out]"
            )
    elif has_music and music_file is not None:
        idx_music = _add_input(["-stream_loop", "-1", "-i", str(music_file.resolve())])
        filter_parts.append(
            f"[{idx_music}:a]atrim=0:{total_dur:.2f},volume={music_vol:.2f},aresample=48000[a_out]"
        )
    else:
        idx_sil = _add_input(
            ["-f", "lavfi", "-t", f"{total_dur:.2f}", "-i", "anullsrc=channel_layout=mono:sample_rate=48000"]
        )
        filter_parts.append(f"[{idx_sil}:a]atrim=0:{total_dur:.2f}[a_out]")

    filter_complex_str = ";".join(filter_parts)

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    tmp_mp4 = out_mp4.with_suffix(".tmp.mp4")
    if tmp_mp4.exists():
        tmp_mp4.unlink(missing_ok=True)

    encoder = str(cfg.get("video_encoder", "libx264")).strip() or "libx264"
    crf_val = int(cfg.get("crf", 21 if low_mem else 20))

    thread_global_args: List[str] = []
    if low_mem:
        thread_global_args = ["-filter_threads", "1", "-filter_complex_threads", "1"]
        v_codec_args = [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            str(crf_val),
            "-threads",
            "1",
            "-x264-params",
            "rc-lookahead=10:ref=1:bframes=0:threads=1",
        ]
    elif encoder == "h264_nvenc":
        v_codec_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(crf_val)]
    else:
        v_codec_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf_val)]

    # Giải phóng bộ nhớ đệm ảnh của Python trước khi khởi chạy tiến trình FFmpeg
    gc.collect()

    ffmpeg_bin = find_binary("ffmpeg")
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        *thread_global_args,
        *inputs,
        "-filter_complex",
        filter_complex_str,
        "-map",
        "[v_out]",
        "-map",
        "[a_out]",
        *v_codec_args,
        "-r",
        str(FPS),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "48000",
        "-t",
        f"{total_dur:.2f}",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        str(tmp_mp4.resolve()),
    ]

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    # Trên gói Render Free 0.1 CPU, cho phép timeout tối đa 900s để không ngắt nhầm khi CPU bị throttle
    timeout_sec = 900 if low_mem else 300
    res = subprocess.run(
        cmd,
        cwd=str(w_dir),
        capture_output=True,
        timeout=timeout_sec,
        creationflags=creationflags,
        check=False,
    )

    if res.returncode != 0 or not tmp_mp4.exists() or tmp_mp4.stat().st_size == 0:
        err_msg = res.stderr.decode("utf-8", errors="ignore")[-500:]
        raise RuntimeError(f"FFmpeg thất bại (mã {res.returncode}): {err_msg}")

    os.replace(tmp_mp4, out_mp4)
    return {
        "mp4_path": out_mp4,
        "total_duration": total_dur,
        "banner_duration": banner_dur,
        "closeup_duration": closeup_dur,
        "variation": var,
    }
