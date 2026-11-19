"""Quản lý Mẫu Template (Video quay mẫu + File ghi âm giọng thật).

Cho phép người dùng tạo mẫu video & giọng đọc một lần, sau đó chỉ cần thay ảnh sản phẩm
mới là hệ thống tự động sinh video hoàn chỉnh trong vài giây.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app import config as cfg_mod
from app.config import TEMPLATES_DIR, find_binary
from app.content import slugify_folder
from app.tts.base import get_wav_duration, normalize_audio_to_wav48k


def get_template_dir(template_slug: str) -> Path:
    slug = slugify_folder(template_slug)
    t_dir = TEMPLATES_DIR / slug
    t_dir.mkdir(parents=True, exist_ok=True)
    return t_dir


def list_templates() -> List[Dict[str, Any]]:
    """Liệt kê toàn bộ danh sách Mẫu Template hiện có."""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []

    for t_dir in sorted(TEMPLATES_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not t_dir.is_dir() or t_dir.name.startswith(("_", ".")):
            continue
        info = get_template_info(t_dir.name)
        if info:
            results.append(info)

    return results


def get_template_info(template_slug: str) -> Optional[Dict[str, Any]]:
    """Đọc thông tin chi tiết của 1 template."""
    slug = slugify_folder(template_slug)
    t_dir = TEMPLATES_DIR / slug
    if not t_dir.exists():
        return None

    cfg_file = t_dir / "template.json"
    data: Dict[str, Any] = {}
    if cfg_file.exists():
        try:
            data = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
        except Exception:
            data = {}

    name = str(data.get("name", "")).strip() or slug
    hook = str(data.get("hook", "")).strip() or "ĐÂY RỒI! MẪU SẢN PHẨM ĐANG BÁN CHẠY NHẤT!"
    doc = str(data.get("doc", "")).strip() or hook
    link = str(data.get("link", "")).strip()
    hashtag = str(data.get("hashtag", "")).strip() or "#xuhuong #fyp #tiktokshop"
    banner_duration = float(data.get("banner_duration", 6.5))

    video_file: Optional[Path] = None
    for ext in (".mp4", ".mov", ".webm", ".mkv"):
        vf = t_dir / f"video_mau{ext}"
        if vf.exists():
            video_file = vf
            break

    audio_file: Optional[Path] = None
    for ext in (".wav", ".mp3", ".m4a", ".aac"):
        af = t_dir / f"ghi_am_mau{ext}"
        if af.exists():
            audio_file = af
            break

    audio_duration = 0.0
    if audio_file and audio_file.suffix.lower() == ".wav":
        try:
            audio_duration = round(get_wav_duration(audio_file), 1)
        except Exception:
            pass

    from app.main import _rel_url

    return {
        "slug": slug,
        "name": name,
        "hook": hook,
        "doc": doc,
        "link": link,
        "hashtag": hashtag,
        "banner_duration": banner_duration,
        "audio_duration": audio_duration,
        "has_video": video_file is not None,
        "has_audio": audio_file is not None,
        "video_url": _rel_url(video_file) if video_file else None,
        "audio_url": _rel_url(audio_file) if audio_file else None,
        "video_filename": video_file.name if video_file else None,
        "audio_filename": audio_file.name if audio_file else None,
        "created_at": data.get("created_at", ""),
    }


def save_template_metadata(template_slug: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    slug = slugify_folder(template_slug)
    t_dir = get_template_dir(slug)
    cfg_file = t_dir / "template.json"
    existing: Dict[str, Any] = {}
    if cfg_file.exists():
        try:
            existing = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
        except Exception:
            pass

    existing.update(meta)
    existing["slug"] = slug
    existing["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    if "created_at" not in existing:
        existing["created_at"] = existing["updated_at"]

    cfg_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return existing


def delete_template(template_slug: str) -> bool:
    slug = slugify_folder(template_slug)
    t_dir = TEMPLATES_DIR / slug
    if t_dir.exists():
        shutil.rmtree(t_dir, ignore_errors=True)
        return True
    return False


def apply_template_to_product(
    template_slug: str,
    product_slug: str,
    product_title: Optional[str] = None,
    uploaded_images: Optional[List[Tuple[str, bytes]]] = None,
) -> Dict[str, Any]:
    """Tạo sản phẩm mới từ Template mẫu và chuẩn bị sẵn sàng để render."""
    t_info = get_template_info(template_slug)
    if not t_info:
        raise ValueError(f"Không tìm thấy Mẫu Template '{template_slug}'.")

    p_slug = slugify_folder(product_slug)
    p_dir = cfg_mod.SAN_PHAM_DIR / p_slug
    p_dir.mkdir(parents=True, exist_ok=True)
    v_dir = p_dir / "_video"
    v_dir.mkdir(parents=True, exist_ok=True)

    t_dir = TEMPLATES_DIR / t_info["slug"]

    # 1. Kế thừa video mẫu -> làm can_canh.mp4 của sản phẩm
    tpl_video: Optional[Path] = None
    for ext in (".mp4", ".mov", ".webm", ".mkv"):
        cand = t_dir / f"video_mau{ext}"
        if cand.exists():
            tpl_video = cand
            break

    if tpl_video and tpl_video.exists():
        dst_vid = p_dir / "can_canh.mp4"
        shutil.copy2(tpl_video, dst_vid)

    # 2. Kế thừa file ghi âm mẫu -> làm v1.wav của sản phẩm
    tpl_audio: Optional[Path] = None
    for ext in (".wav", ".mp3", ".m4a", ".aac"):
        cand = t_dir / f"ghi_am_mau{ext}"
        if cand.exists():
            tpl_audio = cand
            break

    if tpl_audio and tpl_audio.exists():
        dst_wav = v_dir / "v1.wav"
        if tpl_audio.suffix.lower() == ".wav":
            shutil.copy2(tpl_audio, dst_wav)
        else:
            normalize_audio_to_wav48k(tpl_audio, dst_wav)
        shutil.copy2(dst_wav, p_dir / "ghi_am.wav")

    # 3. Lưu ảnh sản phẩm mới
    saved_images: List[str] = []
    if uploaded_images:
        for idx, (filename, data) in enumerate(uploaded_images):
            ext = Path(filename).suffix.lower() or ".jpg"
            if idx == 0:
                dst_name = f"anh_trai{ext}"
            elif idx == 1:
                dst_name = f"anh_phai{ext}"
            else:
                dst_name = f"anh_{idx+1}{ext}"
            dst_path = p_dir / dst_name
            dst_path.write_bytes(data)
            saved_images.append(dst_name)

        # Nếu chỉ có 1 ảnh -> copy thêm sang anh_phai để 2 bên banner đều có ảnh
        if len(uploaded_images) == 1:
            first_ext = Path(uploaded_images[0][0]).suffix.lower() or ".jpg"
            right_path = p_dir / f"anh_phai{first_ext}"
            shutil.copy2(p_dir / f"anh_trai{first_ext}", right_path)
            saved_images.append(f"anh_phai{first_ext}")

    # 4. Tạo noi_dung.txt
    display_title = product_title or p_slug.replace("_", " ").title()
    content_lines = [
        f"=== SẢN PHẨM: {p_slug} ===",
        f"LINK: {t_info.get('link', '')}",
        f"TEN: {display_title}",
        f"HASHTAG: {t_info.get('hashtag', '#xuhuong #fyp #tiktokshop')}",
        "",
        "[VIDEO 1]",
        f"HOOK: {t_info.get('hook', '')}",
        f"DOC: {t_info.get('doc', t_info.get('hook', ''))}",
    ]
    (p_dir / "noi_dung.txt").write_text("\n".join(content_lines), encoding="utf-8-sig")

    # 5. Lưu thông tin liên kết template vào khung.json để ghi nhớ
    khung_path = p_dir / "khung.json"
    khung_data: Dict[str, Any] = {}
    if khung_path.exists():
        try:
            khung_data = json.loads(khung_path.read_text(encoding="utf-8-sig"))
        except Exception:
            khung_data = {}
    khung_data["template_slug"] = t_info["slug"]
    khung_data["banner_duration"] = t_info.get("banner_duration", 6.5)
    khung_path.write_text(json.dumps(khung_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "product": p_slug,
        "title": display_title,
        "template": t_info["slug"],
        "saved_images": saved_images,
    }
