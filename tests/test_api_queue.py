"""Kiểm thử FastAPI endpoints, HTTP Range 206, chặn Path Traversal, Upload file và Duyệt video."""

import io
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image

from app import config, content, main, queue_worker


def _make_img_bytes(color=(200, 80, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (600, 1000), color).save(buf, format="JPEG")
    return buf.getvalue()


def test_api_end_to_end_flow(tmp_path: Path, monkeypatch):
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
    monkeypatch.setenv("APP_PASSWORD", "123456")

    with TestClient(main.app) as client:
        # 0. Chưa đăng nhập -> GET / chuyển hướng về /login (302)
        r_unauth = client.get("/", follow_redirects=False)
        assert r_unauth.status_code == 302
        assert r_unauth.headers["location"] == "/login"

        # Đăng nhập qua API Cookie phiên
        r_login = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
        assert r_login.status_code == 200
        assert "tt_af_session" in client.cookies

        # 1. Trang chủ sau khi đăng nhập
        r_home = client.get("/")
        assert r_home.status_code == 200
        assert "sidebar" in r_home.text

        # 2. Dán kịch bản hàng loạt
        bulk_txt = """
=== SẢN PHẨM: Ốp Lưng Test ===
LINK: https://vt.tiktok.com/ZStest/
TEN: Ốp lưng chống sốc
HASHTAG: #oplung #test
[VIDEO 1]
HOOK: Chiếc ốp lưng siêu bền!
DOC: Chiếc ốp lưng siêu bền! Chống va đập bốn góc cực tốt.
"""
        r_bulk = client.post("/api/bulk", json={"text": bulk_txt})
        assert r_bulk.status_code == 200
        assert r_bulk.json()["count"] == 1

        # 3. Upload 3 file tên bất kỳ qua API kéo-thả
        files = [
            ("files", ("khach_1.jpg", _make_img_bytes((200, 50, 50)), "image/jpeg")),
            ("files", ("sp_nen_2.jpg", _make_img_bytes((50, 50, 200)), "image/jpeg")),
            ("files", ("chi_tiet_3.jpg", _make_img_bytes((50, 180, 80)), "image/jpeg")),
        ]
        r_up = client.post("/api/product/upload", data={"product": "op_lung_test"}, files=files)
        assert r_up.status_code == 200
        prod_summary = r_up.json()["product"]
        assert prod_summary["ready_to_render"] is True

        # 4. Đổi chỗ Trái / Phải
        r_swap = client.post(
            "/api/product/swap_slots",
            json={"product": "op_lung_test", "slot_a": "anh_trai", "slot_b": "anh_phai"},
        )
        assert r_swap.status_code == 200

        # 5. Dựng banner xem trước
        r_prev = client.post("/api/preview_banner", json={"product": "op_lung_test", "video_no": 1})
        assert r_prev.status_code == 200
        banner_url = r_prev.json()["banner_url"].split("?")[0]

        # 6. Kiểm tra HTTP Range (206 Partial Content) trên /files/
        r_range = client.get(banner_url, headers={"Range": "bytes=0-255"})
        assert r_range.status_code == 206
        assert len(r_range.content) == 256
        assert "bytes 0-255/" in r_range.headers["content-range"]

        # 7. Kiểm tra chặn Path Traversal
        r_trav = client.get("/files/../../Windows/win.ini")
        assert r_trav.status_code in (403, 404)

        # 8. Kiểm tra Duyệt video -> xuất sang san_sang_dang/<YYYY-MM-DD>/
        fake_mp4 = sp_dir / "op_lung_test" / "_video" / "v1.mp4"
        fake_mp4.parent.mkdir(parents=True, exist_ok=True)
        fake_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42_dummy_video_bytes")

        r_rev = client.post(
            "/api/video/review",
            json={"product": "op_lung_test", "video_no": 1, "action": "approve"},
        )
        assert r_rev.status_code == 200

        r_ready = client.get("/api/ready")
        assert r_ready.status_code == 200
        days = r_ready.json()["days"]
        assert len(days) == 1
        assert days[0]["items"][0]["filename"] == "op_lung_test_v1.mp4"
        assert "Mua tại đây: https://vt.tiktok.com/ZStest/" in days[0]["items"][0]["caption"]
