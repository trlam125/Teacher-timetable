# Smart TKB

Smart TKB là ứng dụng web hỗ trợ tạo, quản lý và xem thời khóa biểu cho nhà trường.

## Tính năng chính

- Quản lý môn học, giáo viên, lớp và phân công giảng dạy.
- Thùng rác cho bộ thời khóa biểu: giữ nguyên dữ liệu vô thời hạn, không tự động dọn; có thể khôi phục, xóa từng mục hoặc làm rỗng thùng rác khi cần.
- Chỉnh sửa sau xếp lịch: xem trước ảnh hưởng, giữ các tiết hợp lệ, đưa tiết xung đột về kho và lưu bản dự phòng để hoàn tác.
- Xếp thời khóa biểu tự động theo các ràng buộc.
- Chế độ môn **Tối đa 2 tiết liên tiếp/buổi**: chọn trong chương trình khối hoặc phân công để chặn chuỗi 3 tiết cùng môn trong cùng lớp và cùng buổi. Sáng/chiều và các ngày tính riêng; mẫu 2 tiết – ngắt 1 tiết – 2 tiết vẫn hợp lệ. Chế độ này cho phép tiết đơn, không bắt buộc ghép đôi; áp dụng cho xếp tự động, ghim và chỉnh lịch thủ công.
- Lượt xếp đầu ưu tiên xếp đủ tiết, sau đó tối ưu phân bố môn theo ngày, tiết đôi ưu tiên và khoảng trống của giáo viên. Nếu chưa tìm được lịch đầy đủ, hệ thống giữ phương án xếp được nhiều tiết nhất đã tìm thấy; có thể thử xếp lại phần không cố định ở bước cuối.
- Điều chỉnh thời khóa biểu thủ công bằng cách bấm/chạm chọn tiết rồi chọn ô đích hoặc khay.
- Xem lịch theo lớp hoặc giáo viên.
- Quản lý tài khoản Admin và giáo viên.
- Giáo viên có thể xem lịch và gửi nguyện vọng.
- Chia sẻ thời khóa biểu qua liên kết yêu cầu đăng nhập tài khoản; hỗ trợ xuất Excel.
- Xuất Excel theo phôi mẫu: mỗi lớp có hai cột môn–giáo viên, tiêu đề gộp, Times New Roman; khung và hàng tiết dùng viền đen nét liền mảnh, đường ngăn môn–giáo viên dùng nét chấm. Danh sách GV nghỉ ở sheet riêng. File tải về dùng định dạng `.xlsx`.
- Hỗ trợ kiểm tra dữ liệu và trợ lý AI.
- Import kiểm tra TKB nhận bảng Excel mỗi lớp có cặp cột môn–giáo viên và tiêu đề lớp gộp ô; bỏ qua sheet thống kê “GV không có tiết dạy”. Có thể import lại file Excel do ứng dụng xuất ra.

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

Bộ kiểm thử không cần kết nối Neon. Khởi tạo DB của ứng dụng chạy khi FastAPI bắt đầu phục vụ, thay vì khi import mô-đun.

### Kiểm tra tương thích viền Excel

Hai nút xuất Excel trong workspace cùng tải từ `/projects/{id}/export.xlsx`; đường dẫn `.csv` cũ chuyển hướng về đây. Backend tạo hai sheet **Thời khóa biểu** và **GV nghỉ** bằng openpyxl.

openpyxl 3.1.5 ghi các định nghĩa viền nhưng không xuất `applyBorder` trong `cellXfs` của `xl/styles.xml`. Theo file đã được đối chiếu trên máy gặp lỗi, thêm `applyBorder="1"` giúp Excel hiển thị lại viền. `serialize_timetable_workbook()` áp dụng bước tương thích này sau khi lưu workbook, qua helper `services/excel_compat.py`. Helper chỉ bật cờ cho style tham chiếu viền thực sự có cạnh được định dạng; giữ nguyên ID, nét liền/chấm và các thành phần khác của file. ZIP/XML lỗi sẽ làm xuất file thất bại, thay vì tải xuống file không hợp lệ.

Chạy riêng kiểm thử xuất Excel bằng dữ liệu giả, không kết nối Neon:

```text
python -m unittest tests.test_excel_export -v
```

Kiểm thử đối chiếu XML trước/sau, nội dung, công thức, ô gộp, định dạng, thiết lập in, cả hai sheet và phản hồi tải file. GitHub Actions vẫn chỉ kiểm tra cú pháp Python.

Sau khi triển khai, xuất **file mới** rồi mở cùng file trên máy đang hiển thị đúng và máy từng mất viền. Tắt Gridlines, kiểm tra ở Normal/Zoom 100%, Format Cells → Border, Print Preview và Save As rồi mở lại. Kiểm thử tự động không thay thế bước xác nhận thực tế trên hai máy này.

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
