# Smart TKB

Smart TKB là ứng dụng web hỗ trợ nhà trường xây dựng, quản lý và chia sẻ thời khóa biểu. Hệ thống có thể tự động xếp lịch theo dữ liệu và ràng buộc đã nhập, sau đó cho phép quản trị viên tinh chỉnh trực tiếp bằng thao tác kéo-thả.

## Tính năng chính

- Quản lý môn học, tổ chuyên môn, giáo viên, khối, lớp và phân công giảng dạy.
- Xếp thời khóa biểu tự động, hạn chế trùng giáo viên và trùng lớp.
- Xếp toàn bộ lịch hoặc chỉ bổ sung các tiết còn thiếu.
- Kéo-thả tiết học để điều chỉnh lịch thủ công.
- Ghim tiết học vào vị trí cố định.
- Cấu hình ngày học, số buổi, số tiết mỗi buổi và các buổi không sử dụng.
- Thiết lập tiết tránh cho giáo viên, lớp học và giới hạn số tiết dạy mỗi ngày.
- Xem thời khóa biểu theo lớp hoặc theo giáo viên.
- Cổng riêng cho giáo viên xem lịch, cập nhật tài khoản và gửi nguyện vọng.
- Quản trị viên duyệt, từ chối hoặc áp dụng nguyện vọng của giáo viên.
- Chia sẻ thời khóa biểu bằng liên kết và xuất dữ liệu CSV.
- Nhân bản một bộ thời khóa biểu để sử dụng cho học kỳ tiếp theo.
- Khôi phục mật khẩu bằng liên kết có thời hạn và xác minh “Tôi không phải là robot”.

## Quy trình đăng ký tài khoản:

1. Giáo viên đăng ký bằng họ tên, email và mật khẩu.
2. Tài khoản được tạo ở trạng thái `pending`.
3. Quản trị viên mở **Quản lý tài khoản**, chọn hồ sơ giáo viên tương ứng và xác nhận.
4. Tài khoản chuyển thành `teacher` và được truy cập cổng giáo viên.
5. Khi cần, quản trị viên có thể chủ động nâng một tài khoản `teacher` lên `admin` trong trang quản lý tài khoản.

Khi xác nhận, quản trị viên có thể gắn tài khoản với một hồ sơ giáo viên có sẵn chưa có tài khoản, hoặc tạo hồ sơ giáo viên mới từ tên giáo viên mong muốn mà người đăng ký đã nhập.

## Yêu cầu hệ thống

- Python 3.11 trở lên.
- PostgreSQL đang hoạt động.
- `pip` để cài các thư viện Python.
- Trình duyệt web hiện đại.

## Cài đặt

### 1. Tải mã nguồn và mở thư mục dự án

```powershell
cd D:\Teacher-timetable
```

### 2. Tạo môi trường Python

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Linux hoặc macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Cài thư viện

```bash
pip install -r requirements.txt
```

### 4. Tạo database PostgreSQL

Tạo database có tên `teacher_timetable` bằng pgAdmin hoặc câu lệnh:

```sql
CREATE DATABASE teacher_timetable;
```

### 5. Tạo file cấu hình

Tạo file `.env` tại thư mục gốc của dự án:

```env
DATABASE_URL=postgresql+psycopg://postgres:MAT_KHAU_POSTGRES@localhost:5432/teacher_timetable
SECRET_KEY=THAY_BANG_CHUOI_BI_MAT_NGAU_NHIEN
```

Có thể tạo `SECRET_KEY` bằng lệnh:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"

## Cấu hình quên mật khẩu

Khi chưa cấu hình máy chủ gửi thư, ứng dụng hiển thị liên kết đặt lại ngay trên trang để kiểm thử trong môi trường local.

Để gửi liên kết qua email, thêm các biến sau vào `.env`:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-account@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-account@example.com
SMTP_STARTTLS=true
```

Nếu nhà cung cấp email yêu cầu kết nối SSL trực tiếp, có thể dùng:

```env
SMTP_PORT=465
SMTP_SSL=true
SMTP_STARTTLS=false
```

## Chạy ứng dụng

Windows PowerShell:

```powershell
.\run.ps1
```

Hoặc chạy trực tiếp:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Mở trình duyệt tại [http://127.0.0.1:8000](http://127.0.0.1:8000).

Ứng dụng tự tạo bảng và bổ sung các cột còn thiếu khi khởi động.

## Tài khoản quản trị ban đầu

Khi database chưa có tài khoản quản trị mẫu, ứng dụng tự tạo:

| Email | Mật khẩu | Vai trò |
|---|---|---|
| `admin@gmail.com` | `123456` | Quản trị viên |

Hãy đổi thông tin đăng nhập mặc định trước khi sử dụng trong môi trường thật.

Lần khởi động đầu tiên cũng tạo một bộ thời khóa biểu mẫu gồm hai lớp, ba giáo viên và ba môn học.

## Hướng dẫn sử dụng

### Dành cho quản trị viên

1. Đăng nhập bằng tài khoản admin.
2. Tạo một bộ thời khóa biểu và nhập tên trường, số ngày, số buổi và số tiết mỗi buổi.
3. Nhập dữ liệu theo thứ tự:
   1. Môn học.
   2. Tổ chuyên môn.
   3. Giáo viên.
   4. Khối hoặc nhóm lớp.
   5. Lớp học.
   6. Phân công giảng dạy.
   7. Ràng buộc và các tiết cần tránh.
4. Mở **Quản lý tài khoản** để xác nhận tài khoản đang chờ và gắn tài khoản với đúng giáo viên.
5. Kiểm tra các tiết cố định, buổi khóa và nguyện vọng giáo viên.
6. Chọn chức năng xếp lịch tự động.
7. Kéo-thả để tinh chỉnh nếu cần.
8. Chia sẻ lịch hoặc xuất file CSV.

Quản trị viên chỉ được duyệt và nâng quyền các tài khoản giáo viên thuộc bộ thời khóa biểu mình quản lý.

### Dành cho giáo viên

1. Đăng ký tài khoản.
2. Chờ quản trị viên xác nhận và gắn với hồ sơ giáo viên.
3. Tải lại trang hoặc đăng nhập lại sau khi được duyệt.
4. Xem lịch dạy cá nhân tại cổng giáo viên.
5. Gửi các tiết mong muốn, các tiết cần tránh và ghi chú cho quản trị viên.
6. Cập nhật email hoặc mật khẩu trong trang tài khoản cá nhân.

## Cấu trúc dự án

```text
Teacher-timetable/
├── app/
│   ├── main.py                    # FastAPI, SQLAlchemy, xác thực và thuật toán xếp lịch
│   ├── static/
│   │   ├── app.js                 # Tương tác giao diện quản trị
│   │   ├── style.css              # Kiểu giao diện chính
│   │   ├── auth-extra.css         # Kiểu giao diện tài khoản và khôi phục mật khẩu
│   │   └── preferences.css        # Kiểu giao diện nguyện vọng giáo viên
│   └── templates/
│       ├── landing.html
│       ├── auth.html
│       ├── user_pending.html
│       ├── users.html
│       ├── forgot_password.html
│       ├── reset_password.html
│       ├── projects.html
│       ├── workspace.html
│       ├── teacher_portal.html
│       ├── teacher_account.html
│       ├── teacher_preferences.html
│       └── share.html
├── requirements.txt
├── run.ps1
└── README.md
```

## Công nghệ sử dụng

| Thành phần | Công nghệ |
|---|---|
| Backend | FastAPI |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL |
| Template | Jinja2 |
| Xác thực | Cookie session, PBKDF2-SHA256, itsdangerous |
| Frontend | HTML, CSS, JavaScript thuần |
| Server | Uvicorn |

## Lưu ý bảo mật

- Thay mật khẩu quản trị mặc định ngay sau khi cài đặt.
- Sử dụng `SECRET_KEY` dài, ngẫu nhiên và không chia sẻ công khai.
- Không commit file `.env`.
- Cấu hình SMTP khi triển khai để liên kết đặt lại mật khẩu không hiển thị trực tiếp trên giao diện.
- Sử dụng mật khẩu ứng dụng nếu nhà cung cấp email hỗ trợ.
