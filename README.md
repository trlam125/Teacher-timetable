# Smart TKB

Hướng dẫn triển khai các giới hạn lưu lượng, upload, WebSocket và proxy:
[SECURITY_DEPLOYMENT.md](docs/SECURITY_DEPLOYMENT.md).

Smart TKB là ứng dụng web hỗ trợ tạo, quản lý và xem thời khóa biểu cho nhà trường.

## Tính năng chính

- Quản lý môn học, giáo viên, lớp và phân công giảng dạy.
- Thùng rác cho bộ thời khóa biểu: giữ nguyên dữ liệu vô thời hạn, không tự động dọn; có thể khôi phục, xóa từng mục hoặc làm rỗng thùng rác khi cần.
- Chỉnh sửa sau xếp lịch: xem trước ảnh hưởng, giữ các tiết hợp lệ, đưa tiết xung đột về kho và lưu bản dự phòng để hoàn tác.
- Xếp thời khóa biểu tự động theo các ràng buộc.
- Chế độ môn **Tối đa 2 tiết/buổi (liền nhau)**: mỗi môn trong một lớp chỉ được 1 tiết hoặc 2 tiết liền nhau trong buổi, không được có tiết thứ 3. Hai tiết cách nhau và mẫu 2 tiết – ngắt 1 tiết – 2 tiết đều không hợp lệ. Sáng/chiều và các ngày tính riêng. Chọn chế độ trong chương trình khối hoặc phân công; áp dụng cho xếp tự động, ghim, chỉnh lịch thủ công và kiểm tra lịch. Mã chế độ lưu trong dữ liệu vẫn là `max_two_consecutive`; lịch cũ được kiểm tra lại theo quy tắc mới khi xếp/chỉnh sửa, các tiết ghim xung đột cần được xử lý trước.
- Lượt xếp đầu ưu tiên xếp đủ tiết, sau đó tối ưu phân bố môn theo ngày, tiết đôi ưu tiên và khoảng trống của giáo viên. Nếu chưa tìm được lịch đầy đủ, hệ thống giữ phương án xếp được nhiều tiết nhất đã tìm thấy; có thể thử xếp lại phần không cố định ở bước cuối.
- Điều chỉnh thời khóa biểu thủ công bằng cách bấm/chạm chọn tiết rồi chọn ô đích hoặc khay.
- Xem lịch theo lớp hoặc giáo viên.
- Quản lý tài khoản Admin và giáo viên.
- Giáo viên có thể xem lịch và gửi nguyện vọng.
- Chia sẻ thời khóa biểu qua liên kết yêu cầu đăng nhập tài khoản; hỗ trợ xuất Excel.
- Xuất Excel theo phôi mẫu: mỗi lớp có hai cột môn–giáo viên, tiêu đề gộp, Times New Roman; khung và hàng tiết dùng viền đen nét liền mảnh, đường ngăn môn–giáo viên dùng nét chấm. Danh sách GV nghỉ ở sheet riêng. File tải về dùng định dạng `.xlsx`.
- Hỗ trợ kiểm tra dữ liệu và trợ lý AI.
- **Nhật ký sự cố hệ thống** trong trang quản lý tài khoản dành cho super admin: xem chung sự cố trợ lý AI và các lần xếp lịch bị lỗi, bị từ chối hoặc còn thiếu tiết. Log ghi project, tài khoản, thời gian và chi tiết tìm kiếm; giữ tối đa 500 sự cố, hiển thị 100 mục mới nhất. Lịch sử AI cũ vẫn được giữ. Mục Chẩn đoán bộ xếp riêng đã được bỏ.
- Import kiểm tra TKB nhận bảng Excel/Word mỗi lớp có cặp cột môn–giáo viên và tiêu đề lớp gộp ô; bỏ qua sheet thống kê “GV không có tiết dạy”. Có thể import lại file Excel do ứng dụng xuất ra; các dòng môn/giáo viên tương ứng trong cùng ô được giữ riêng để phát hiện trùng lớp. Tên giáo viên khác dấu được tính định mức riêng.
- Hỗ trợ cột lớp gộp ô trong `.xls` và cách đánh số tiết xuyên ngày khi các nhãn buổi xác định được ranh giới. Thứ/buổi/tiết sai được báo lỗi, không tự làm tròn hoặc đổi sang ô khác. Kết quả AI cũ được bỏ qua sau khi đổi tệp hay sửa tên môn/giáo viên.
- Kiểm tra TKB từ tệp hoạt động độc lập: kiểm tra trùng lớp, giáo viên, phòng; đối chiếu số tiết theo định mức người dùng nhập. Tệp không chứa ràng buộc của project nên chức năng này chưa tự kiểm tra tiết tránh, tiết ghim hay chế độ tối đa 2 tiết/buổi của project.

## Chỉnh sửa sau khi đã xếp lịch

Trong workspace, bật **Chỉnh sửa sau xếp lịch**, sửa phân công/dữ liệu/ràng buộc rồi xem danh sách ảnh hưởng trước khi **Áp dụng thay đổi**. Có thể đổi giáo viên, chỉnh số tiết theo chương trình khối, đổi khối của lớp và xử lý phân công liên quan khi bỏ môn dạy hoặc xóa dữ liệu.

Công tắc được lưu theo từng bộ thời khóa biểu, mặc định tắt. Khi tắt, các thay đổi tác động đến tiết đã xếp hoặc đã ghim sẽ bị chặn. Đổi tên, thêm tiết tránh ở ô trống và điều chỉnh phần chưa xếp vẫn lưu được nếu hợp lệ. Nếu gặp khóa trong hộp thoại, chọn **Đến công tắc chỉnh sửa** để giữ bản nháp trong lúc bật chế độ. Các thao tác chỉnh tiết trực tiếp, xếp lịch và hoàn tác có luồng riêng.

Tiết ghim/cố định được bảo vệ; cần bỏ cố định trước nếu thay đổi xung đột với các tiết đó. Tiết còn cần dạy được đưa về Kho tiết chưa xếp; tiết dư do giảm nhu cầu hoặc xóa phân công được tính riêng. Không tự chạy lại bộ xếp lịch.

Mở **Lịch sử & sao lưu** để hoàn tác lần thay đổi gần nhất khi project chưa có thay đổi tiếp. Bản dự phòng được giữ đến khi xóa vĩnh viễn project. Bản xem trước có hiệu lực 15 phút và phải tính lại nếu dữ liệu thay đổi. Chức năng này chưa thay đổi số ngày/buổi/tiết của toàn project.

Khởi động lại ứng dụng sau khi cập nhật để tự tạo bảng lưu trạng thái công tắc, bảng lưu bản dự phòng và nâng cấp cột thông báo. GitHub Actions kiểm tra cú pháp Python và JavaScript trên mỗi lần push hoặc pull request.

## Công nghệ

- **Backend:** FastAPI, SQLAlchemy
- **Database:** PostgreSQL
- **Frontend:** HTML, CSS, JavaScript, Jinja2
- **Server:** Uvicorn

## Cấu trúc và kiểm tra mã

- `app/routers/`: xử lý các trang và yêu cầu từ giao diện.
- `app/services/`: nghiệp vụ tài khoản, dữ liệu và chỉnh sửa lịch.
- `app/scheduling/`: ràng buộc và bộ xếp thời khóa biểu.
- `app/schedule_audit/`: đọc tệp và kiểm tra thời khóa biểu.
- `app/templates/`, `app/static/`: giao diện, JavaScript và CSS.

Kiểm tra cú pháp Python bằng lệnh đang dùng trên GitHub Actions:

```text
python -m compileall -q app
```

Kiểm tra cú pháp một tệp JavaScript (Node.js 22+):

```text
node --check app/static/app-entities.js
```

Bộ giải gộp các tiết đơn có cùng tập vị trí hợp lệ theo phân công để giảm số
hoán vị phải tìm kiếm. Ràng buộc tránh tiết, khóa khối/lớp, trùng giáo viên/lớp
và tối đa tiết liên tiếp vẫn được giữ nguyên. Tiết đôi bắt buộc, cụm ghim và
mẫu có điểm neo tiếp tục dùng mô hình theo cụm. Khi lịch đang thiếu tiết nhưng
không còn vị trí trống hợp lệ, cần dùng bước xếp lại các tiết không cố định.

Khởi tạo DB chạy khi ứng dụng bắt đầu phục vụ, thay vì khi import mô-đun.

### Kiểm tra tương thích viền Excel

Hai nút xuất Excel trong workspace cùng tải từ `/projects/{id}/export.xlsx`; đường dẫn `.csv` cũ chuyển hướng về đây. Backend tạo hai sheet **Thời khóa biểu** và **GV nghỉ** bằng openpyxl.

openpyxl 3.1.5 ghi các định nghĩa viền nhưng không xuất `applyBorder` trong `cellXfs` của `xl/styles.xml`. Theo file đã được đối chiếu trên máy gặp lỗi, thêm `applyBorder="1"` giúp Excel hiển thị lại viền. `serialize_timetable_workbook()` áp dụng bước tương thích này sau khi lưu workbook, qua helper `services/excel_compat.py`. Helper chỉ bật cờ cho style tham chiếu viền thực sự có cạnh được định dạng; giữ nguyên ID, nét liền/chấm và các thành phần khác của file. ZIP/XML lỗi sẽ làm xuất file thất bại, thay vì tải xuống file không hợp lệ.

Sau khi triển khai, xuất **file mới** rồi mở cùng file trên máy đang hiển thị đúng và máy từng mất viền. Tắt Gridlines, kiểm tra ở Normal/Zoom 100%, Format Cells → Border, Print Preview và Save As rồi mở lại.

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
