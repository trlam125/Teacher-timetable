# Smart TKB

Smart TKB là ứng dụng web hỗ trợ tạo, quản lý và xem thời khóa biểu cho nhà trường.

## Tính năng chính

- Quản lý môn học, giáo viên, lớp và phân công giảng dạy.
- Xếp thời khóa biểu tự động theo các ràng buộc.
- Điều chỉnh thời khóa biểu thủ công bằng cách bấm/chạm chọn tiết rồi chọn ô đích hoặc khay.
- Xem lịch theo lớp hoặc giáo viên.
- Quản lý tài khoản Admin và giáo viên.
- Giáo viên có thể xem lịch và gửi nguyện vọng.
- Chia sẻ và xuất thời khóa biểu.
- Hỗ trợ kiểm tra dữ liệu và trợ lý AI.

## Công nghệ

- **Backend:** FastAPI, SQLAlchemy
- **Database:** PostgreSQL
- **Frontend:** HTML, CSS, JavaScript, Jinja2
- **Server:** Uvicorn

## Yêu cầu

- Python 3.11+
- PostgreSQL
- pip

## Cài đặt

```bash
python -m venv .venv
```

Kích hoạt môi trường ảo trên Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Cài thư viện:

```bash
pip install -r requirements.txt
```

Tạo file `.env` từ `.env.example` và cấu hình kết nối PostgreSQL cùng các biến cần thiết.

## Chạy ứng dụng

Có thể chạy nhanh bằng:

```text
run-local.bat
```

Hoặc chạy trực tiếp:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Sau đó truy cập:

```text
http://127.0.0.1:8000
```

## Tài khoản

Hệ thống hỗ trợ hai nhóm người dùng chính:

- **Admin:** quản lý dữ liệu và thời khóa biểu.
- **Giáo viên:** xem thời khóa biểu và gửi nguyện vọng.
