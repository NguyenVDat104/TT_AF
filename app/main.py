"""Máy chủ FastAPI (hỗ trợ cả Local 127.0.0.1:8765 & Cloud Render.com): Basic Auth, HTTP Range, Tải MP4/ZIP."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import secrets
import shutil
import subprocess
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app import config as cfg_mod
from app.config import (
    PROMPT_TEMPLATE_PATH,
    STATIC_DIR,
    ensure_directories,
    load_config,
    save_config,
)
from app.content import (
    MEDIA_EXTS,
    SLOT_NAMES,
    VIDEO_EXTS,
    assign_file_to_slot,
    list_candidate_media_files,
    make_sample_noi_dung,
    parse_bulk_scripts,
    parse_noi_dung,
    resolve_product_media,
    save_bulk_scripts,
    slugify_folder,
    swap_product_slots,
)
from app.crop import (
    get_product_frames,
    load_image_for_media,
    save_product_frames,
)
from app.models import (
    AssignFileSlotRequest,
    BulkScriptRequest,
    NewProductRequest,
    OpenFolderRequest,
    QueueControlRequest,
    RenderRequest,
    SaveContentRequest,
    SaveFramesRequest,
    SwapSlotsRequest,
    VideoReviewRequest,
    VoiceTestRequest,
)
from app.queue_worker import (
    load_product_status,
    queue_manager,
    review_product_video,
)
from app.render import make_banner
from app.tts import check_tts_status, list_tts_profiles, synthesize_test_sentence

# Biến giữ tương thích cho kiểm thử monkeypatch
BASE_DIR = cfg_mod.DATA_ROOT
SAN_PHAM_DIR = cfg_mod.SAN_PHAM_DIR
SAN_SANG_DANG_DIR = cfg_mod.SAN_SANG_DANG_DIR
TAM_DIR = cfg_mod.TAM_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_directories()
    load_config()
    queue_manager.recover_on_startup()
    queue_manager.start_worker()
    yield
    queue_manager.stop_worker()


app = FastAPI(
    title="Xưởng Video TikTok Affiliate (Bản Cloud & Local 1.4)",
    version="1.4.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    """Bảo vệ bằng mật khẩu (HTTP Basic Auth) khi đặt biến môi trường APP_PASSWORD trên Render."""
    app_password = os.environ.get("APP_PASSWORD", "").strip()
    if not app_password or request.url.path == "/healthz":
        return await call_next(request)

    expected_user = os.environ.get("APP_USER", "").strip()
    auth_header = request.headers.get("Authorization", "")
    authorized = False

    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:].strip()).decode("utf-8")
            username, password = decoded.split(":", 1)
            pass_ok = secrets.compare_digest(password, app_password)
            user_ok = True if not expected_user else secrets.compare_digest(username, expected_user)
            authorized = pass_ok and user_ok
        except Exception:
            authorized = False

    if not authorized:
        return Response(
            content="Vui lòng đăng nhập mật khẩu quản trị Xưởng Video TikTok.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Xuong Video TikTok"'},
        )

    return await call_next(request)


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": f"Dữ liệu gửi lên không hợp lệ: {exc.errors()}"})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": str(exc)})


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/healthz")
async def healthcheck():
    """Cổng kiểm tra sức khỏe cho Render.com và dịch vụ giữ thức UptimeRobot."""
    st = queue_manager.get_status()
    return {
        "status": "ok",
        "busy": st["current"] is not None,
        "queue_length": st["queue_length"],
    }


def _safe_resolve_under_base(rel_path: str) -> Path:
    """Chặn truy cập đi ra ngoài thư mục dữ liệu gốc (Path Traversal Protection)."""
    cleaned = rel_path.lstrip("/\\")
    base_resolved = BASE_DIR.resolve()
    candidate = (base_resolved / cleaned).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise HTTPException(status_code=403, detail="Truy cập đường dẫn ngoài thư mục gốc bị từ chối.")
    return candidate


def _make_preview_jpeg(media_path: Path, max_dim: int = 1200) -> Path:
    """Tạo ảnh xem trước tối đa 1200 px cho ảnh hoặc video."""
    TAM_DIR.mkdir(parents=True, exist_ok=True)
    st = media_path.stat()
    sig = f"{media_path.resolve()}_{st.st_mtime_ns}_{st.st_size}_{max_dim}"
    digest = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]
    out_jpg = TAM_DIR / f"prev_{digest}.jpg"
    if out_jpg.exists() and out_jpg.stat().st_size > 0:
        return out_jpg

    img = load_image_for_media(media_path)
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / float(max(w, h))
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    img.save(out_jpg, "JPEG", quality=86)
    return out_jpg


def _open_in_explorer(folder_path: Path) -> None:
    folder_path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt" and not cfg_mod.IS_CLOUD:
        subprocess.Popen(["explorer", str(folder_path.resolve())])


def _rel_url(path: Path) -> str:
    rel = path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    mtime = int(path.stat().st_mtime) if path.exists() else 0
    return f"/files/{quote(rel, safe='/')}?v={mtime}"


def _build_product_summary(prod_dir: Path) -> Dict[str, Any]:
    slug = prod_dir.name
    nd_path = prod_dir / "noi_dung.txt"
    has_noi_dung = nd_path.exists()
    parsed = (
        parse_noi_dung(nd_path.read_text(encoding="utf-8-sig"), slug=slug)
        if has_noi_dung
        else parse_noi_dung("", slug=slug)
    )

    media_map = resolve_product_media(prod_dir)
    all_files = [p.name for p in list_candidate_media_files(prod_dir)]
    status_data = load_product_status(prod_dir).get("videos", {})

    slots_info: Dict[str, Any] = {}
    for slot in SLOT_NAMES:
        m_path = media_map.get(slot)
        if m_path and m_path.exists():
            is_vid = m_path.suffix.lower() in VIDEO_EXTS
            slots_info[slot] = {
                "present": True,
                "filename": m_path.name,
                "media_type": "video" if is_vid else "image",
                "url": _rel_url(m_path),
                "thumb_url": f"{_rel_url(m_path)}&preview=1",
            }
        else:
            slots_info[slot] = {
                "present": False,
                "filename": None,
                "media_type": None,
                "url": None,
                "thumb_url": None,
            }

    has_all_media = all(slots_info[s]["present"] for s in SLOT_NAMES)
    has_scripts = len(parsed.videos) > 0
    ready_to_render = has_all_media and has_scripts

    script_map = {v.video_no: v for v in parsed.videos}
    video_nos = sorted(script_map.keys()) if script_map else [1, 2, 3]

    videos_list: List[Dict[str, Any]] = []
    for v_no in video_nos:
        sc = script_map.get(v_no)
        st_entry = status_data.get(str(v_no), {}) if isinstance(status_data.get(str(v_no)), dict) else {}
        mp4_path = prod_dir / "_video" / f"v{v_no}.mp4"
        mp4_exists = mp4_path.exists() and mp4_path.stat().st_size > 0
        cur_state = str(st_entry.get("state", "chua_lam"))
        if cur_state in ("cho_duyet", "da_duyet") and not mp4_exists:
            cur_state = "chua_lam"

        dl_url = f"/api/download/video?product={quote(slug)}&video_no={v_no}" if mp4_exists else None

        videos_list.append(
            {
                "video_no": v_no,
                "has_script": sc is not None,
                "hook": sc.hook if sc else "",
                "doc": sc.doc if sc else "",
                "state": cur_state,
                "error": st_entry.get("error", ""),
                "duration": st_entry.get("duration"),
                "banner_duration": st_entry.get("banner_duration"),
                "tts_provider": st_entry.get("tts_provider"),
                "render_seconds": st_entry.get("render_seconds"),
                "updated_at": st_entry.get("updated_at"),
                "video_url": _rel_url(mp4_path) if mp4_exists else None,
                "download_url": dl_url,
                "post_slot_hint": st_entry.get("post_slot_hint", ""),
            }
        )

    return {
        "slug": slug,
        "ten": parsed.ten or slug,
        "link": parsed.link,
        "hashtag": parsed.hashtag,
        "has_noi_dung": has_noi_dung and has_scripts,
        "has_all_media": has_all_media,
        "ready_to_render": ready_to_render,
        "slots": slots_info,
        "candidate_files": all_files,
        "has_manual_frames": (prod_dir / "khung.json").exists(),
        "videos": videos_list,
    }


@app.get("/", response_class=HTMLResponse)
async def index_page():
    html_file = STATIC_DIR / "index.html"
    if not html_file.exists():
        return HTMLResponse("<h1>Đang khởi tạo giao diện...</h1>")
    return HTMLResponse(html_file.read_text(encoding="utf-8"))


@app.get("/files/{file_path:path}")
async def serve_file_with_range(
    file_path: str,
    request: Request,
    preview: int = Query(default=0),
):
    """Phục vụ file trong thư mục gốc, hỗ trợ HTTP Range (206) để tua video mượt và preview ảnh."""
    target = _safe_resolve_under_base(file_path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file yêu cầu.")

    if preview == 1 and target.suffix.lower() in MEDIA_EXTS:
        jpg_prev = _make_preview_jpeg(target, max_dim=1200)
        return FileResponse(str(jpg_prev), media_type="image/jpeg")

    file_size = target.stat().st_size
    content_type, _ = mimetypes.guess_type(str(target))
    content_type = content_type or "application/octet-stream"

    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(
            str(target),
            media_type=content_type,
            headers={"Accept-Ranges": "bytes"},
        )

    try:
        unit, ranges_str = range_header.strip().split("=", 1)
        if unit.lower() != "bytes":
            raise ValueError("Invalid unit")
        start_str, end_str = ranges_str.split("-", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
    except Exception:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    if start >= file_size or start < 0:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    end = min(end, file_size - 1)
    chunk_len = end - start + 1

    def _iter_file(path: Path, offset: int, length: int, block_size: int = 256 * 1024):
        with open(path, "rb") as f:
            f.seek(offset)
            remaining = length
            while remaining > 0:
                data = f.read(min(block_size, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_len),
    }
    return StreamingResponse(
        _iter_file(target, start, chunk_len),
        status_code=206,
        media_type=content_type,
        headers=headers,
    )


@app.get("/api/download/video")
async def api_download_single_video(
    product: Optional[str] = Query(default=None),
    video_no: Optional[int] = Query(default=None),
    ready_date: Optional[str] = Query(default=None),
    filename: Optional[str] = Query(default=None),
):
    """Tải trực tiếp file .mp4 về máy tính hoặc điện thoại (dành cho bản chạy trên Cloud Render)."""
    if ready_date and filename:
        safe_date = Path(ready_date).name
        safe_name = Path(filename).name
        target = SAN_SANG_DANG_DIR / safe_date / safe_name
        download_name = safe_name
    elif product and video_no is not None:
        slug = slugify_folder(product)
        target = SAN_PHAM_DIR / slug / "_video" / f"v{int(video_no)}.mp4"
        download_name = f"{slug}_v{int(video_no)}.mp4"
    else:
        raise HTTPException(status_code=400, detail="Thiếu thông tin file video cần tải.")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file video để tải xuống.")

    return FileResponse(
        str(target),
        media_type="video/mp4",
        filename=download_name,
    )


@app.get("/api/download/day_zip")
async def api_download_day_zip(date: Optional[str] = Query(default=None)):
    """Đóng gói toàn bộ MP4 + Caption .txt của 1 ngày (hoặc tất cả ngày) thành 1 file .zip để tải về 1-click."""
    TAM_DIR.mkdir(parents=True, exist_ok=True)

    if date:
        safe_date = Path(date).name
        day_dir = SAN_SANG_DANG_DIR / safe_date
        if not day_dir.exists() or not day_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Không tìm thấy dữ liệu ngày {safe_date}.")
        zip_name = f"tiktok_videos_{safe_date}.zip"
        zip_path = TAM_DIR / zip_name
        summary_lines: List[str] = [f"=== TỔNG HỢP CAPTION NGÀY {safe_date} ===\n"]

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for f in sorted(day_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in (".mp4", ".txt"):
                    zf.write(f, arcname=f.name)
                    if f.suffix.lower() == ".txt":
                        cap = f.read_text(encoding="utf-8-sig").strip()
                        summary_lines.append(f"--- FILE: {f.stem}.mp4 ---\n{cap}\n")
            zf.writestr("00_TONG_HOP_CAPTION.txt", "\n".join(summary_lines))

        return FileResponse(str(zip_path), media_type="application/zip", filename=zip_name)

    # Nếu không truyền date -> nén toàn bộ thư mục san_sang_dang
    zip_name = "tiktok_tat_ca_video_san_sang_dang.zip"
    zip_path = TAM_DIR / zip_name
    count_files = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        if SAN_SANG_DANG_DIR.exists():
            for day_dir in sorted(SAN_SANG_DANG_DIR.iterdir()):
                if not day_dir.is_dir():
                    continue
                for f in sorted(day_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in (".mp4", ".txt"):
                        zf.write(f, arcname=f"{day_dir.name}/{f.name}")
                        count_files += 1

    if count_files == 0:
        raise HTTPException(status_code=404, detail="Chưa có video nào đã duyệt để nén ZIP.")

    return FileResponse(str(zip_path), media_type="application/zip", filename=zip_name)


@app.get("/api/products")
async def api_list_products():
    SAN_PHAM_DIR.mkdir(parents=True, exist_ok=True)
    products: List[Dict[str, Any]] = []
    for p in sorted(SAN_PHAM_DIR.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir():
            continue
        if p.name.startswith("_") or p.name.startswith("."):
            continue
        products.append(_build_product_summary(p))
    return {"products": products}


@app.get("/api/product/content")
async def api_get_product_content(product: str = Query(...)):
    slug = slugify_folder(product)
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy sản phẩm {slug}")
    nd_path = prod_dir / "noi_dung.txt"
    raw = nd_path.read_text(encoding="utf-8-sig") if nd_path.exists() else make_sample_noi_dung(slug)
    parsed = parse_noi_dung(raw, slug=slug)
    return {
        "product": slug,
        "content": raw,
        "parsed": parsed.model_dump(),
    }


@app.post("/api/product/content")
async def api_save_product_content(req: SaveContentRequest):
    slug = slugify_folder(req.product)
    prod_dir = SAN_PHAM_DIR / slug
    prod_dir.mkdir(parents=True, exist_ok=True)
    nd_path = prod_dir / "noi_dung.txt"
    nd_path.write_text(req.content, encoding="utf-8")
    parsed = parse_noi_dung(req.content, slug=slug)
    queue_manager.log(f"Đã cập nhật kịch bản noi_dung.txt cho {slug} ({len(parsed.videos)} video).")
    return {"ok": True, "product": slug, "video_count": len(parsed.videos)}


@app.post("/api/product/new")
async def api_create_new_product(req: NewProductRequest, open_explorer: bool = Query(default=False)):
    slug = slugify_folder(req.name)
    prod_dir = SAN_PHAM_DIR / slug
    prod_dir.mkdir(parents=True, exist_ok=True)
    (prod_dir / "_video").mkdir(parents=True, exist_ok=True)
    nd_path = prod_dir / "noi_dung.txt"
    if not nd_path.exists():
        sample_txt = make_sample_noi_dung(
            ten_hien_thi=req.ten_hien_thi or req.name,
            link=req.link or "",
            hashtag=req.hashtag or "",
        )
        nd_path.write_text(sample_txt, encoding="utf-8")
    if open_explorer:
        _open_in_explorer(prod_dir)
    queue_manager.log(f"Đã tạo thư mục sản phẩm mới: {slug}")
    return {"ok": True, "slug": slug, "product": _build_product_summary(prod_dir)}


@app.post("/api/product/delete")
async def api_delete_product(req: Dict[str, Any]):
    """Xóa thư mục sản phẩm để giải phóng dung lượng trên Cloud Render."""
    slug = slugify_folder(str(req.get("product", "")))
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy sản phẩm {slug}")
    shutil.rmtree(prod_dir, ignore_errors=True)
    queue_manager.log(f"🗑 Đã xóa sản phẩm: {slug}")
    return {"ok": True, "deleted": slug}


@app.post("/api/product/upload")
async def api_upload_product_media(
    product: str = Form(...),
    slot: Optional[str] = Form(default=None),
    files: List[UploadFile] = File(...),
):
    """Hỗ trợ kéo-thả 1 hoặc nhiều file ảnh/video thẳng từ trình duyệt vào sản phẩm."""
    slug = slugify_folder(product)
    prod_dir = SAN_PHAM_DIR / slug
    prod_dir.mkdir(parents=True, exist_ok=True)

    saved_names: List[str] = []
    for idx, up in enumerate(files):
        orig_name = Path(up.filename or f"file_{idx}.jpg").name
        ext = Path(orig_name).suffix.lower()
        if ext not in MEDIA_EXTS:
            raise HTTPException(status_code=400, detail=f"Định dạng file {orig_name} không được hỗ trợ.")

        if slot in SLOT_NAMES and len(files) == 1:
            safe_stem = slugify_folder(Path(orig_name).stem, max_len=40)
            dst_name = f"{safe_stem}{ext}"
            dst_path = prod_dir / dst_name
            with open(dst_path, "wb") as out_f:
                shutil.copyfileobj(up.file, out_f)
            assign_file_to_slot(slug, slot, dst_name)
            saved_names.append(dst_name)
        else:
            safe_stem = slugify_folder(Path(orig_name).stem, max_len=40)
            dst_name = f"{safe_stem}{ext}"
            dst_path = prod_dir / dst_name
            counter = 1
            while dst_path.exists():
                dst_name = f"{safe_stem}_{counter}{ext}"
                dst_path = prod_dir / dst_name
                counter += 1
            with open(dst_path, "wb") as out_f:
                shutil.copyfileobj(up.file, out_f)
            saved_names.append(dst_name)

    resolve_product_media(prod_dir)
    queue_manager.log(f"Đã tải lên {len(saved_names)} tư liệu cho {slug}: {', '.join(saved_names)}")
    return {"ok": True, "saved": saved_names, "product": _build_product_summary(prod_dir)}


@app.post("/api/product/swap_slots")
async def api_swap_slots(req: SwapSlotsRequest):
    slug = slugify_folder(req.product)
    mapping = swap_product_slots(slug, req.slot_a, req.slot_b)
    queue_manager.log(f"Đã đổi chỗ {req.slot_a} ↔ {req.slot_b} cho {slug}.")
    return {"ok": True, "files_map": mapping, "product": _build_product_summary(SAN_PHAM_DIR / slug)}


@app.post("/api/product/assign_slot")
async def api_assign_slot(req: AssignFileSlotRequest):
    slug = slugify_folder(req.product)
    mapping = assign_file_to_slot(slug, req.slot, req.filename)
    return {"ok": True, "files_map": mapping, "product": _build_product_summary(SAN_PHAM_DIR / slug)}


@app.post("/api/product/open")
async def api_open_product_folder(req: Dict[str, Any]):
    slug = slugify_folder(str(req.get("product", "")))
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy thư mục {slug}")
    _open_in_explorer(prod_dir)
    return {"ok": True}


@app.post("/api/bulk")
async def api_bulk_scripts(req: BulkScriptRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Nội dung kịch bản hàng loạt đang trống.")
    if req.preview_only:
        parsed_list = parse_bulk_scripts(req.text)
        return {
            "ok": True,
            "preview": True,
            "count": len(parsed_list),
            "items": [
                {
                    "slug": it.slug,
                    "ten": it.ten,
                    "video_count": len(it.videos),
                    "hooks": [v.hook for v in it.videos],
                }
                for it in parsed_list
            ],
        }

    saved = save_bulk_scripts(req.text)
    queue_manager.log(f"Đã tách và lưu kịch bản hàng loạt cho {len(saved)} sản phẩm.")
    return {"ok": True, "count": len(saved), "items": saved}


@app.post("/api/render")
async def api_enqueue_render(req: RenderRequest):
    slugs: List[str] = []
    if req.product:
        slugs.append(slugify_folder(req.product))
    if req.products:
        slugs.extend(slugify_folder(p) for p in req.products)

    if not slugs:
        raise HTTPException(status_code=400, detail="Chưa chọn sản phẩm cần làm video.")

    added = 0
    skipped: List[str] = []

    for slug in slugs:
        prod_dir = SAN_PHAM_DIR / slug
        if not prod_dir.exists():
            skipped.append(f"{slug} (không tồn tại)")
            continue

        summary = _build_product_summary(prod_dir)
        if not summary["ready_to_render"]:
            skipped.append(f"{slug} (thiếu tư liệu hoặc kịch bản)")
            continue

        target_vnos: List[int] = []
        if req.video_no is not None:
            target_vnos = [int(req.video_no)]
        elif req.video_nos:
            target_vnos = [int(x) for x in req.video_nos]
        else:
            target_vnos = [int(v["video_no"]) for v in summary["videos"] if v["has_script"]]

        for v_no in target_vnos:
            if queue_manager.enqueue(slug, v_no):
                added += 1

    return {"ok": True, "added": added, "skipped": skipped, "status": queue_manager.get_status()}


@app.post("/api/render_all")
async def api_render_all_pending():
    added = 0
    SAN_PHAM_DIR.mkdir(parents=True, exist_ok=True)
    for prod_dir in sorted(SAN_PHAM_DIR.iterdir(), key=lambda x: x.name.lower()):
        if not prod_dir.is_dir() or prod_dir.name.startswith(("_", ".")):
            continue
        summary = _build_product_summary(prod_dir)
        if not summary["ready_to_render"]:
            continue
        for v in summary["videos"]:
            if v["has_script"] and v["state"] in ("chua_lam", "loi"):
                if queue_manager.enqueue(summary["slug"], int(v["video_no"])):
                    added += 1

    return {"ok": True, "added": added, "status": queue_manager.get_status()}


@app.post("/api/queue/control")
async def api_queue_control(req: QueueControlRequest):
    st = queue_manager.control(req.action, product=req.product, video_no=req.video_no)
    return {"ok": True, "status": st}


@app.get("/api/frames")
async def api_get_frames(product: str = Query(...)):
    slug = slugify_folder(product)
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy sản phẩm {slug}")

    frames = get_product_frames(prod_dir)
    media_map = resolve_product_media(prod_dir)
    for slot, m_path in media_map.items():
        if m_path is not None and m_path.exists():
            frames[slot]["preview_url"] = f"{_rel_url(m_path)}&preview=1"
            frames[slot]["raw_url"] = _rel_url(m_path)
        else:
            frames[slot]["preview_url"] = None
            frames[slot]["raw_url"] = None

    return {"product": slug, "frames": frames}


@app.post("/api/frames")
async def api_save_frames(req: SaveFramesRequest):
    slug = slugify_folder(req.product)
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy sản phẩm {slug}")

    updated = save_product_frames(prod_dir, req.frames, reset_auto=req.reset_auto)
    action_msg = "đặt lại tự động" if req.reset_auto else "lưu khung chỉnh tay"
    queue_manager.log(f"Đã {action_msg} khung ảnh cho {slug}.")
    return {"ok": True, "product": slug, "frames": updated}


@app.post("/api/preview_banner")
async def api_preview_banner(req: Dict[str, Any]):
    slug = slugify_folder(str(req.get("product", "")))
    video_no = int(req.get("video_no", 1))
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy sản phẩm {slug}")

    nd_path = prod_dir / "noi_dung.txt"
    hook_text = str(req.get("hook", "")).strip()
    if not hook_text and nd_path.exists():
        parsed = parse_noi_dung(nd_path.read_text(encoding="utf-8-sig"), slug=slug)
        sc = next((v for v in parsed.videos if v.video_no == video_no), None)
        if sc:
            hook_text = sc.hook
        elif parsed.videos:
            hook_text = parsed.videos[0].hook
    if not hook_text:
        hook_text = "ĐÂY RỒI! MẪU SẢN PHẨM ĐANG BÁN CỰC CHẠY TRÊN TIKTOK SHOP!"

    cfg = load_config()
    out = make_banner(prod_dir=prod_dir, hook_text=hook_text, cfg=cfg, video_no=video_no)
    return {
        "ok": True,
        "product": slug,
        "video_no": video_no,
        "banner_url": _rel_url(out["preview_png"]),
    }


@app.post("/api/video/review")
async def api_review_video(req: VideoReviewRequest):
    slug = slugify_folder(req.product)
    entry = review_product_video(slug, req.video_no, req.action, queue_manager)
    return {"ok": True, "entry": entry}


@app.get("/api/ready")
async def api_list_ready_videos():
    SAN_SANG_DANG_DIR.mkdir(parents=True, exist_ok=True)
    days_list: List[Dict[str, Any]] = []
    for day_dir in sorted(SAN_SANG_DANG_DIR.iterdir(), key=lambda x: x.name, reverse=True):
        if not day_dir.is_dir() or day_dir.name.startswith(("_", ".")):
            continue
        items: List[Dict[str, Any]] = []
        for mp4_file in sorted(day_dir.glob("*.mp4")):
            txt_file = mp4_file.with_suffix(".txt")
            caption = txt_file.read_text(encoding="utf-8-sig").strip() if txt_file.exists() else ""
            v_no = 1
            if "_v" in mp4_file.stem:
                try:
                    v_no = int(mp4_file.stem.rsplit("_v", 1)[1])
                except ValueError:
                    v_no = 1
            from app.queue_worker import suggested_post_slot

            items.append(
                {
                    "filename": mp4_file.name,
                    "video_url": _rel_url(mp4_file),
                    "download_url": f"/api/download/video?ready_date={quote(day_dir.name)}&filename={quote(mp4_file.name)}",
                    "caption": caption,
                    "size_mb": round(mp4_file.stat().st_size / (1024 * 1024), 2),
                    "post_slot_hint": suggested_post_slot(v_no),
                }
            )
        if items:
            days_list.append(
                {
                    "date": day_dir.name,
                    "count": len(items),
                    "zip_url": f"/api/download/day_zip?date={quote(day_dir.name)}",
                    "items": items,
                }
            )
    return {"days": days_list}


@app.get("/api/status")
async def api_get_status():
    return queue_manager.get_status()


@app.get("/api/config")
async def api_get_config():
    cfg = load_config()
    cfg["is_cloud"] = cfg_mod.IS_CLOUD
    cfg["has_ephemeral_disk"] = bool(os.environ.get("RENDER")) and not bool(os.environ.get("RENDER_DISK_MOUNT"))
    return cfg


@app.post("/api/config")
async def api_save_config(req: Dict[str, Any]):
    updated = save_config(req)
    updated["is_cloud"] = cfg_mod.IS_CLOUD
    queue_manager.log("Đã lưu cấu hình hệ thống (cai_dat.json).")
    return updated


@app.get("/api/voice/check")
async def api_voice_check():
    cfg = load_config()
    return check_tts_status(cfg)


@app.get("/api/voice/profiles")
async def api_voice_profiles():
    cfg = load_config()
    return {"profiles": list_tts_profiles(cfg)}


@app.post("/api/voice/test")
async def api_voice_test(req: VoiceTestRequest):
    cfg = load_config()
    if req.config_override:
        cfg.update(req.config_override)
    wav_path = synthesize_test_sentence(req.text, cfg)
    return {
        "ok": True,
        "audio_url": _rel_url(wav_path),
    }


@app.get("/api/prompt")
async def api_get_prompt_template():
    if PROMPT_TEMPLATE_PATH.exists():
        return {"prompt": PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8-sig")}
    return {"prompt": ""}


@app.post("/api/open")
async def api_open_folder(req: OpenFolderRequest):
    if req.target == "san_sang_dang":
        target_dir = SAN_SANG_DANG_DIR / req.date_folder if req.date_folder else SAN_SANG_DANG_DIR
    elif req.product:
        target_dir = SAN_PHAM_DIR / slugify_folder(req.product)
    else:
        target_dir = SAN_PHAM_DIR
    _open_in_explorer(target_dir)
    return {"ok": True}
