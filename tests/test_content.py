"""Kiểm thử module content.py: bỏ dấu thư mục, đọc noi_dung.txt (BOM/CRLF), tách hàng loạt & tự phân vai file."""

from pathlib import Path
from PIL import Image

from app import content


def test_slugify_folder():
    assert content.slugify_folder("Ốp chống bẩn (Mẫu 01)!") == "op_chong_ban_mau_01"
    assert content.slugify_folder("Đầm dự tiệc Đỏ Đô") == "dam_du_tiec_do_do"
    long_name = "Túi xách nữ cao cấp chống thấm nước phiên bản giới hạn mùa đông năm nay siêu hot"
    slug = content.slugify_folder(long_name)
    assert len(slug) <= 60
    assert not slug.startswith("_")


def test_parse_noi_dung_bom_crlf_and_continuation():
    raw = (
        "\ufeffLINK: https://vt.tiktok.com/ZS123/\r\n"
        "TEN: Ốp chống bẩn 01\r\n"
        "HASHTAG: #oplung #xuhuong\r\n\r\n"
        "[VIDEO 1]\r\n"
        "HOOK: Đây rồi! Đúng là cái mẫu ốp lưng tui tìm bấy lâu nay!\r\n"
        "DOC: Đây rồi! Đúng là cái mẫu ốp lưng tui tìm bấy lâu nay! (lời đọc 45-65 từ, câu đầu = câu hook)\r\n"
        "Chất silicon mịn cầm cực sướng tay, lau nhẹ là sạch.\r\n\r\n"
        "[VIDEO 2]\r\n"
        "HOOK: \r\n"
        "DOC: \r\n\r\n"
        "[VIDEO 3]\r\n"
        "HOOK: Khoan mua ốp thường nếu chưa xem mẫu này!\r\n"
        "DOC: Khoan mua ốp thường nếu chưa xem mẫu này! Bốn góc chống sốc cực êm.\r\n"
    )
    parsed = content.parse_noi_dung(raw, slug="op_01")
    assert parsed.ten == "Ốp chống bẩn 01"
    assert parsed.link == "https://vt.tiktok.com/ZS123/"
    # VIDEO 2 trống cả hook lẫn doc nên bị loại, còn VIDEO 1 và VIDEO 3
    assert len(parsed.videos) == 2
    assert parsed.videos[0].video_no == 1
    assert "(lời đọc" not in parsed.videos[0].doc
    assert "Chất silicon mịn" in parsed.videos[0].doc
    assert parsed.videos[1].video_no == 3


def test_parse_bulk_scripts():
    bulk = """
=== SẢN PHẨM: Túi Đeo Chéo 01 ===
LINK: https://example.com/1
TEN: Túi đeo chéo da mềm
HASHTAG: #tui #xuhuong
[VIDEO 1]
HOOK: Chiếc túi quốc dân mùa này!
DOC: Chiếc túi quốc dân mùa này! Đựng vừa cả điện thoại lẫn ví dài.

=== SẢN PHẨM: Kính Mát Phân Cực ===
LINK: https://example.com/2
TEN: Kính mát chống tia UV
[VIDEO 1]
HOOK: Đi nắng mà thiếu kính này là tiếc lắm nha!
DOC: Đi nắng mà thiếu kính này là tiếc lắm nha! Tròng phân cực siêu trong.
"""
    items = content.parse_bulk_scripts(bulk)
    assert len(items) == 2
    assert items[0].slug == "tui_deo_cheo_01"
    assert items[1].slug == "kinh_mat_phan_cuc"
    assert len(items[0].videos) == 1
    assert len(items[1].videos) == 1


def test_auto_resolve_arbitrary_filenames_and_swap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(content, "SAN_PHAM_DIR", tmp_path)
    prod_dir = tmp_path / "sp_test"
    prod_dir.mkdir()

    # Thả 2 ảnh và 1 video với tên bất kỳ (không đặt tên anh_trai, anh_phai, can_canh)
    Image.new("RGB", (600, 1200), (200, 50, 50)).save(prod_dir / "shopee_01.jpg")
    Image.new("RGB", (600, 1200), (50, 200, 50)).save(prod_dir / "feedback_02.png")
    (prod_dir / "quay_thuc_te.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")

    resolved = content.resolve_product_media(prod_dir)
    assert resolved["can_canh"] is not None
    assert resolved["can_canh"].name == "quay_thuc_te.mp4"
    assert {resolved["anh_trai"].name, resolved["anh_phai"].name} == {"feedback_02.png", "shopee_01.jpg"}

    old_left = resolved["anh_trai"].name
    old_right = resolved["anh_phai"].name

    swapped = content.swap_product_slots("sp_test", "anh_trai", "anh_phai")
    assert swapped["anh_trai"] == old_right
    assert swapped["anh_phai"] == old_left
