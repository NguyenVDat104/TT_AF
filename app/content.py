"""Quản lý kịch bản (noi_dung.txt), tách kịch bản hàng loạt và tự động phân vai tư liệu sản phẩm."""

from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import SAN_PHAM_DIR, find_binary, load_config
from app.models import ProductContentData, VideoScript

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

SLOT_NAMES = ("anh_trai", "anh_phai", "can_canh")

# Mẫu chữ gợi ý trong ngoặc đơn cần loại bỏ khi đọc noi_dung.txt
_HINT_PAREN_RE = re.compile(
    r"\((?:lời đọc|câu đầu|ví dụ|điền|gợi ý|tối đa|khoảng\s*\d+|45\s*[-–]\s*65)[^)]*\)",
    re.IGNORECASE,
)


def slugify_folder(name: str, max_len: int = 60) -> str:
    """Chuyển tên bất kỳ sang tên thư mục không dấu an toàn (tối đa 60 ký tự)."""
    if not name:
        return "san_pham_moi"
    text = name.strip()
    text = text.replace("đ", "d").replace("Đ", "d")
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    ascii_text = re.sub(r"_+", "_", ascii_text).strip("_.")
    if not ascii_text:
        ascii_text = "san_pham_moi"
    return ascii_text[:max_len].rstrip("_")


def clean_script_line(text: str) -> str:
    """Loại bỏ các chú thích mẫu trong ngoặc đơn và khoảng trắng thừa."""
    cleaned = _HINT_PAREN_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_noi_dung(raw_text: str, slug: str = "") -> ProductContentData:
    """Đọc nội dung noi_dung.txt (chấp nhận BOM, CRLF, dòng tiếp nối)."""
    text = raw_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    ten = ""
    link = ""
    hashtag = ""
    videos_dict: Dict[int, Dict[str, str]] = {}
    current_video: Optional[int] = None
    last_field: Optional[str] = None  # "ten" | "link" | "hashtag" | "hook" | "doc"

    video_header_re = re.compile(r"^\[\s*VIDEO\s*(\d+)\s*\]$", re.IGNORECASE)
    key_re = re.compile(r"^(LINK|TEN|TÊN|HASHTAG|HOOK|DOC|ĐỌC)\s*:\s*(.*)$", re.IGNORECASE)

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        m_vid = video_header_re.match(line)
        if m_vid:
            current_video = int(m_vid.group(1))
            videos_dict.setdefault(current_video, {"hook": "", "doc": ""})
            last_field = None
            continue

        m_key = key_re.match(line)
        if m_key:
            key = m_key.group(1).upper()
            val = clean_script_line(m_key.group(2))
            if key == "LINK":
                link = val
                last_field = "link"
            elif key in ("TEN", "TÊN"):
                ten = val
                last_field = "ten"
            elif key == "HASHTAG":
                hashtag = val
                last_field = "hashtag"
            elif key == "HOOK":
                if current_video is None:
                    current_video = 1
                    videos_dict.setdefault(1, {"hook": "", "doc": ""})
                videos_dict[current_video]["hook"] = val
                last_field = "hook"
            elif key in ("DOC", "ĐỌC"):
                if current_video is None:
                    current_video = 1
                    videos_dict.setdefault(1, {"hook": "", "doc": ""})
                videos_dict[current_video]["doc"] = val
                last_field = "doc"
            continue

        # Dòng tiếp nối: gộp vào mục trước đó
        cont = clean_script_line(line)
        if not cont:
            continue
        if last_field == "doc" and current_video is not None:
            prev = videos_dict[current_video]["doc"]
            videos_dict[current_video]["doc"] = f"{prev} {cont}".strip()
        elif last_field == "hook" and current_video is not None:
            prev = videos_dict[current_video]["hook"]
            videos_dict[current_video]["hook"] = f"{prev} {cont}".strip()
        elif last_field == "ten":
            ten = f"{ten} {cont}".strip()
        elif last_field == "hashtag":
            hashtag = f"{hashtag} {cont}".strip()
        elif last_field == "link" and not link:
            link = cont

    videos: List[VideoScript] = []
    for v_no in sorted(videos_dict.keys()):
        hook_val = videos_dict[v_no].get("hook", "").strip()
        doc_val = videos_dict[v_no].get("doc", "").strip()
        # Video không có hook lẫn lời đọc bị loại
        if not hook_val and not doc_val:
            continue
        if not hook_val and doc_val:
            # Tự trích câu đầu làm hook nếu người dùng chỉ điền DOC
            first_sent = re.split(r"(?<=[.!?…])\s+", doc_val, maxsplit=1)[0]
            hook_val = first_sent[:140].strip()
        elif hook_val and not doc_val:
            doc_val = hook_val
        videos.append(VideoScript(video_no=v_no, hook=hook_val, doc=doc_val))

    return ProductContentData(
        slug=slug,
        ten=ten or slug,
        link=link,
        hashtag=hashtag,
        videos=videos,
        raw_text=text,
    )


def format_noi_dung(data: ProductContentData) -> str:
    """Chuyển ProductContentData thành định dạng chuẩn noi_dung.txt."""
    lines = [
        f"LINK: {data.link}",
        f"TEN: {data.ten}",
        f"HASHTAG: {data.hashtag}",
        "",
    ]
    videos = data.videos if data.videos else [
        VideoScript(video_no=1, hook="", doc=""),
        VideoScript(video_no=2, hook="", doc=""),
        VideoScript(video_no=3, hook="", doc=""),
    ]
    for v in videos:
        lines.append(f"[VIDEO {v.video_no}]")
        lines.append(f"HOOK: {v.hook}")
        lines.append(f"DOC: {v.doc}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def make_sample_noi_dung(ten_hien_thi: str = "Sản phẩm mới", link: str = "", hashtag: str = "") -> str:
    """Tạo nội dung mẫu noi_dung.txt khi tạo sản phẩm mới."""
    cfg = load_config()
    ht = hashtag or cfg.get("default_hashtags", "#xuhuong #fyp #tiktokshop")
    return (
        f"LINK: {link}\n"
        f"TEN: {ten_hien_thi}\n"
        f"HASHTAG: {ht}\n\n"
        "[VIDEO 1]\n"
        "HOOK: \n"
        "DOC: \n\n"
        "[VIDEO 2]\n"
        "HOOK: \n"
        "DOC: \n\n"
        "[VIDEO 3]\n"
        "HOOK: \n"
        "DOC: \n"
    )


def parse_bulk_scripts(bulk_text: str) -> List[ProductContentData]:
    """Tách kịch bản hàng loạt theo dòng === SẢN PHẨM: <ten_thu_muc> ===."""
    text = bulk_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    header_re = re.compile(
        r"^={2,}\s*(?:SẢN\s*PHẨM|SAN\s*PHAM)\s*:\s*(.+?)\s*={2,}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(header_re.finditer(text))
    results: List[ProductContentData] = []

    if not matches:
        # Nếu người dùng dán kịch bản của 1 sản phẩm mà quên dòng === SẢN PHẨM: ... ===
        parsed = parse_noi_dung(text, slug="")
        if parsed.videos or parsed.ten:
            parsed.slug = slugify_folder(parsed.ten or "san_pham_01")
            results.append(parsed)
        return results

    for idx, match in enumerate(matches):
        raw_name = match.group(1).strip()
        slug = slugify_folder(raw_name)
        start_pos = match.end()
        end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        block_text = text[start_pos:end_pos].strip()
        parsed = parse_noi_dung(block_text, slug=slug)
        if not parsed.ten or parsed.ten == slug:
            parsed.ten = raw_name
        parsed.raw_text = block_text + "\n"
        results.append(parsed)

    return results


def save_bulk_scripts(bulk_text: str) -> List[Dict[str, Any]]:
    """Tách kịch bản hàng loạt và ghi vào từng thư mục san_pham/<slug>/noi_dung.txt."""
    items = parse_bulk_scripts(bulk_text)
    saved_summary: List[Dict[str, Any]] = []
    for item in items:
        prod_dir = SAN_PHAM_DIR / item.slug
        prod_dir.mkdir(parents=True, exist_ok=True)
        (prod_dir / "_video").mkdir(parents=True, exist_ok=True)
        nd_path = prod_dir / "noi_dung.txt"
        content_to_write = item.raw_text if item.raw_text.strip() else format_noi_dung(item)
        nd_path.write_text(content_to_write, encoding="utf-8")
        saved_summary.append(
            {
                "slug": item.slug,
                "ten": item.ten,
                "video_count": len(item.videos),
                "hooks": [v.hook for v in item.videos],
            }
        )
    return saved_summary


def probe_media_duration(file_path: Path) -> float:
    """Đo thời lượng file video bằng ffprobe (trả về 0.0 nếu là ảnh hoặc lỗi)."""
    if file_path.suffix.lower() not in VIDEO_EXTS:
        return 0.0
    ffprobe_bin = find_binary("ffprobe")
    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=creationflags,
        )
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception:
        pass
    return 1.0


def load_khung_raw(prod_dir: Path) -> Dict[str, Any]:
    """Đọc file khung.json trong thư mục sản phẩm."""
    khung_path = prod_dir / "khung.json"
    if khung_path.exists():
        try:
            data = json.loads(khung_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def save_khung_raw(prod_dir: Path, data: Dict[str, Any]) -> None:
    """Ghi file khung.json an toàn."""
    khung_path = prod_dir / "khung.json"
    tmp_path = prod_dir / "khung.json.tmp"
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, khung_path)


def list_candidate_media_files(prod_dir: Path) -> List[Path]:
    """Liệt kê tất cả file ảnh/video hợp lệ ở cấp ngoài của thư mục sản phẩm."""
    if not prod_dir.exists():
        return []
    candidates: List[Path] = []
    for p in sorted(prod_dir.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.name.startswith("_") or p.name.startswith("."):
            continue
        if p.suffix.lower() in MEDIA_EXTS:
            candidates.append(p)
    return candidates


def resolve_product_media(prod_dir: Path) -> Dict[str, Optional[Path]]:
    """Tự động tìm hoặc phân vai tư liệu cho 3 ô (anh_trai, anh_phai, can_canh).

    Hỗ trợ cả 2 cách:
    1. Đặt tên truyền thống: anh_trai.*, anh_phai.*, can_canh.*
    2. Thả bất kỳ 3 file ảnh/video vào thư mục (không cần đổi tên):
       - Hệ thống kiểm tra bảng ánh xạ `files_map` trong `khung.json`.
       - Với các ô còn trống, tự động ưu tiên video dài nhất cho `can_canh`,
         và 2 file còn lại cho `anh_trai`, `anh_phai`.
    """
    result: Dict[str, Optional[Path]] = {
        "anh_trai": None,
        "anh_phai": None,
        "can_canh": None,
    }
    candidates = list_candidate_media_files(prod_dir)
    if not candidates:
        return result

    by_name = {p.name: p for p in candidates}
    used_files: set[str] = set()

    # Bước 1: Kiểm tra files_map đã lưu trong khung.json (cho phép đổi chỗ trên UI)
    khung_data = load_khung_raw(prod_dir)
    files_map = khung_data.get("files_map", {}) if isinstance(khung_data.get("files_map"), dict) else {}
    map_changed = False

    for slot in SLOT_NAMES:
        mapped_name = files_map.get(slot)
        if mapped_name and mapped_name in by_name and mapped_name not in used_files:
            result[slot] = by_name[mapped_name]
            used_files.add(mapped_name)

    # Bước 2: Tìm theo tên chuẩn (anh_trai.*, anh_phai.*, can_canh.*) cho các ô chưa có
    for slot in SLOT_NAMES:
        if result[slot] is not None:
            continue
        for p in candidates:
            if p.name in used_files:
                continue
            if p.stem.lower() == slot:
                result[slot] = p
                used_files.add(p.name)
                files_map[slot] = p.name
                map_changed = True
                break

    # Bước 3: Tự động phân vai cho các file có tên bất kỳ còn lại
    remaining = [p for p in candidates if p.name not in used_files]
    if remaining:
        # Nếu chưa có can_canh: ưu tiên chọn file video (nếu có nhiều video thì chọn file kích thước/thời lượng lớn nhất)
        if result["can_canh"] is None and remaining:
            video_candidates = [p for p in remaining if p.suffix.lower() in VIDEO_EXTS]
            if video_candidates:
                chosen_cc = max(video_candidates, key=lambda p: (probe_media_duration(p), p.stat().st_size))
            elif len(remaining) >= 3:
                chosen_cc = remaining[-1]
            else:
                chosen_cc = None

            if chosen_cc is not None:
                result["can_canh"] = chosen_cc
                used_files.add(chosen_cc.name)
                files_map["can_canh"] = chosen_cc.name
                remaining = [p for p in remaining if p.name not in used_files]
                map_changed = True

        # Gán tiếp vào anh_trai, anh_phai, rồi can_canh (nếu vẫn trống)
        for slot in ("anh_trai", "anh_phai", "can_canh"):
            if result[slot] is None and remaining:
                chosen = remaining.pop(0)
                result[slot] = chosen
                used_files.add(chosen.name)
                files_map[slot] = chosen.name
                map_changed = True

    if map_changed:
        khung_data["files_map"] = {k: v.name for k, v in result.items() if v is not None}
        try:
            save_khung_raw(prod_dir, khung_data)
        except Exception:
            pass

    return result


def swap_product_slots(slug: str, slot_a: str, slot_b: str) -> Dict[str, Optional[str]]:
    """Đổi chỗ 2 ô tư liệu (ví dụ anh_trai <-> anh_phai) ngay lập tức qua khung.json."""
    if slot_a not in SLOT_NAMES or slot_b not in SLOT_NAMES:
        raise ValueError("Tên ô không hợp lệ")
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise FileNotFoundError(f"Không tìm thấy sản phẩm: {slug}")

    media = resolve_product_media(prod_dir)
    khung_data = load_khung_raw(prod_dir)
    files_map: Dict[str, str] = {}
    for s in SLOT_NAMES:
        if media.get(s) is not None:
            files_map[s] = media[s].name  # type: ignore[union-attr]

    # Hoán đổi file ánh xạ
    val_a = files_map.get(slot_a)
    val_b = files_map.get(slot_b)
    if val_b:
        files_map[slot_a] = val_b
    else:
        files_map.pop(slot_a, None)

    if val_a:
        files_map[slot_b] = val_a
    else:
        files_map.pop(slot_b, None)

    khung_data["files_map"] = files_map

    # Hoán đổi cả tọa độ khung chỉnh tay nếu có
    frame_a = khung_data.get(slot_a)
    frame_b = khung_data.get(slot_b)
    if frame_b is not None:
        khung_data[slot_a] = frame_b
    else:
        khung_data.pop(slot_a, None)
    if frame_a is not None:
        khung_data[slot_b] = frame_a
    else:
        khung_data.pop(slot_b, None)

    save_khung_raw(prod_dir, khung_data)
    updated = resolve_product_media(prod_dir)
    return {k: (v.name if v else None) for k, v in updated.items()}


def assign_file_to_slot(slug: str, slot: str, filename: str) -> Dict[str, Optional[str]]:
    """Gán đích danh 1 file trong thư mục sản phẩm vào ô bất kỳ."""
    if slot not in SLOT_NAMES:
        raise ValueError("Tên ô không hợp lệ")
    prod_dir = SAN_PHAM_DIR / slug
    target_file = prod_dir / Path(filename).name
    if not target_file.exists():
        raise FileNotFoundError(f"Không tìm thấy file {filename}")

    media = resolve_product_media(prod_dir)
    khung_data = load_khung_raw(prod_dir)
    files_map: Dict[str, str] = {
        s: media[s].name for s in SLOT_NAMES if media.get(s) is not None  # type: ignore[union-attr]
    }

    # Nếu file đó đang nằm ở ô khác thì hoán đổi với ô hiện tại
    other_slot = next((s for s, fname in files_map.items() if fname == target_file.name and s != slot), None)
    prev_in_slot = files_map.get(slot)
    files_map[slot] = target_file.name
    if other_slot:
        if prev_in_slot:
            files_map[other_slot] = prev_in_slot
        else:
            files_map.pop(other_slot, None)

    khung_data["files_map"] = files_map
    save_khung_raw(prod_dir, khung_data)
    updated = resolve_product_media(prod_dir)
    return {k: (v.name if v else None) for k, v in updated.items()}
