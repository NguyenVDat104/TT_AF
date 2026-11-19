"""Kiểm thử tính năng Mẫu Template (Video quay mẫu & file ghi âm giọng thật)."""

import io
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image

from app import config, content, main, queue_worker, templates_mgr


def _make_dummy_image() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), (200, 50, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def test_template_flow(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    sp_dir = data_dir / "san_pham"
    tpl_dir = data_dir / "_mau_templates"
    tam_dir = data_dir / "_tam"

    for d in (sp_dir, tpl_dir, tam_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "DATA_ROOT", data_dir)
    monkeypatch.setattr(config, "SAN_PHAM_DIR", sp_dir)
    monkeypatch.setattr(config, "TEMPLATES_DIR", tpl_dir)
    monkeypatch.setattr(config, "TAM_DIR", tam_dir)
    monkeypatch.setattr(templates_mgr, "TEMPLATES_DIR", tpl_dir)
    monkeypatch.setattr(main, "BASE_DIR", data_dir)
    monkeypatch.setattr(main, "SAN_PHAM_DIR", sp_dir)
    monkeypatch.setattr(queue_worker, "SAN_PHAM_DIR", sp_dir)
    monkeypatch.setattr(queue_worker, "TAM_DIR", tam_dir)
    monkeypatch.setenv("AUTH_DISABLED", "1")

    # 1. Tạo 1 template trực tiếp qua templates_mgr
    t_slug = "mau_test_01"
    cur_t_dir = tpl_dir / t_slug
    cur_t_dir.mkdir(parents=True, exist_ok=True)

    # Giả lập video mẫu và audio mẫu
    (cur_t_dir / "video_mau.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42_dummy")
    (cur_t_dir / "ghi_am_mau.wav").write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00")

    templates_mgr.save_template_metadata(
        t_slug,
        {
            "name": "Mẫu ốp chống bẩn test",
            "hook": "ĐÂY RỒI MẪU ỐP LƯNG CHỐNG BẨN",
            "banner_duration": 6.5,
            "link": "https://vt.tiktok.com/test",
            "hashtag": "#oplung #xuhuong",
        },
    )

    with TestClient(main.app) as client:
        # Kiểm tra API liệt kê template
        r_list = client.get("/api/templates")
        assert r_list.status_code == 200
        tpls = r_list.json()["templates"]
        assert len(tpls) == 1
        assert tpls[0]["slug"] == t_slug
        assert tpls[0]["has_video"] is True
        assert tpls[0]["has_audio"] is True

        # 2. Áp dụng template để tạo sản phẩm mới chỉ bằng cách tải ảnh lên
        img_bytes = _make_dummy_image()
        r_apply = client.post(
            "/api/template/apply_and_render",
            data={
                "template_slug": t_slug,
                "product_name": "op_da_bo_moi",
                "product_title": "Ốp Da Bò Mới 2026",
            },
            files=[
                ("files", ("anh_sp_1.jpg", img_bytes, "image/jpeg")),
                ("files", ("anh_sp_2.jpg", img_bytes, "image/jpeg")),
            ],
        )
        assert r_apply.status_code == 200
        res_data = r_apply.json()
        assert res_data["ok"] is True
        assert res_data["product"] == "op_da_bo_moi"

        # Kiểm tra thư mục sản phẩm mới sinh ra
        new_p_dir = sp_dir / "op_da_bo_moi"
        assert (new_p_dir / "anh_trai.jpg").exists()
        assert (new_p_dir / "anh_phai.jpg").exists()
        assert (new_p_dir / "can_canh.mp4").exists()
        assert (new_p_dir / "_video" / "v1.wav").exists()
        assert (new_p_dir / "noi_dung.txt").exists()

        content_txt = (new_p_dir / "noi_dung.txt").read_text(encoding="utf-8-sig")
        assert "ĐÂY RỒI MẪU ỐP LƯNG CHỐNG BẨN" in content_txt

        # 3. Kiểm tra API xóa template
        r_del = client.delete(f"/api/template/{t_slug}")
        assert r_del.status_code == 200
        assert not (tpl_dir / t_slug).exists()
