"""Kiểm thử module crop.py: lọc nhiễu khung Shopee ở viền trên/dưới, quy đổi tọa độ và làm mờ nền."""

from PIL import Image, ImageDraw

from app.crop import auto_detect_frame, compute_placement, render_slot_image


def test_auto_detect_ignores_top_bottom_shopee_banners():
    # Ảnh nền trắng 800x800, có dải banner đỏ rực ở sát mép trên (y < 70)
    # và sản phẩm thật màu xanh đậm nằm ở hơi lệch phải giữa ảnh (520, 420)
    img = Image.new("RGB", (800, 800), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 800, 65], fill=(230, 30, 30))  # Banner khuyến mãi Shopee ở mép trên
    draw.rectangle([420, 300, 640, 560], fill=(20, 40, 160))  # Sản phẩm thật

    detected = auto_detect_frame(img, slot_w=540, slot_h=1280)
    # Tâm phải bám về phía sản phẩm (cx > 0.52, cy nằm khoảng giữa 0.42..0.68 chứ không bị kéo lên mép trên < 0.25)
    assert detected["cx"] > 0.50
    assert 0.35 <= detected["cy"] <= 0.70
    assert 0.45 <= detected["z"] <= 1.0


def test_compute_placement_clamps_edges_and_detects_blur():
    # Khi z = 1.0: ảnh luôn phủ kín ô -> không cần nền mờ và không hở viền (> 0)
    p_cover = compute_placement(1000, 1000, 540, 1280, cx=0.95, cy=0.95, z=1.0)
    assert p_cover["needs_blur_bg"] is False
    assert p_cover["x"] <= 0
    assert p_cover["x"] + p_cover["scaled_w"] >= 540
    assert p_cover["y"] <= 0
    assert p_cover["y"] + p_cover["scaled_h"] >= 1280

    # Khi z = 0.6: ảnh thu nhỏ -> cần lấp nền mờ Gaussian
    p_zoom_out = compute_placement(1000, 1000, 540, 1280, cx=0.5, cy=0.5, z=0.6)
    assert p_zoom_out["needs_blur_bg"] is True


def test_render_slot_image_exact_dimensions():
    img = Image.new("RGB", (900, 600), (180, 120, 90))
    out_half = render_slot_image(img, 540, 1280, cx=0.5, cy=0.5, z=0.7)
    assert out_half.size == (540, 1280)

    out_full = render_slot_image(img, 1080, 1920, cx=0.5, cy=0.5, z=1.0)
    assert out_full.size == (1080, 1920)
