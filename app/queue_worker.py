"""Hàng đợi bền vững (_hang_doi.json), Snapshot tư liệu chống xung đột khi sửa file, Worker tuần tự & Duyệt video."""

from __future__ import annotations

import collections
import datetime
import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from app.config import SAN_PHAM_DIR, SAN_SANG_DANG_DIR, TAM_DIR, load_config
from app.content import parse_noi_dung, resolve_product_media
from app.render import compose_video
from app.subtitle import generate_closeup_ass_subtitle
from app.tts import synthesize_script_voice

QUEUE_PERSIST_PATH = TAM_DIR / "_hang_doi.json"
_STATUS_LOCK = threading.RLock()


def load_product_status(prod_dir: Path) -> Dict[str, Any]:
    """Đọc _video/trang_thai.json của 1 sản phẩm."""
    status_file = prod_dir / "_video" / "trang_thai.json"
    with _STATUS_LOCK:
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
    return {"videos": {}}


def save_product_status(prod_dir: Path, data: Dict[str, Any]) -> None:
    """Ghi _video/trang_thai.json an toàn (atomic write)."""
    video_dir = prod_dir / "_video"
    video_dir.mkdir(parents=True, exist_ok=True)
    status_file = video_dir / "trang_thai.json"
    tmp_file = video_dir / "trang_thai.json.tmp"
    with _STATUS_LOCK:
        tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_file, status_file)


def update_single_video_status(
    prod_dir: Path,
    video_no: int,
    state: str,
    error: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cập nhật trạng thái cho video số video_no của 1 sản phẩm."""
    with _STATUS_LOCK:
        data = load_product_status(prod_dir)
        videos = data.setdefault("videos", {})
        key = str(video_no)
        entry = videos.get(key, {}) if isinstance(videos.get(key), dict) else {}
        entry["state"] = state
        entry["error"] = error
        entry["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        if extra:
            entry.update(extra)
        videos[key] = entry
        save_product_status(prod_dir, data)
        return entry


def build_caption_text(hook: str, hashtag: str, link: str, default_hashtags: str) -> str:
    """Tạo nội dung caption = hook + hashtag + link sản phẩm."""
    parts: List[str] = []
    if hook.strip():
        parts.append(hook.strip())
    ht = hashtag.strip() or default_hashtags.strip()
    if ht:
        parts.append(ht)
    if link.strip():
        parts.append(f"Mua tại đây: {link.strip()}")
    return "\n\n".join(parts) + "\n"


def suggested_post_slot(video_no: int) -> str:
    """Gợi ý khung giờ rải trong ngày để không đăng liền 3 video cùng sản phẩm."""
    slots = {
        1: "Khung Sáng (07:30 - 09:00)",
        2: "Khung Trưa (11:30 - 13:00)",
        3: "Khung Tối (19:30 - 21:30)",
    }
    return slots.get(video_no, "Rải cách nhau ít nhất 3-4 giờ")


class VideoQueueManager:
    """Quản lý hàng đợi bền vững 1 worker tuần tự + Nhật ký 300 dòng trong bộ nhớ."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._queue: List[Dict[str, Any]] = []
        self._current_job: Optional[Dict[str, Any]] = None
        self._paused: bool = False
        self._stop_event = threading.Event()
        self._logs: Deque[str] = collections.deque(maxlen=300)
        self._worker_thread: Optional[threading.Thread] = None

    def log(self, message: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        with self._lock:
            self._logs.append(line)

    def get_logs(self, limit: int = 60) -> List[str]:
        with self._lock:
            items = list(self._logs)
        return items[-limit:] if limit > 0 else items

    def _persist_queue_locked(self) -> None:
        TAM_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "paused": self._paused,
            "current": self._current_job,
            "queue": self._queue,
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        tmp_path = QUEUE_PERSIST_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, QUEUE_PERSIST_PATH)

    def recover_on_startup(self) -> None:
        """Khôi phục hàng đợi bền vững khi bật lại công cụ và xử lý các video dở dang."""
        TAM_DIR.mkdir(parents=True, exist_ok=True)
        SAN_PHAM_DIR.mkdir(parents=True, exist_ok=True)

        # Dọn các thư mục snapshot tạm bị bỏ dở từ phiên trước
        for stale in TAM_DIR.glob("job_*"):
            if stale.is_dir():
                shutil.rmtree(stale, ignore_errors=True)

        restored_items: List[Tuple[str, int]] = []
        paused_flag = False

        if QUEUE_PERSIST_PATH.exists():
            try:
                saved = json.loads(QUEUE_PERSIST_PATH.read_text(encoding="utf-8-sig"))
                paused_flag = bool(saved.get("paused", False))
                cur = saved.get("current")
                if isinstance(cur, dict) and cur.get("product") and cur.get("video_no"):
                    restored_items.append((str(cur["product"]), int(cur["video_no"])))
                for item in saved.get("queue", []):
                    if isinstance(item, dict) and item.get("product") and item.get("video_no"):
                        pair = (str(item["product"]), int(item["video_no"]))
                        if pair not in restored_items:
                            restored_items.append(pair)
            except Exception:
                pass

        # Quét toàn bộ san_pham/: nếu video có trạng thái dang_lam / trong_hang_doi mà không nằm trong restored_items -> đưa về chua_lam
        restored_set = set(restored_items)
        for prod_dir in SAN_PHAM_DIR.iterdir():
            if not prod_dir.is_dir() or prod_dir.name.startswith(("_", ".")):
                continue
            st = load_product_status(prod_dir)
            changed = False
            for v_key, v_info in st.get("videos", {}).items():
                if not isinstance(v_info, dict):
                    continue
                v_no = int(v_key)
                cur_state = v_info.get("state", "chua_lam")
                if (prod_dir.name, v_no) in restored_set:
                    v_info["state"] = "trong_hang_doi"
                    changed = True
                elif cur_state in ("dang_lam", "trong_hang_doi"):
                    v_info["state"] = "chua_lam"
                    changed = True
            if changed:
                save_product_status(prod_dir, st)

        with self._lock:
            self._paused = paused_flag
            self._queue = []
            for slug, v_no in restored_items:
                if (SAN_PHAM_DIR / slug).exists():
                    self._queue.append({"product": slug, "video_no": v_no})
            self._persist_queue_locked()

        if self._queue:
            self.log(f"Đã khôi phục {len(self._queue)} video trong hàng đợi từ phiên làm việc trước.")
        else:
            self.log("Hệ thống Xưởng Video TikTok đã sẵn sàng.")

    def start_worker(self) -> None:
        with self._lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="TikTokVideoWorker",
                daemon=True,
            )
            self._worker_thread.start()

    def stop_worker(self) -> None:
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def enqueue(self, product_slug: str, video_no: int) -> bool:
        """Thêm (sản phẩm, số video) vào hàng đợi, không thêm trùng."""
        prod_dir = SAN_PHAM_DIR / product_slug
        if not prod_dir.exists():
            return False

        with self._lock:
            if self._current_job and (
                self._current_job["product"] == product_slug and self._current_job["video_no"] == video_no
            ):
                return False
            for item in self._queue:
                if item["product"] == product_slug and item["video_no"] == video_no:
                    return False

            self._queue.append({"product": product_slug, "video_no": int(video_no)})
            update_single_video_status(prod_dir, video_no, "trong_hang_doi", error="")
            self._persist_queue_locked()
            self.log(f"Đã thêm vào hàng đợi: {product_slug} - Video {video_no}")
            return True

    def control(self, action: str, product: Optional[str] = None, video_no: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            if action == "pause":
                self._paused = True
                self._persist_queue_locked()
                self.log("Đã tạm dừng hàng đợi (video đang làm dở sẽ hoàn tất nốt).")
            elif action == "resume":
                self._paused = False
                self._persist_queue_locked()
                self.log("Đã tiếp tục chạy hàng đợi.")
            elif action == "clear":
                removed = list(self._queue)
                self._queue.clear()
                for item in removed:
                    p_dir = SAN_PHAM_DIR / item["product"]
                    if p_dir.exists():
                        update_single_video_status(p_dir, int(item["video_no"]), "chua_lam")
                self._persist_queue_locked()
                self.log(f"Đã xóa {len(removed)} mục đang chờ trong hàng đợi.")
            elif action == "remove" and product and video_no is not None:
                before = len(self._queue)
                self._queue = [
                    it
                    for it in self._queue
                    if not (it["product"] == product and int(it["video_no"]) == int(video_no))
                ]
                if len(self._queue) < before:
                    p_dir = SAN_PHAM_DIR / product
                    if p_dir.exists():
                        update_single_video_status(p_dir, int(video_no), "chua_lam")
                    self._persist_queue_locked()
                    self.log(f"Đã gỡ {product} - Video {video_no} khỏi hàng đợi.")
            return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "paused": self._paused,
                "current": self._current_job,
                "queue": list(self._queue),
                "queue_length": len(self._queue),
                "logs": list(self._logs)[-80:],
            }

    def _create_job_snapshot(self, prod_dir: Path, video_no: int) -> Path:
        """Sao chép tư liệu sản phẩm ra thư mục snapshot riêng trước khi render để tránh lỗi nếu người dùng sửa file."""
        snap_dir = TAM_DIR / f"job_{prod_dir.name}_v{video_no}_{int(time.time() * 1000)}"
        snap_dir.mkdir(parents=True, exist_ok=True)

        media_map = resolve_product_media(prod_dir)
        for _, m_path in media_map.items():
            if m_path is not None and m_path.exists():
                dst = snap_dir / m_path.name
                if not dst.exists():
                    shutil.copy2(m_path, dst)

        for cfg_name in ("khung.json", "noi_dung.txt"):
            src_cfg = prod_dir / cfg_name
            if src_cfg.exists():
                shutil.copy2(src_cfg, snap_dir / cfg_name)

        return snap_dir

    def process_one_job(self, product_slug: str, video_no: int) -> None:
        """Thực thi 4 bước cho 1 video: tạo giọng -> tính thời lượng & phụ đề -> dựng banner -> ráp FFmpeg."""
        prod_dir = SAN_PHAM_DIR / product_slug
        if not prod_dir.exists():
            self.log(f"[BỎ QUA] Thư mục sản phẩm {product_slug} không còn tồn tại.")
            return

        t_start = time.time()
        update_single_video_status(prod_dir, video_no, "dang_lam", error="")
        self.log(f"▶ Bắt đầu làm {product_slug} - Video {video_no}...")

        snap_dir: Optional[Path] = None
        try:
            cfg = load_config()
            nd_path = prod_dir / "noi_dung.txt"
            if not nd_path.exists():
                raise FileNotFoundError("Thiếu file kịch bản noi_dung.txt.")

            parsed = parse_noi_dung(nd_path.read_text(encoding="utf-8-sig"), slug=product_slug)
            script = next((v for v in parsed.videos if v.video_no == video_no), None)
            if script is None:
                raise ValueError(f"Không tìm thấy kịch bản [VIDEO {video_no}] trong noi_dung.txt.")

            media_map = resolve_product_media(prod_dir)
            missing = [k for k in ("anh_trai", "anh_phai", "can_canh") if media_map.get(k) is None]
            if missing:
                raise FileNotFoundError(f"Thiếu tư liệu bắt buộc: {', '.join(missing)}")

            # Tạo bản chụp cô lập tư liệu
            snap_dir = self._create_job_snapshot(prod_dir, video_no)
            video_out_dir = prod_dir / "_video"
            video_out_dir.mkdir(parents=True, exist_ok=True)
            cache_dir = video_out_dir / "_giong_cache"

            voice_wav: Optional[Path] = None
            voice_dur = 0.0
            hook_dur = 0.0
            subtitle_ass: Optional[Path] = None
            tts_provider_used = "off"

            if cfg.get("voice_enabled", True):
                out_wav = video_out_dir / f"v{video_no}.wav"
                self.log(f"  [1/3] Đang tạo giọng đọc ({cfg.get('tts_provider', 'edge')})...")
                voice_res = synthesize_script_voice(
                    hook_text=script.hook,
                    doc_text=script.doc,
                    out_wav=out_wav,
                    cache_dir=cache_dir,
                    cfg=cfg,
                    log_fn=self.log,
                )
                voice_wav = voice_res.wav_path
                voice_dur = voice_res.total_duration
                hook_dur = voice_res.hook_duration
                tts_provider_used = voice_res.provider_used
                self.log(
                    f"  -> Xong giọng đọc: {voice_dur:.1f}s (Hook {hook_dur:.1f}s, "
                    f"cache {voice_res.cached_hits}/{voice_res.total_chunks} câu)."
                )

                # Tính thời lượng để sinh phụ đề động .ass khớp nửa sau
                from app.render import compute_video_durations

                t_tot, t_ban, _ = compute_video_durations(True, voice_dur, hook_dur, cfg)
                if cfg.get("subtitle_enabled", True) and voice_res.word_timings:
                    ass_file = snap_dir / f"_sub_v{video_no}.ass"
                    subtitle_ass = generate_closeup_ass_subtitle(
                        word_timings=voice_res.word_timings,
                        banner_duration=t_ban,
                        total_duration=t_tot,
                        out_ass_path=ass_file,
                        cfg=cfg,
                    )
            else:
                self.log("  [1/3] Đang tắt giọng đọc -> dùng thời lượng mặc định.")

            self.log("  [2/3] Dựng lớp Banner & chạy FFmpeg ghép video 1080x1920...")
            out_mp4 = video_out_dir / f"v{video_no}.mp4"
            render_info = compose_video(
                prod_dir=snap_dir,
                video_no=video_no,
                hook_text=script.hook,
                out_mp4=out_mp4,
                cfg=cfg,
                voice_wav=voice_wav,
                voice_duration=voice_dur,
                hook_duration=hook_dur,
                subtitle_ass=subtitle_ass,
                work_dir=snap_dir / "_work",
            )

            # Lưu lại bản xem trước banner của video này vào _video/
            work_preview = snap_dir / "_work" / f"_banner_preview_v{video_no}.png"
            if work_preview.exists():
                shutil.copy2(work_preview, video_out_dir / f"banner_v{video_no}.png")

            elapsed = round(time.time() - t_start, 1)
            update_single_video_status(
                prod_dir,
                video_no,
                "cho_duyet",
                error="",
                extra={
                    "duration": render_info["total_duration"],
                    "banner_duration": render_info["banner_duration"],
                    "tts_provider": tts_provider_used,
                    "render_seconds": elapsed,
                    "hook": script.hook,
                },
            )
            self.log(
                f"✓ Hoàn thành {product_slug} - Video {video_no} "
                f"(dài {render_info['total_duration']:.1f}s, mất {elapsed}s) -> Chờ duyệt!"
            )

        except Exception as exc:
            err_str = str(exc)
            update_single_video_status(prod_dir, video_no, "loi", error=err_str)
            self.log(f"✗ LỖI {product_slug} - Video {video_no}: {err_str}")
        finally:
            if snap_dir is not None and snap_dir.exists():
                shutil.rmtree(snap_dir, ignore_errors=True)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            next_item: Optional[Dict[str, Any]] = None
            with self._lock:
                if not self._paused and self._queue:
                    next_item = self._queue.pop(0)
                    self._current_job = next_item
                    self._persist_queue_locked()

            if next_item is None:
                time.sleep(0.5)
                continue

            try:
                self.process_one_job(
                    product_slug=str(next_item["product"]),
                    video_no=int(next_item["video_no"]),
                )
            finally:
                with self._lock:
                    self._current_job = None
                    self._persist_queue_locked()


def review_product_video(slug: str, video_no: int, action: str, queue_mgr: VideoQueueManager) -> Dict[str, Any]:
    """Xử lý Duyệt (approve) / Loại (reject) / Làm lại (redo) một video."""
    prod_dir = SAN_PHAM_DIR / slug
    if not prod_dir.exists():
        raise FileNotFoundError(f"Không tìm thấy sản phẩm {slug}")

    mp4_src = prod_dir / "_video" / f"v{video_no}.mp4"
    cfg = load_config()

    if action == "approve":
        if not mp4_src.exists():
            raise FileNotFoundError(f"Chưa có file video v{video_no}.mp4 để duyệt.")

        today_str = datetime.date.today().isoformat()
        ready_dir = SAN_SANG_DANG_DIR / today_str
        ready_dir.mkdir(parents=True, exist_ok=True)

        dst_mp4 = ready_dir / f"{slug}_v{video_no}.mp4"
        dst_txt = ready_dir / f"{slug}_v{video_no}.txt"
        shutil.copy2(mp4_src, dst_mp4)

        nd_path = prod_dir / "noi_dung.txt"
        parsed = parse_noi_dung(nd_path.read_text(encoding="utf-8-sig"), slug=slug) if nd_path.exists() else None
        script = next((v for v in (parsed.videos if parsed else []) if v.video_no == video_no), None)

        caption = build_caption_text(
            hook=script.hook if script else "",
            hashtag=parsed.hashtag if parsed else "",
            link=parsed.link if parsed else "",
            default_hashtags=str(cfg.get("default_hashtags", "#xuhuong #fyp #tiktokshop")),
        )
        dst_txt.write_text(caption, encoding="utf-8")

        entry = update_single_video_status(
            prod_dir,
            video_no,
            "da_duyet",
            error="",
            extra={
                "approved_date": today_str,
                "ready_mp4": f"san_sang_dang/{today_str}/{dst_mp4.name}",
                "ready_caption": caption.strip(),
                "post_slot_hint": suggested_post_slot(video_no),
            },
        )
        queue_mgr.log(f"★ Đã duyệt {slug} - Video {video_no} -> san_sang_dang/{today_str}/")
        return entry

    if action == "reject":
        entry = update_single_video_status(prod_dir, video_no, "da_loai", error="")
        queue_mgr.log(f"Đã loại {slug} - Video {video_no}.")
        return entry

    if action == "redo":
        queue_mgr.enqueue(slug, video_no)
        return load_product_status(prod_dir).get("videos", {}).get(str(video_no), {"state": "trong_hang_doi"})

    raise ValueError(f"Hành động duyệt không hợp lệ: {action}")


queue_manager = VideoQueueManager()
