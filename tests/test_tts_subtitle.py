"""Kiểm thử tách câu <= 140 ký tự, khớp toàn bộ câu Hook có nhiều dấu chấm than & sinh phụ đề .ass."""

from pathlib import Path

from app.config import DEFAULT_CONFIG
from app.subtitle import generate_closeup_ass_subtitle
from app.tts.base import WordTiming, split_hook_and_body_sentences, split_sentences


def test_split_long_sentence_at_comma():
    long_text = (
        "Mặt ngoài chiếc túi được phủ một lớp da tổng hợp chống thấm nước cực kỳ dày dặn, "
        "bên trong chia làm ba ngăn rộng rãi đựng vừa điện thoại sạc dự phòng và cả son phấn, "
        "đường kim mũi chỉ may tỉ mỉ sắc nét tới từng chi tiết nhỏ."
    )
    chunks = split_sentences(long_text, max_chars=140)
    assert len(chunks) >= 2
    assert all(len(c) <= 140 for c in chunks)


def test_split_hook_with_multiple_exclamations():
    hook = "Đây rồi! Đúng là cái mẫu ốp lưng chống bẩn tui tìm bấy lâu nay anh em ơi!"
    doc = (
        "Đây rồi! Đúng là cái mẫu ốp lưng chống bẩn tui tìm bấy lâu nay anh em ơi! "
        "Mặt ngoài phủ lớp silicon mịn cầm cực bám tay. Bấm giỏ hàng góc trái nha!"
    )
    hook_sents, body_sents = split_hook_and_body_sentences(hook, doc)
    # Cả 2 câu cảm thán của Hook đều phải nằm trong hook_sents (không bị cắt cụt ở chữ "Đây rồi!")
    assert len(hook_sents) == 2
    assert "Đây rồi!" in hook_sents[0]
    assert "mẫu ốp lưng" in hook_sents[1]
    assert len(body_sents) == 2


def test_generate_closeup_ass_subtitle_only_after_banner(tmp_path: Path):
    words = [
        WordTiming("Đây", 0.0, 0.3),
        WordTiming("rồi!", 0.3, 0.8),
        WordTiming("Mặt", 7.2, 7.5),
        WordTiming("ngoài", 7.5, 7.8),
        WordTiming("phủ", 7.8, 8.1),
        WordTiming("silicon", 8.1, 8.6),
        WordTiming("mịn", 8.6, 9.0),
        WordTiming("cực", 9.0, 9.3),
        WordTiming("đẹp.", 9.3, 9.8),
    ]
    ass_path = tmp_path / "_sub_v1.ass"
    res = generate_closeup_ass_subtitle(
        word_timings=words,
        banner_duration=7.0,
        total_duration=18.0,
        out_ass_path=ass_path,
        cfg=DEFAULT_CONFIG,
    )
    assert res is not None and res.exists()
    content = res.read_text(encoding="utf-8")
    assert "Dialogue:" in content
    # Phần chữ Hook ở giây 0..0.8 không được lặp lại trong phụ đề nửa sau
    assert "ĐÂY RỒI!" not in content
    assert "SILICON" in content
