# Smart TKB — Xếp thời khóa biểu tự động

Ứng dụng web hỗ trợ xây dựng và quản lý thời khóa biểu trường học. Hệ thống tự động tìm phương án xếp lịch không trùng giờ, sau đó cho phép tinh chỉnh thủ công bằng kéo-thả.

## Tính năng

- **Xếp lịch tự động** — thuật toán tìm kiếm ngẫu nhiên có trọng số, chạy nhiều lần và chọn phương án tốt nhất.
- **Tinh chỉnh trực quan** — kéo-thả tiết học vào ô trên lịch, xem theo lớp hoặc theo giáo viên.
- **Quản lý đầy đủ dữ liệu** — môn học, tổ chuyên môn, giáo viên, khối, lớp, phân công giảng dạy.
- **Ràng buộc linh hoạt** — đặt tiết tránh/nghỉ cho giáo viên và lớp; giới hạn số tiết dạy tối đa mỗi ngày; số tiết liên tiếp tối đa theo môn.
- **Tiết cố định** — ghim một tiết vào ô cụ thể, bộ xếp lịch sẽ giữ nguyên vị trí đó.
- **Hòm thư nguyện vọng** — giáo viên đăng nhập, chọn tiết mong muốn/cần tránh và gửi cho quản trị viên xét duyệt.
- **Cổng giáo viên** — mỗi giáo viên có tài khoản riêng, xem lịch dạy cá nhân và gửi nguyện vọng.
- **Chia sẻ & xuất** — chia sẻ lịch bằng link token, xuất ra file CSV.
- **Nhân bản dự án** — sao chép toàn bộ cấu hình sang dự án mới để bắt đầu kỳ học tiếp theo.

## Yêu cầu

- Python 3.11 trở lên
- PostgreSQL đang chạy và đã có database `teacher_timetable`
- Các gói trong `requirements.txt`

## Cài đặt

```bash
# 1. Tạo môi trường ảo
python -m venv .venv

# 2. Kích hoạt môi trường ảo
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

# 3. Cài đặt thư viện
pip install -r requirements.txt

# 4. Tạo file cấu hình môi trường
# Windows PowerShell
Copy-Item .env.example .env
```

Mở `.env` và sửa mật khẩu PostgreSQL cùng `SECRET_KEY`:

```env
DATABASE_URL=postgresql+psycopg://postgres:MAT_KHAU@localhost:5432/teacher_timetable
SECRET_KEY=CHUOI_BI_MAT_NGAU_NHIEN
```

Tạo `SECRET_KEY` bằng lệnh:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Chuẩn bị PostgreSQL

Trong pgAdmin, tạo database có tên:

```text
teacher_timetable
```

Ứng dụng sẽ tự tạo các bảng khi chạy lần đầu. File `.env` thật không được đưa lên GitHub; chỉ `.env.example` được commit.

## Chạy ứng dụng

**Windows (PowerShell):**

```powershell
.\run.ps1
```

**Hoặc chạy trực tiếp:**

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Truy cập tại: [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Tài khoản demo

| Email | Mật khẩu | Vai trò |
|---|---|---|
| `demo@school.vn` | `123456` | Quản trị viên |

Tài khoản demo được tạo tự động khi khởi động lần đầu, kèm một dự án mẫu với 2 lớp, 3 giáo viên và 3 môn học.

## Quy trình sử dụng

1. Đăng ký hoặc đăng nhập với tài khoản quản trị viên.
2. Tạo **dự án** mới (đặt tên, số ngày, số buổi, số tiết/buổi).
3. Lần lượt thêm dữ liệu theo 7 bước trong giao diện:
   1. Môn học
   2. Tổ chuyên môn
   3. Giáo viên
   4. Khối / nhóm lớp
   5. Lớp học
   6. Phân công giảng dạy
   7. Ràng buộc (tiết tránh, giới hạn tải)
4. (Tùy chọn) Cấp tài khoản cho giáo viên, chia sẻ link nguyện vọng và duyệt các đề xuất nhận được.
5. Nhấn **Xếp tự động** để tạo lịch.
6. Tinh chỉnh bằng kéo-thả nếu cần, sau đó xuất CSV hoặc in PDF.

## Cấu trúc dự án

```
teacher-timetable/
├── app/
│   ├── main.py              # Toàn bộ logic backend (FastAPI + SQLAlchemy)
│   ├── static/
│   │   ├── app.js           # Giao diện frontend (Vanilla JS)
│   │   ├── style.css        # Stylesheet chính
│   │   └── preferences.css  # Stylesheet trang nguyện vọng
│   └── templates/           # Jinja2 HTML templates
│       ├── landing.html
│       ├── auth.html
│       ├── projects.html
│       ├── workspace.html
│       ├── teacher_portal.html
│       ├── teacher_preferences.html
│       ├── teacher_account.html
│       └── share.html
├── .env.example             # Mẫu cấu hình PostgreSQL và khóa bí mật
├── requirements.txt
├── run.ps1
└── README.md
```

## Stack kỹ thuật

| Thành phần | Công nghệ |
|---|---|
| Web framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL 18 |
| Template engine | Jinja2 |
| Auth | Cookie session + PBKDF2-SHA256 + itsdangerous |
| Frontend | Vanilla JS, CSS |
| Server | Uvicorn |
