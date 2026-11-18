# Hướng Dẫn Triển Khai Lên Render.com (Chạy Tự Động Trên Internet)

Dự án đã được đóng gói sẵn **`Dockerfile`** và **`render.yaml`** (chế độ tiết kiệm bộ nhớ `< 250 MB RAM`, nhúng sẵn `FFmpeg` + Font Tiếng Việt, bảo mật bằng mật khẩu `APP_PASSWORD` và tải trọn bộ `.zip` về điện thoại/máy tính).

---

## Bước 1: Đẩy mã nguồn lên GitHub (Chỉ mất 2 phút)

1. Đăng nhập GitHub và tạo 1 repository mới (nên chọn **Private** để bảo mật dự án), ví dụ: `xuong-video-tiktok`.
2. Mở cửa sổ dòng lệnh (PowerShell / Terminal) tại thư mục `C:\ToolsEB` và chạy lần lượt:

```powershell
git init
git add .
git commit -m "Deploy Xuong Video TikTok len Render"
git branch -M main
git remote add origin https://github.com/<TEN_GITHUB_CUA_BAN>/xuong-video-tiktok.git
git push -u origin main
```
*(File `.gitignore` đã cấu hình sẵn để không đẩy nhầm thư mục nặng `.venv/`, `san_pham/`, `_tam/` lên GitHub).*

---

## Bước 2: Triển khai Tự động bằng Render Blueprint (`render.yaml`)

1. Đăng nhập vào **https://dashboard.render.com/** (bằng tài khoản GitHub của bạn).
2. Trên góc phải, bấm nút **New +** → chọn **Blueprint**.
3. Chọn repository **`xuong-video-tiktok`** vừa đẩy lên ở Bước 1.
4. Render sẽ tự động đọc file `render.yaml` (vùng máy chủ `Singapore` gần Việt Nam nhất, gói `Free`, môi trường `Docker`) và hỏi bạn 1 ô duy nhất:
   - **`APP_PASSWORD`**: Nhập mật khẩu quản trị của riêng bạn (ví dụ: `MatKhauManh@2026`).
5. Bấm **Apply** và chờ khoảng **3–4 phút** để Render cài đặt `FFmpeg` + khởi chạy server.
6. Khi hiện chữ **`Live`** màu xanh lá, bấm vào đường link `https://xuong-video-tiktok-xxxx.onrender.com`:
   - Nhập tài khoản: **`admin`**
   - Nhập mật khẩu: **`APP_PASSWORD`** bạn vừa đặt ở trên.

---

## Bước 3: Bí quyết Giữ Server Gói Free Không Tự Ngủ & Không Mất Video

Vì bạn chọn **Gói Render Free ($0)**:

1. **Cách chống tự ngủ sau 15 phút (Miễn phí 100%)**:
   - Bình thường Render Free sẽ tự tắt nếu 15 phút không có truy cập. Nếu bạn muốn server thức liên tục khi đang treo hàng đợi làm 20–30 video:
   - Vào trang miễn phí **https://cron-job.org** hoặc **https://uptimerobot.com**.
   - Tạo 1 bộ ping định kỳ mỗi **10 phút** gọi vào đường dẫn:
     `https://<link-render-cua-ban>.onrender.com/healthz`
   - *(Cổng `/healthz` đã được mình thiết kế mở riêng không cần mật khẩu để dịch vụ ping giữ cho server của bạn luôn thức!).*

2. **Quy trình làm việc an toàn trên Gói Free**:
   - Vào web bằng máy tính hoặc điện thoại → Dán kịch bản → Tải 3 file tư liệu lên → Bấm **Làm cả 3 video**.
   - Vào tab **3. Duyệt video** bấm **✓ Duyệt** (hoặc tải lẻ bằng nút **⬇ Tải MP4**).
   - Sang tab **4. Sẵn sàng đăng** bấm nút **📦 Tải ZIP ngày ...** để tải 1 cục toàn bộ video `.mp4` + file tổng hợp `00_TONG_HOP_CAPTION.txt` về điện thoại/máy tính ngay!
   - *(Nếu sau này nâng lên gói Render Starter có gắn ổ cứng Persistent Disk tại `/var/data`, bạn chỉ cần đổi biến `DATA_DIR=/var/data` trong tab Environment của Render là dữ liệu được lưu vĩnh viễn).*
