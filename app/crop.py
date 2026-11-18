"""Nhận diện tự động vùng sản phẩm (Auto-Crop chống nhiễu khung Shopee) & toán học đặt khung."""

from __future__ import annotations

import hashlib
import math
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.config import TAM_DIR, find_binary
from app.content import VIDEO_EXTS, load_khung_raw, resolve_product_media, save_khung_raw

SLOT_DIMENSIONS: Dict[str, Tuple[int, int]] = {
    "anh_trai": (540, 1280),
    "anh_phai": (540, 1280),
    "can_canh": (1080, 1920),
}


def extract_video_frame(video_path: Path, timestamp: float = 0.5) -> Path:
    """Trích xuất khung hình tĩnh ở giây 0.5 từ file video (lùi về 0.0s nếu clip quá ngắn)."""
    TAM_DIR.mkdir(parents=True, exist_ok=True)
    stat = video_path.stat()
    key = f"{video_path.resolve()}_{stat.st_mtime_ns}_{stat.st_size}_{timestamp}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    out_jpg = TAM_DIR / f"frame_{digest}.jpg"
    if out_jpg.exists() and out_jpg.stat().st_size > 0:
        return out_jpg

    ffmpeg_bin = find_binary("ffmpeg")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    for ts in (timestamp, 0.0):
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{ts:.2f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_jpg),
        ]
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=15,
                creationflags=creationflags,
                check=False,
            )
            if out_jpg.exists() and out_jpg.stat().st_size > 0:
                return out_jpg
        except Exception:
            continue

    # Nếu vẫn không trích được (ví dụ môi trường test giả lập): tạo ảnh màu xám mặc định
    fallback = Image.new("RGB", (1080, 1920), (60, 60, 65))
    fallback.save(out_jpg, "JPEG", quality=85)
    return out_jpg


def load_image_for_media(media_path: Path) -> Image.Image:
    """Mở file ảnh (tự xoay EXIF) hoặc trích khung hình ở giây 0.5 nếu là video."""
    if media_path.suffix.lower() in VIDEO_EXTS:
        frame_path = extract_video_frame(media_path, 0.5)
        img = Image.open(frame_path)
    else:
        img = Image.open(media_path)
        img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = (len(sorted_vals) - 1) * max(0.0, min(1.0, p))
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def auto_detect_frame(
    img: Image.Image,
    slot_w: int = 540,
    slot_h: int = 1280,
) -> Dict[str, float]:
    """Nhận diện tự động vùng sản phẩm bằng Pillow + bộ lọc chống nhiễu khung Shopee.

    Quy trình:
    1. Thu ảnh về tối đa 160 px. Lấy màu nền bằng trung vị các điểm ảnh ở viền
       (ưu tiên viền trái/phải để tránh dải banner chữ trên/dưới của ảnh Shopee).
    2. Trọng số mỗi điểm = (0.65 * độ_khác_màu_nền + 0.35 * độ_mạnh_cạnh)
       nhân với hệ số ưu tiên vùng giữa (Rule-of-Thirds) và giảm 80% trọng số
       ở 12% mép trên/dưới nơi hay có chữ/khung khuyến mãi.
    3. Ngưỡng = max(phân vị 70%, 0.06, 25% giá trị lớn nhất).
    4. Vùng sản phẩm = phân vị 5%–95% của các điểm vượt ngưỡng; tâm = trung bình
       của trọng tâm và tâm hộp.
    5. Chọn z: ảnh gần đúng tỉ lệ ô (cắt mất <= 18%) -> z = 1. Nếu phủ kín vẫn
       thấy >= 88% vùng sản phẩm -> z = 1. Ngược lại thu nhỏ vừa để sản phẩm
       chiếm 94% ô (tối thiểu z = 0.45).
    """
    orig_w, orig_h = img.size
    if orig_w <= 0 or orig_h <= 0:
        return {"cx": 0.5, "cy": 0.5, "z": 1.0}

    scale = min(1.0, 160.0 / max(orig_w, orig_h))
    w = max(16, int(round(orig_w * scale)))
    h = max(16, int(round(orig_h * scale)))
    small = img.resize((w, h), Image.Resampling.BILINEAR)
    pixels = small.load()

    # 1. Màu nền = trung vị các điểm ảnh ở viền (lấy viền trái/phải + vùng ngoài)
    border_r: list[float] = []
    border_g: list[float] = []
    border_b: list[float] = []
    for x in range(w):
        for y in (0, 1, h - 2, h - 1):
            r, g, b = pixels[x, y]
            border_r.append(float(r))
            border_g.append(float(g))
            border_b.append(float(b))
    for y in range(2, h - 2):
        for x in (0, 1, w - 2, w - 1):
            r, g, b = pixels[x, y]
            border_r.append(float(r))
            border_g.append(float(g))
            border_b.append(float(b))

    border_r.sort()
    border_g.sort()
    border_b.sort()
    bg_r = _percentile(border_r, 0.5)
    bg_g = _percentile(border_g, 0.5)
    bg_b = _percentile(border_b, 0.5)

    # 2. Bản đồ cạnh (FIND_EDGES + MaxFilter 3, bỏ 3 px viền)
    gray = small.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(3))
    edge_px = edges.load()

    weights = [[0.0 for _ in range(w)] for _ in range(h)]
    flat_weights: list[float] = []
    max_w = 0.0

    for y in range(h):
        ny = (y + 0.5) / h
        # Giảm trọng số ở 12% mép trên/dưới để khử khung sale Shopee / watermark
        if ny < 0.12 or ny > 0.88:
            shopee_banner_factor = 0.20
        else:
            shopee_banner_factor = 1.0

        for x in range(w):
            nx = (x + 0.5) / w
            r, g, b = pixels[x, y]
            color_diff = math.sqrt((r - bg_r) ** 2 + (g - bg_g) ** 2 + (b - bg_b) ** 2) / 441.673

            if x < 3 or x >= w - 3 or y < 3 or y >= h - 3:
                edge_val = 0.0
            else:
                edge_val = edge_px[x, y] / 255.0

            # Hệ số ưu tiên vùng giữa (Gaussian nhẹ quanh tâm)
            dist_sq = ((nx - 0.5) / 0.42) ** 2 + ((ny - 0.5) / 0.42) ** 2
            center_prior = 0.45 + 0.55 * math.exp(-0.5 * dist_sq)

            w_val = (0.65 * color_diff + 0.35 * edge_val) * center_prior * shopee_banner_factor
            weights[y][x] = w_val
            flat_weights.append(w_val)
            if w_val > max_w:
                max_w = w_val

    if max_w <= 1e-4:
        return {"cx": 0.5, "cy": 0.5, "z": 1.0}

    flat_weights.sort()
    p70 = _percentile(flat_weights, 0.70)
    threshold = max(p70, 0.06, 0.25 * max_w)

    xs: list[float] = []
    ys: list[float] = []
    sum_w = 0.0
    sum_wx = 0.0
    sum_wy = 0.0

    for y in range(h):
        ny = (y + 0.5) / h
        for x in range(w):
            val = weights[y][x]
            if val >= threshold:
                nx = (x + 0.5) / w
                xs.append(nx)
                ys.append(ny)
                sum_w += val
                sum_wx += val * nx
                sum_wy += val * ny

    if not xs or sum_w <= 0:
        return {"cx": 0.5, "cy": 0.5, "z": 1.0}

    xs.sort()
    ys.sort()
    x0 = _percentile(xs, 0.05)
    x1 = _percentile(xs, 0.95)
    y0 = _percentile(ys, 0.05)
    y1 = _percentile(ys, 0.95)

    box_cx = 0.5 * (x0 + x1)
    box_cy = 0.5 * (y0 + y1)
    mass_cx = sum_wx / sum_w
    mass_cy = sum_wy / sum_w

    cx = max(0.05, min(0.95, 0.5 * (box_cx + mass_cx)))
    cy = max(0.05, min(0.95, 0.5 * (box_cy + mass_cy)))

    # 4. Chọn z theo đúng đặc tả
    s_cover = max(slot_w / orig_w, slot_h / orig_h)
    visible_w_ratio = min(1.0, (slot_w / s_cover) / orig_w)
    visible_h_ratio = min(1.0, (slot_h / s_cover) / orig_h)
    cut_loss = 1.0 - (visible_w_ratio * visible_h_ratio)

    obj_w = max(0.05, x1 - x0)
    obj_h = max(0.05, y1 - y0)

    # Kiểm tra ở z = 1 vùng sản phẩm có nằm trọn >= 88% trong ô không
    obj_fit_w = min(1.0, visible_w_ratio / obj_w)
    obj_fit_h = min(1.0, visible_h_ratio / obj_h)
    obj_visible_ratio = obj_fit_w * obj_fit_h

    if cut_loss <= 0.18 or obj_visible_ratio >= 0.88:
        z = 1.0
    else:
        needed_scale = min(
            (0.94 * visible_w_ratio) / obj_w,
            (0.94 * visible_h_ratio) / obj_h,
        )
        z = max(0.45, min(1.0, round(needed_scale, 3)))

    return {
        "cx": round(cx, 4),
        "cy": round(cy, 4),
        "z": round(z, 3),
    }


def compute_placement(
    img_w: int,
    img_h: int,
    slot_w: int,
    slot_h: int,
    cx: float = 0.5,
    cy: float = 0.5,
    z: float = 1.0,
) -> Dict[str, Any]:
    """Tính tỉ lệ s, kích thước (scaled_w, scaled_h) và vị trí (x, y) đặt ảnh vào ô.

    Công thức đồng nhất với giao diện xem trước:
    s = max(slot_w / img_w, slot_h / img_h) * z
    Vị trí sao cho điểm (cx, cy) trên ảnh gốc nằm ở giữa ô (slot_w/2, slot_h/2).
    Khi ảnh đủ phủ ô (scaled_w >= slot_w hoặc scaled_h >= slot_h) thì kẹp vị trí
    để không lộ khoảng trống.
    """
    cx = max(0.0, min(1.0, float(cx)))
    cy = max(0.0, min(1.0, float(cy)))
    z = max(0.35, min(3.5, float(z)))

    base_s = max(slot_w / max(1, img_w), slot_h / max(1, img_h))
    s = base_s * z
    scaled_w = max(2, int(round(img_w * s)))
    scaled_h = max(2, int(round(img_h * s)))
    # Đảm bảo chẵn pixel cho bộ mã hóa yuv420p của FFmpeg
    if scaled_w % 2 != 0:
        scaled_w += 1
    if scaled_h % 2 != 0:
        scaled_h += 1

    x = slot_w / 2.0 - cx * scaled_w
    y = slot_h / 2.0 - cy * scaled_h

    if scaled_w >= slot_w:
        x = max(float(slot_w - scaled_w), min(0.0, x))
    else:
        x = (slot_w - scaled_w) / 2.0

    if scaled_h >= slot_h:
        y = max(float(slot_h - scaled_h), min(0.0, y))
    else:
        y = (slot_h - scaled_h) / 2.0

    needs_blur_bg = scaled_w < slot_w or scaled_h < slot_h

    return {
        "s": s,
        "scaled_w": scaled_w,
        "scaled_h": scaled_h,
        "x": int(round(x)),
        "y": int(round(y)),
        "cx": cx,
        "cy": cy,
        "z": z,
        "needs_blur_bg": needs_blur_bg,
        "slot_w": slot_w,
        "slot_h": slot_h,
        "img_w": img_w,
        "img_h": img_h,
    }


def render_slot_image(
    img: Image.Image,
    slot_w: int,
    slot_h: int,
    cx: float = 0.5,
    cy: float = 0.5,
    z: float = 1.0,
) -> Image.Image:
    """Đặt ảnh vào ô (slot_w x slot_h) theo thông số (cx, cy, z).

    Nếu z < 1 (không phủ kín ô), phần trống được lấp bằng chính ảnh đó
    làm mờ Gaussian 28 và tối đi 25% (brightness 0.75).
    """
    img_rgb = img.convert("RGB")
    placement = compute_placement(img_rgb.width, img_rgb.height, slot_w, slot_h, cx, cy, z)

    if placement["needs_blur_bg"]:
        bg_scale = max(slot_w / img_rgb.width, slot_h / img_rgb.height)
        bg_w = max(slot_w, int(round(img_rgb.width * bg_scale)))
        bg_h = max(slot_h, int(round(img_rgb.height * bg_scale)))
        bg_resized = img_rgb.resize((bg_w, bg_h), Image.Resampling.BILINEAR)
        left = max(0, (bg_w - slot_w) // 2)
        top = max(0, (bg_h - slot_h) // 2)
        canvas = bg_resized.crop((left, top, left + slot_w, top + slot_h))
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=28))
        canvas = ImageEnhance.Brightness(canvas).enhance(0.75)
    else:
        canvas = Image.new("RGB", (slot_w, slot_h), (0, 0, 0))

    fg = img_rgb.resize((placement["scaled_w"], placement["scaled_h"]), Image.Resampling.LANCZOS)
    canvas.paste(fg, (placement["x"], placement["y"]))
    return canvas


def get_product_frames(prod_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Trả về thông số khung (cx, cy, z, use_video, manual, media_type...) cho cả 3 ô."""
    media_map = resolve_product_media(prod_dir)
    khung_raw = load_khung_raw(prod_dir)
    result: Dict[str, Dict[str, Any]] = {}

    for slot, (slot_w, slot_h) in SLOT_DIMENSIONS.items():
        media_path = media_map.get(slot)
        if media_path is None or not media_path.exists():
            result[slot] = {
                "cx": 0.5,
                "cy": 0.5,
                "z": 1.0,
                "use_video": True,
                "manual": False,
                "has_media": False,
                "media_type": None,
                "filename": None,
                "slot_w": slot_w,
                "slot_h": slot_h,
            }
            continue

        is_video = media_path.suffix.lower() in VIDEO_EXTS
        img = load_image_for_media(media_path)
        saved_slot = khung_raw.get(slot)

        if isinstance(saved_slot, dict) and "cx" in saved_slot and "cy" in saved_slot and "z" in saved_slot:
            cx = float(saved_slot["cx"])
            cy = float(saved_slot["cy"])
            z = float(saved_slot["z"])
            use_video = bool(saved_slot.get("use_video", True))
            manual = True
        else:
            auto_vals = auto_detect_frame(img, slot_w=slot_w, slot_h=slot_h)
            cx = auto_vals["cx"]
            cy = auto_vals["cy"]
            z = auto_vals["z"]
            use_video = True
            manual = False

        placement = compute_placement(img.width, img.height, slot_w, slot_h, cx, cy, z)
        result[slot] = {
            **placement,
            "use_video": use_video if is_video else False,
            "manual": manual,
            "has_media": True,
            "media_type": "video" if is_video else "image",
            "filename": media_path.name,
        }

    return result


def save_product_frames(
    prod_dir: Path,
    frames_update: Dict[str, Dict[str, Any]],
    reset_auto: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Lưu khung chỉnh tay vào khung.json (hoặc xóa khung chỉnh tay khi reset_auto=True)."""
    khung_raw = load_khung_raw(prod_dir)
    if reset_auto:
        for slot in SLOT_DIMENSIONS:
            khung_raw.pop(slot, None)
    else:
        for slot, vals in frames_update.items():
            if slot not in SLOT_DIMENSIONS:
                continue
            if vals is None or vals.get("reset"):
                khung_raw.pop(slot, None)
            else:
                khung_raw[slot] = {
                    "cx": round(float(vals.get("cx", 0.5)), 4),
                    "cy": round(float(vals.get("cy", 0.5)), 4),
                    "z": round(float(vals.get("z", 1.0)), 3),
                    "use_video": bool(vals.get("use_video", True)),
                }
    save_khung_raw(prod_dir, khung_raw)
    return get_product_frames(prod_dir)
