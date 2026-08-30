# Smart TKB

**Smart TKB** là ứng dụng web hỗ trợ nhà trường xây dựng, quản lý và chia sẻ thời khóa biểu. Hệ thống có thể **xếp lịch tự động theo các ràng buộc** và cho phép quản trị viên **kéo-thả để điều chỉnh lịch** sau khi xếp.

## Tính năng chính

* Quản lý môn học, tổ chuyên môn, giáo viên, khối và lớp.
* Quản lý phân công giảng dạy.
* Tự động xếp thời khóa biểu, hạn chế trùng giáo viên và lớp.
* Thiết lập tiết cố định, tiết cần tránh và giới hạn số tiết/ngày.
* Kéo-thả để điều chỉnh thời khóa biểu thủ công.
* Xem thời khóa biểu theo lớp hoặc giáo viên.
* Cổng riêng cho giáo viên xem lịch và gửi nguyện vọng.
* Đăng ký tài khoản giáo viên qua link mời và xác thực OTP email.
* Chia sẻ thời khóa biểu bằng liên kết và xuất CSV.
* Nhân bản bộ thời khóa biểu cho học kỳ mới.

## Công nghệ sử dụng

| Thành phần | Công nghệ                                   |
| ---------- | ------------------------------------------- |
| Backend    | FastAPI                                     |
| ORM        | SQLAlchemy 2.0                              |
| Database   | PostgreSQL                                  |
| Template   | Jinja2                                      |
| Frontend   | HTML, CSS, JavaScript                       |
| Xác thực   | Cookie Session, PBKDF2-SHA256, itsdangerous |
| Server     | Uvicorn                                     |

## Yêu cầu hệ thống

* Python 3.11+
* PostgreSQL
* pip

## Cài đặt

### 1. Mở thư mục dự án

```bash
cd Teacher-timetable
```

### 2. Tạo môi trường ảo

**Windows PowerShell:**

```powershell
python -m venv venv
./venv/Scripts/Activate.ps1
```

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Cài đặt thư viện

```bash
pip install -r requirements.txt
```

### 4. Tạo PostgreSQL database

```sql
CREATE DATABASE teacher_timetable;
```

### 5. Cấu hình môi trường

Tạo file `.env` tại thư mục gốc:

```env
APP_ENV=production
APP_BASE_URL=https://tkb.example.com

DATABASE_URL=postgresql+psycopg://postgres:PASSWORD@localhost:5432/teacher_timetable
SECRET_KEY=YOUR_SECRET_KEY

BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=YOUR_PASSWORD

SUPER_ADMIN_USER_ID=1
SESSION_TTL_SECONDS=43200
SEED_DEMO_DATA=false
```

Tạo `SECRET_KEY` ngẫu nhiên:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Cấu hình Email / SMTP

SMTP được sử dụng để gửi **OTP đăng ký** và **liên kết đặt lại mật khẩu**.

Ví dụ với STARTTLS cổng `587`:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-account@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-account@example.com
SMTP_SSL=false
SMTP_STARTTLS=true
```

Nếu nhà cung cấp sử dụng SSL cổng `465`:

```env
SMTP_PORT=465
SMTP_SSL=true
SMTP_STARTTLS=false
```

Khi triển khai production, `APP_BASE_URL` cần được đặt thành địa chỉ công khai của ứng dụng.

## Chạy ứng dụng

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Truy cập:

```text
http://127.0.0.1:8000
```

## Hướng dẫn sử dụng

### Quản trị viên

1. Đăng nhập tài khoản Admin.
2. Tạo bộ thời khóa biểu.
3. Nhập môn học, giáo viên, lớp và phân công giảng dạy.
4. Thiết lập ràng buộc, tiết cố định và tiết cần tránh.
5. Xếp thời khóa biểu tự động.
6. Kéo-thả để điều chỉnh nếu cần.
7. Xem, chia sẻ hoặc xuất thời khóa biểu.

### Giáo viên

1. Mở link đăng ký do Admin cung cấp.
2. Chọn đúng hồ sơ giáo viên và tạo tài khoản.
3. Nhập OTP được gửi qua email để kích hoạt.
4. Đăng nhập và xem thời khóa biểu cá nhân.
5. Gửi nguyện vọng hoặc các tiết cần tránh.
6. Cập nhật thông tin tài khoản khi cần.

## Cấu trúc hoạt động

```text
Browser
   │
   ▼
FastAPI
   │
   ├── Jinja2 Templates
   ├── Authentication
   ├── Scheduling Logic
   └── SQLAlchemy
          │
          ▼
      PostgreSQL
```

## Vai trò người dùng

Hệ thống gồm hai nhóm người dùng chính:

* **Admin:** quản lý dữ liệu, phân công, ràng buộc, tài khoản giáo viên và thời khóa biểu.
* **Giáo viên:** xem lịch cá nhân, quản lý tài khoản và gửi nguyện vọng.