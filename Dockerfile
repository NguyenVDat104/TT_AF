# Dockerfile chuẩn tối ưu RAM cho Render.com (Free 512MB & Paid Tiers)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    LOW_MEMORY_MODE=1 \
    DATA_DIR=/app/data

WORKDIR /app

# Cài đặt FFmpeg (kèm libass đốt phụ đề .ass) và bộ Font chữ hỗ trợ đầy đủ Tiếng Việt
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-noto-core \
    fontconfig \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY MAU_LENH_VIET_KICH_BAN.txt HUONG_DAN.md pyproject.toml ./

RUN mkdir -p /app/data/san_pham /app/data/san_sang_dang /app/data/_tam

EXPOSE 10000

# Bắt buộc chạy --workers 1 để hàng đợi VideoQueueManager đồng nhất và tiết kiệm tối đa RAM trên Render Free
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
