# Smart TKB

Smart TKB là ứng dụng web hỗ trợ tạo, quản lý và xem thời khóa biểu cho nhà trường.

## Tính năng chính

- Quản lý môn học, giáo viên, lớp và phân công giảng dạy.
- Thùng rác cho bộ thời khóa biểu: giữ nguyên dữ liệu vô thời hạn, không tự động dọn; có thể khôi phục, xóa từng mục hoặc làm rỗng thùng rác khi cần.
- Chỉnh sửa sau xếp lịch: xem trước ảnh hưởng, giữ các tiết hợp lệ, đưa tiết xung đột về kho và lưu bản dự phòng để hoàn tác.
- Xếp thời khóa biểu tự động theo các ràng buộc.
- Lượt xếp đầu ưu tiên xếp đủ tiết, sau đó tối ưu phân bố môn theo ngày, tiết đôi ưu tiên và khoảng trống của giáo viên. Nếu chưa tìm được lịch đầy đủ, hệ thống giữ phương án xếp được nhiều tiết nhất đã tìm thấy; có thể thử xếp lại phần không cố định ở bước cuối.
- Điều chỉnh thời khóa biểu thủ công bằng cách bấm/chạm chọn tiết rồi chọn ô đích hoặc khay.
- Xem lịch theo lớp hoặc giáo viên.
- Quản lý tài khoản Admin và giáo viên.
- Giáo viên có thể xem lịch và gửi nguyện vọng.
- Chia sẻ và xuất thời khóa biểu.
- Xuất Excel theo phôi mẫu: mỗi lớp có hai cột môn–giáo viên, tiêu đề gộp, Times New Roman và viền đen; danh sách GV nghỉ ở sheet riêng. File tải về dùng định dạng `.xlsx`.
- Hỗ trợ kiểm tra dữ liệu và trợ lý AI.

## Chỉnh sửa sau khi đã xếp lịch

Trong workspace, bật **Chỉnh sửa sau xếp lịch**, sửa phân công/dữ liệu/ràng buộc rồi xem danh sách ảnh hưởng trước khi **Áp dụng thay đổi**. Có thể đổi giáo viên, chỉnh số tiết theo chương trình khối, đổi khối của lớp và xử lý phân công liên quan khi bỏ môn dạy hoặc xóa dữ liệu.

Tiết ghim/cố định được bảo vệ; cần bỏ cố định trước nếu thay đổi xung đột với các tiết đó. Tiết còn cần dạy được đưa về Kho tiết chưa xếp; tiết dư do giảm nhu cầu hoặc xóa phân công được tính riêng. Không tự chạy lại bộ xếp lịch.

Mở **Bản dự phòng & lịch sử** để hoàn tác lần thay đổi gần nhất khi project chưa có thay đổi tiếp. Bản dự phòng được giữ đến khi xóa vĩnh viễn project. Bản xem trước có hiệu lực 15 phút và phải tính lại nếu dữ liệu thay đổi. Chức năng này chưa thay đổi số ngày/buổi/tiết của toàn project.

Khởi động lại ứng dụng sau khi cập nhật để tự tạo bảng lưu bản dự phòng và nâng cấp cột thông báo. Kiểm thử chạy thủ công tại máy phát triển; GitHub Actions chỉ kiểm tra cú pháp Python.

## Công nghệ

- **Backend:** FastAPI, SQLAlchemy
- **Database:** PostgreSQL
- **Frontend:** HTML, CSS, JavaScript, Jinja2
- **Server:** Uvicorn

## Cấu trúc và kiểm thử

Xem [hướng dẫn kiến trúc](docs/ARCHITECTURE.md) để tìm mô-đun phụ trách từng phần.

Chạy kiểm thử sau khi cài dependencies và kích hoạt môi trường ảo:

```text
python -m unittest discover -s tests -t . -v
```

Bộ kiểm thử dùng DB trong bộ nhớ, không cần kết nối Neon. Khởi tạo DB của ứng dụng chạy khi FastAPI bắt đầu phục vụ, thay vì khi import mô-đun.

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
