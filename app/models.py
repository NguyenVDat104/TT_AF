"""Pydantic models & cấu trúc dữ liệu cho API và lưu trữ trạng thái."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

VideoStateLiteral = Literal[
    "chua_lam",
    "trong_hang_doi",
    "dang_lam",
    "cho_duyet",
    "da_duyet",
    "da_loai",
    "loi",
]


class VideoScript(BaseModel):
    video_no: int
    hook: str = ""
    doc: str = ""


class ProductContentData(BaseModel):
    slug: str
    ten: str = ""
    link: str = ""
    hashtag: str = ""
    videos: List[VideoScript] = Field(default_factory=list)
    raw_text: str = ""


class SlotFrameConfig(BaseModel):
    cx: float = 0.5
    cy: float = 0.5
    z: float = 1.0
    use_video: bool = True
    manual: bool = False


class NewProductRequest(BaseModel):
    name: str
    ten_hien_thi: Optional[str] = None
    link: Optional[str] = ""
    hashtag: Optional[str] = ""


class SaveContentRequest(BaseModel):
    product: str
    content: str


class BulkScriptRequest(BaseModel):
    text: str
    preview_only: bool = False


class SwapSlotsRequest(BaseModel):
    product: str
    slot_a: Literal["anh_trai", "anh_phai", "can_canh"]
    slot_b: Literal["anh_trai", "anh_phai", "can_canh"]


class AssignFileSlotRequest(BaseModel):
    product: str
    slot: Literal["anh_trai", "anh_phai", "can_canh"]
    filename: str


class SaveFramesRequest(BaseModel):
    product: str
    frames: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    reset_auto: bool = False


class RenderRequest(BaseModel):
    product: Optional[str] = None
    products: Optional[List[str]] = None
    video_no: Optional[int] = None
    video_nos: Optional[List[int]] = None
    force: bool = False


class QueueControlRequest(BaseModel):
    action: Literal["pause", "resume", "clear", "remove"]
    product: Optional[str] = None
    video_no: Optional[int] = None


class VideoReviewRequest(BaseModel):
    product: str
    video_no: int
    action: Literal["approve", "reject", "redo"]


class VoiceTestRequest(BaseModel):
    text: str = "Đây rồi! Đúng là cái mẫu ốp lưng chống bẩn tui đang tìm bấy lâu nay anh em ơi!"
    config_override: Optional[Dict[str, Any]] = None


class OpenFolderRequest(BaseModel):
    target: str = "san_pham"
    product: Optional[str] = None
    date_folder: Optional[str] = None
