"""Kiểm thử các tính năng Cloud Render: Basic Auth APP_PASSWORD, /healthz, tải ZIP/MP4, xóa SP & FFmpeg Low-Memory Mode."""

import io
import zipfile
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image

from app import config, content, main, queue_worker
from app.render import compose_video


def test_basic_auth_and_healthz_and_zip_download(tmp_path: Path, monkeypatch):
    sp_dir = tmp_path / "san_pham"
    ssd_dir = tmp_path / "san_sang_dang"
    tam_dir = tmp_path / "_tam"
    cfg_path = tmp_path / "cai_dat.json"

    for mod in (config, content, main, queue_worker):
        if hasattr(mod, "SAN_PHAM_DIR"):
            monkeypatch.setattr(mod, "SAN_PHAM_DIR", sp_dir)
        if hasattr(mod, "SAN_SANG_DANG_DIR"):
            monkeypatch.setattr(mod, "SAN_SANG_DANG_DIR", ssd_dir)
        if hasattr(mod, "TAM_DIR"):
            monkeypatch.setattr(mod, "TAM_DIR", tam_dir)
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(queue_worker, "QUEUE_PERSIST_PATH", tam_dir / "_hang_doi.json")

    monkeypatch.setenv("APP_USER", "admin")
    monkeypatch.setenv("APP_PASSWORD", "MatKhau@Render2026")

    with TestClient(main.app) as client:
        # 1. /healthz luôn mở công khai cho Render & UptimeRobot (không cần mật khẩu)
        r_health = client.get("/healthz")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "ok"

        # 2. Truy cập không mật khẩu vào API/UI phải bị chặn 401
        r_unauth = client.get("/api/products")
        assert r_unauth.status_code == 401

        # 3. Đăng nhập qua Cookie phiên (/api/auth/login) + kiểm tra /api/auth/me & Logout
        r_bad_login = client.post("/api/auth/login", json={"username": "admin", "password": "sai"})
        assert r_bad_login.status_code == 401

        r_good_login = client.post("/api/auth/login", json={"username": "admin", "password": "MatKhau@Render2026"})
        assert r_good_login.status_code == 200
        assert client.get("/api/auth/me").json()["username"] == "admin"

        # Kiểm tra Đổi mật khẩu
        r_chg = client.post(
            "/api/auth/change_password",
            json={
                "current_password": "MatKhau@Render2026",
                "new_username": "dat_admin",
                "new_password": "NewPass@999",
            },
        )
        assert r_chg.status_code == 200
        assert client.get("/api/auth/me").json()["username"] == "dat_admin"

        # Kiểm tra Đăng xuất -> mất quyền truy cập ngay lập tức
        client.post("/api/auth/logout")
        assert client.get("/api/products").status_code == 401

        # Đăng nhập lại bằng tài khoản mới
        r_relogin = client.post("/api/auth/login", json={"username": "dat_admin", "password": "NewPass@999"})
        assert r_relogin.status_code == 200
        auth = None
        r_ok = client.get("/api/products")
        assert r_ok.status_code == 200

        # 4. Tạo sản phẩm, giả lập duyệt video & tải trọn bộ ZIP ngày
        r_new = client.post("/api/product/new", json={"name": "Túi Render Cloud"}, auth=auth)
        assert r_new.status_code == 200
        slug = r_new.json()["slug"]

        vid_file = sp_dir / slug / "_video" / "v1.mp4"
        vid_file.parent.mkdir(parents=True, exist_ok=True)
        vid_file.write_bytes(b"\x00\x00\x00\x18ftypmp42_cloud_mp4_content")

        r_rev = client.post(
            "/api/video/review",
            json={"product": slug, "video_no": 1, "action": "approve"},
            auth=auth,
        )
        assert r_rev.status_code == 200
        approved_date = r_rev.json()["entry"]["approved_date"]

        # Tải lẻ MP4
        r_dl_mp4 = client.get(f"/api/download/video?product={slug}&video_no=1", auth=auth)
        assert r_dl_mp4.status_code == 200
        assert b"cloud_mp4_content" in r_dl_mp4.content

        # Tải trọn bộ ZIP của ngày đó
        r_zip = client.get(f"/api/download/day_zip?date={approved_date}", auth=auth)
        assert r_zip.status_code == 200
        with zipfile.ZipFile(io.BytesIO(r_zip.content), "r") as zf:
            names = zf.namelist()
            assert f"{slug}_v1.mp4" in names
            assert f"{slug}_v1.txt" in names
            assert "00_TONG_HOP_CAPTION.txt" in names

        # 5. Xóa sản phẩm giải phóng dung lượng
        r_del = client.post("/api/product/delete", json={"product": slug}, auth=auth)
        assert r_del.status_code == 200
        assert not (sp_dir / slug).exists()


def test_ffmpeg_low_memory_mode_for_render_free(tmp_path: Path):
    """Đảm bảo cấu hình ép RAM FFmpeg (-threads 1, ultrafast, rc-lookahead=10) chạy mượt không lỗi cú pháp."""
    prod_dir = tmp_path / "sp_lowmem"
    prod_dir.mkdir()
    Image.new("RGB", (600, 1200), (180, 40, 40)).save(prod_dir / "anh_trai.jpg")
    Image.new("RGB", (600, 1200), (40, 80, 180)).save(prod_dir / "anh_phai.jpg")
    Image.new("RGB", (900, 1500), (50, 150, 90)).save(prod_dir / "can_canh.jpg")

    cfg = dict(config.DEFAULT_CONFIG)
    cfg["low_memory_mode"] = True
    cfg["voice_enabled"] = False
    cfg["min_seconds"] = 8.0
    cfg["default_seconds"] = 8.0

    out_mp4 = tmp_path / "lowmem.mp4"
    compose_video(
        prod_dir=prod_dir,
        video_no=1,
        hook_text="Kiểm tra chế độ tiết kiệm RAM 512MB trên Render Free!",
        out_mp4=out_mp4,
        cfg=cfg,
        work_dir=tmp_path / "work_lowmem",
    )
    assert out_mp4.exists() and out_mp4.stat().st_size > 5000
