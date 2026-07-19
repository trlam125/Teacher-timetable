# Smart TKB

Smart TKB là ứng dụng web hỗ trợ nhà trường xây dựng, quản lý và chia sẻ thời khóa biểu. Hệ thống có thể tự động xếp lịch theo dữ liệu và các ràng buộc đã nhập, sau đó cho phép quản trị viên tinh chỉnh trực tiếp bằng thao tác kéo-thả.

## Tính năng chính

* Quản lý môn học, tổ chuyên môn, giáo viên, khối, lớp và phân công giảng dạy.
* Xếp thời khóa biểu tự động, hạn chế trùng giáo viên và trùng lớp.
* Kéo-thả tiết học để điều chỉnh lịch thủ công.
* Thiết lập tiết tránh cho giáo viên, lớp học và giới hạn số tiết dạy mỗi ngày.
* Xem thời khóa biểu theo lớp hoặc theo giáo viên.
* Cổng riêng cho giáo viên xem lịch, cập nhật tài khoản và gửi nguyện vọng.
* Chia sẻ thời khóa biểu bằng liên kết và xuất dữ liệu CSV.
* Nhân bản một bộ thời khóa biểu để sử dụng cho học kỳ tiếp theo.

## Quy trình đăng ký tài khoản

1. Giáo viên đăng ký bằng họ tên, email và mật khẩu.
2. Quản trị viên mở **Quản lý tài khoản**, chọn hồ sơ giáo viên tương ứng và xác nhận.

Khi xác nhận, quản trị viên có thể gắn tài khoản với một hồ sơ giáo viên có sẵn chưa có tài khoản, hoặc tạo hồ sơ giáo viên mới từ tên giáo viên mà người đăng ký đã nhập.

## Yêu cầu hệ thống

* Python 3.11 trở lên.
* PostgreSQL đang hoạt động.
* `pip` để cài các thư viện Python.
* Trình duyệt web hiện đại.

## Cài đặt

### 1\. Mở thư mục dự án

```powershell
cd ./Teacher-timetable
```

### 2\. Tạo môi trường Python

Windows PowerShell:

```powershell
python -m venv venv
./venv/Scripts/Activate.ps1
```

Linux hoặc macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3\. Cài thư viện

```bash
pip install -r requirements.txt
```

### 4\. Tạo database PostgreSQL

```sql
CREATE DATABASE teacher\_timetable;
```

### 5\. Tạo file cấu hình `.env`

Tạo file `.env` tại thư mục gốc của dự án:

```env
APP\_ENV=production
DATABASE\_URL=postgresql+psycopg://postgres:MAT\_KHAU\_POSTGRES@localhost:5432/teacher\_timetable
SECRET\_KEY=THAY\_BANG\_CHUOI\_BI\_MAT\_NGAU\_NHIEN
BOOTSTRAP\_ADMIN\_EMAIL=admin@example.com
BOOTSTRAP\_ADMIN\_PASSWORD=mat-khau-manh-it-nhat-8-ky-tu
SESSION\_TTL\_SECONDS=43200
SEED\_DEMO\_DATA=false
```

Có thể tạo `SECRET\_KEY` bằng lệnh:

```bash
python -c "import secrets; print(secrets.token\_urlsafe(64))"
```

## Cấu hình quên mật khẩu và SMTP

Trong môi trường công khai, chức năng quên mật khẩu chỉ gửi liên kết đặt lại qua SMTP. Liên kết kiểm thử chỉ được hiển thị khi đồng thời thỏa mãn hai điều kiện:

* `APP\_ENV=development`.
* Truy cập ứng dụng bằng `localhost` hoặc `127.0.0.1`.

Ví dụ cấu hình SMTP dùng cổng `587` với STARTTLS:

```env
SMTP\_HOST=smtp.example.com
SMTP\_PORT=587
SMTP\_USER=your-account@example.com
SMTP\_PASSWORD=your-app-password
SMTP\_FROM=your-account@example.com
SMTP\_SSL=false
SMTP\_STARTTLS=true
```

Nếu nhà cung cấp email yêu cầu SSL trực tiếp, có thể dùng:

```env
SMTP\_HOST=smtp.example.com
SMTP\_PORT=465
SMTP\_USER=your-account@example.com
SMTP\_PASSWORD=your-app-password
SMTP\_FROM=your-account@example.com
SMTP\_SSL=true
SMTP\_STARTTLS=false
```

`SMTP\_USER` là tài khoản dùng để gửi thư. Email nhận là địa chỉ mà người dùng đã đăng ký trong hệ thống.

## Chạy ứng dụng

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Mở trình duyệt tại [http://127.0.0.1:8000](http://127.0.0.1:8000).

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

## Công nghệ sử dụng

|Thành phần|Công nghệ|
|-|-|
|Backend|FastAPI|
|ORM|SQLAlchemy 2.0|
|Database|PostgreSQL|
|Template|Jinja2|
|Xác thực|Cookie session, PBKDF2-SHA256, itsdangerous|
|Frontend|HTML, CSS, JavaScript thuần|
|Server|Uvicorn|




## Chạy kiểm thử logic

```bash
python -m unittest discover -s tests -v
```
