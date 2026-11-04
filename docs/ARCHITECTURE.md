# Cấu trúc Smart TKB

Ứng dụng tiếp tục dùng FastAPI, SQLAlchemy và giao diện Jinja/JavaScript. Các mô-đun được chia theo trách nhiệm để có thể kiểm tra từng phần độc lập.

## Các thư mục chính

```text
app/
  main.py                 Tạo ứng dụng và điều phối vòng đời khởi động
  config.py               Cấu hình kết nối DB và khóa ký phiên
  settings.py             Cấu hình nghiệp vụ, thời gian, tài khoản và giao diện
  logging_config.py       Logger dùng chung
  models.py               Mô hình dữ liệu SQLAlchemy
  routers/                HTTP/WebSocket, phân quyền và dữ liệu đầu vào
  services/               Điều phối thao tác và giao dịch
    authentication/       Đăng nhập, phiên, mật khẩu, email và quyền truy cập
    entities/             Giáo viên, lớp, môn, phân công và chương trình khối
    schedule_operations/  Kiểm tra, đặt tiết và quản lý block
    bootstrap/            Khởi tạo DB và migration
  scheduling/
    rules.py              Quy tắc và cấu trúc block
    solver/
      api.py              Các chế độ xếp từ trống, bổ sung, xếp lại
      problem.py          Đọc dữ liệu, kiểm tra đầu vào, tạo nhiệm vụ và vị trí hợp lệ
      context.py          Thời hạn chung và cách so sánh phương án
      engine.py           Điều phối thuật toán, giữ phương án tốt nhất
      cp_sat.py           CP-SAT: tìm lịch đủ, xếp tối đa, sửa cục bộ
      genetic.py          Giải mã phương án và tìm kiếm quần thể GA
      backtracking.py     Quay lui có giới hạn cho bài toán nhỏ
      repair.py           Dời chuỗi block để chèn phần còn thiếu
      rebuild.py          Tận dụng lịch đang lưu và chọn vùng cần sửa
      scoring.py          Công thức chấm điểm dùng chung
      diagnostics.py      Thông tin môi trường bộ xếp
  templates/              HTML/Jinja
  static/                 JavaScript, CSS và tài nguyên giao diện
tests/                    Kiểm thử độc lập với DB vận hành
```

## Luồng xếp lịch

1. Router xác thực quyền truy cập và gọi `services/schedule_generation.py`.
2. Dịch vụ kiểm tra dữ liệu, chọn chế độ và gọi API bộ xếp.
3. `problem.py` tạo một bộ nhiệm vụ và ứng viên dùng chung. Tiết tránh, khóa khối, khóa lớp, khóa toàn trường và biên buổi được áp dụng ở đây.
4. `engine.py` điều phối CP-SAT, GA, sửa chuỗi và quay lui trong cùng một thời hạn. Số tiết còn thiếu được ưu tiên trước điểm mềm.
5. Dịch vụ lưu kết quả tạm, chạy kiểm tra toàn vẹn và chỉ commit khi lịch hợp lệ. Kết quả không hợp lệ bị rollback.

Các thuật toán tìm kiếm nhận `SchedulingProblem` đã chuẩn bị, không tự truy vấn DB. Hàm `ga_schedule()` vẫn được xuất tại các đường dẫn cũ để giữ tương thích.

## Phụ thuộc và vòng đời ứng dụng

- Import rõ từng tên từ mô-đun cung cấp. Router không lấy toàn bộ lớp dịch vụ qua `runtime.py` hoặc `foundation.py`.
- `runtime.py`, `foundation.py` và các facade tương thích dùng export tường minh để phục vụ mã cũ.
- Cấu hình nghiệp vụ và logger không phụ thuộc vào phiên DB.
- Import `app.main` tạo đối tượng FastAPI nhưng không kết nối DB hoặc chạy migration.
- Khi FastAPI bắt đầu phục vụ, lifespan đăng ký các hook lịch, lấy khóa bootstrap PostgreSQL rồi chạy khởi tạo/migration như trước.
- Không chạy migration bằng cách import mô-đun trong công cụ kiểm tra hoặc bài kiểm thử.

## Kiểm thử

Sau khi cài dependencies và kích hoạt môi trường ảo:

```text
python -m unittest discover -s tests -t . -v
python -m compileall -q app tests
```

Các bài kiểm thử tạo DB SQLite trong bộ nhớ. Cấu hình DB trong tiến trình kiểm thử trỏ tới địa chỉ giả và bài kiểm tra import chặn việc kết nối DB. Không cần tài khoản Neon hoặc `.env` thật để chạy kiểm thử.

Phạm vi gồm:

- Tiết tránh giáo viên, khóa khối/lớp/toàn trường và chống trùng lịch.
- Tiết đôi theo block đã lưu, tiết ghim và biên buổi học.
- Phân biệt hết thời gian tìm, không thể xếp đủ và tối ưu cục bộ.
- Xếp từ trống, bổ sung, xếp lại, GA dự phòng và quay lui.
- Kiểm tra toàn vẹn trước commit và rollback kết quả sai.
- Bộ dữ liệu sinh tự động gồm 17 lớp, 35 giáo viên, 272 phân công và 498 tiết.
- Import ứng dụng không truy cập DB; bootstrap chỉ chạy khi bắt đầu phục vụ.

Workflow `.github/workflows/python-tests.yml` chạy các kiểm tra này khi push hoặc mở pull request. Dữ liệu thử được sinh trong mã, không lấy tên giáo viên hoặc lịch vận hành thật.
