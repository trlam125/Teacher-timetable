# Smart TKB

Smart TKB là ứng dụng web hỗ trợ nhà trường xây dựng, quản lý và chia sẻ thời khóa biểu. Hệ thống có thể tự động xếp lịch theo dữ liệu và các ràng buộc đã nhập, sau đó cho phép quản trị viên tinh chỉnh trực tiếp bằng thao tác kéo-thả.

## Tính năng chính

- Quản lý môn học, tổ chuyên môn, giáo viên, khối, lớp và phân công giảng dạy.
- Xếp thời khóa biểu tự động, hạn chế trùng giáo viên và trùng lớp.
- Xếp toàn bộ lịch hoặc chỉ bổ sung các tiết còn thiếu.
- Kéo-thả tiết học để điều chỉnh lịch thủ công.
- Ghim và bỏ ghim từng cụm tiết ở vị trí cố định.
- Cấu hình ngày học, số buổi, số tiết mỗi buổi và các buổi không sử dụng.
- Thiết lập tiết tránh cho giáo viên, lớp học và giới hạn số tiết dạy mỗi ngày.
- Xem thời khóa biểu theo lớp hoặc theo giáo viên.
- Cổng riêng cho giáo viên xem lịch, cập nhật tài khoản và gửi nguyện vọng.
- Quản trị viên duyệt, từ chối hoặc áp dụng nguyện vọng của giáo viên.
- Chia sẻ thời khóa biểu bằng liên kết và xuất dữ liệu CSV.
- Nhân bản một bộ thời khóa biểu để sử dụng cho học kỳ tiếp theo.
- Khôi phục mật khẩu bằng liên kết có thời hạn và xác minh “Tôi không phải là robot”.

## Quy trình đăng ký tài khoản

1. Giáo viên đăng ký bằng họ tên, email và mật khẩu.
2. Tài khoản được tạo ở trạng thái `pending`.
3. Quản trị viên mở **Quản lý tài khoản**, chọn hồ sơ giáo viên tương ứng và xác nhận.
4. Tài khoản chuyển thành `teacher` và được truy cập cổng giáo viên.
5. Khi cần, quản trị viên có thể chủ động nâng một tài khoản `teacher` lên `admin` trong trang quản lý tài khoản.

Khi xác nhận, quản trị viên có thể gắn tài khoản với một hồ sơ giáo viên có sẵn chưa có tài khoản, hoặc tạo hồ sơ giáo viên mới từ tên giáo viên mà người đăng ký đã nhập.

## Yêu cầu hệ thống

- Python 3.11 trở lên.
- PostgreSQL đang hoạt động.
- `pip` để cài các thư viện Python.
- Trình duyệt web hiện đại.

## Cài đặt

### 1. Mở thư mục dự án

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

### 5. Tạo file cấu hình `.env`

Tạo file `.env` tại thư mục gốc của dự án:

```env
APP_ENV=production
DATABASE_URL=postgresql+psycopg://postgres:MAT_KHAU_POSTGRES@localhost:5432/teacher_timetable
SECRET_KEY=THAY_BANG_CHUOI_BI_MAT_NGAU_NHIEN
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=mat-khau-manh-it-nhat-8-ky-tu
SESSION_TTL_SECONDS=43200
SEED_DEMO_DATA=false
```

Có thể tạo `SECRET_KEY` bằng lệnh:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

## Cấu hình quên mật khẩu và SMTP

Trong môi trường công khai, chức năng quên mật khẩu chỉ gửi liên kết đặt lại qua SMTP. Liên kết kiểm thử chỉ được hiển thị khi đồng thời thỏa mãn hai điều kiện:

- `APP_ENV=development`.
- Truy cập ứng dụng bằng `localhost` hoặc `127.0.0.1`.

Ví dụ cấu hình SMTP dùng cổng `587` với STARTTLS:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your-account@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-account@example.com
SMTP_SSL=false
SMTP_STARTTLS=true
```

Nếu nhà cung cấp email yêu cầu SSL trực tiếp, có thể dùng:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USER=your-account@example.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=your-account@example.com
SMTP_SSL=true
SMTP_STARTTLS=false
```

`SMTP_USER` là tài khoản dùng để gửi thư. Email nhận là địa chỉ mà người dùng đã đăng ký trong hệ thống.

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

Khi database hoàn toàn trống, ứng dụng tạo quản trị viên đầu tiên từ các biến:

```env
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=mat-khau-manh-it-nhat-8-ky-tu
```

Không còn tài khoản hoặc mật khẩu mặc định được viết cứng trong mã nguồn. Dữ liệu minh họa chỉ được tạo khi chủ động đặt:

```env
SEED_DEMO_DATA=true
```

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
├── tests/                         # Bộ kiểm thử hồi quy, không bắt buộc khi chỉ chạy website
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

## Các bản vá logic và bảo mật đã áp dụng

- Liên kết đặt lại mật khẩu không còn bị lộ trên máy chủ công khai.
- API có phiên hết hạn trả JSON `401` thay vì trả trang đăng nhập HTML.
- Quản trị viên chỉ có thể quản lý tài khoản của chính mình, tài khoản chờ được mời và giáo viên thuộc các project mình sở hữu.
- Liên kết đăng ký giáo viên được giới hạn theo project qua `/register?project=<share_token>`.
- Project mới được tạo trống, không tự thêm giáo viên, lớp, môn hoặc phân công mẫu.
- Trang chia sẻ công khai chỉ nhận dữ liệu cần thiết và không làm lộ ràng buộc nội bộ hoặc share token trong dữ liệu trang.
- Mẫu tiết đơn được áp dụng thành các tiết tách rời, không liền nhau.
- Khi thay đổi số tiết mỗi tuần hoặc mẫu cụm tiết, các tiết không cố định được đưa về khay để xếp lại an toàn.
- Tiết cố định hoạt động theo từng cụm thực tế. Có thể ghim và bỏ ghim nhiều cụm độc lập trong cùng một phân công.
- Dữ liệu cố định từ phiên bản cũ được chuẩn hóa trong quá trình sinh lịch.
- Khi khóa một buổi, hệ thống xóa toàn bộ cụm cố định bị ảnh hưởng thay vì để lại cụm bị thiếu.
- Khi chấp nhận nguyện vọng giáo viên, hệ thống xếp lại các tiết không cố định của giáo viên đó và hoàn tác nếu bất kỳ phân công nào sai mẫu cụm tiết.
- Thuật toán di truyền đã sửa lỗi tăng con trỏ theo kích thước cụm và không còn tính hai tiết ở khác ngày hoặc khác buổi là liền nhau.
- Dữ liệu tạo mới được kiểm tra trường bắt buộc và trả HTTP `400` thay vì gây lỗi `KeyError` nội bộ.
- Thông tin quản trị viên ban đầu được lấy từ `.env`; không còn tài khoản hoặc mật khẩu mặc định trong mã nguồn.
- Phiên đăng nhập hết hạn ở phía máy chủ và bị thu hồi khi người dùng đổi hoặc đặt lại mật khẩu.
- Quyền super admin được lưu bằng cờ ổn định trong database, nên đổi email không làm mất quyền phê duyệt.
- Lịch còn thiếu nhưng đã có các cụm cố định hoàn chỉnh vẫn có thể tiếp tục được xếp mà không phá hoặc từ chối các cụm đó.

## Cấu hình bảo mật sau bản vá

1. Sao chép `.env.example` thành `.env` và thay toàn bộ giá trị `CHANGE_ME`.
2. Đặt `APP_ENV=production` khi chạy qua Cloudflare Tunnel hoặc máy chủ công khai.
3. Không commit hoặc chia sẻ file `.env`.
4. Sử dụng `SECRET_KEY` dài, ngẫu nhiên và riêng cho từng môi trường.
5. Cấu hình SMTP khi triển khai công khai.
6. Sử dụng App Password nếu nhà cung cấp email hỗ trợ.
7. Mật khẩu quản trị viên ban đầu phải có ít nhất 8 ký tự.
8. Chỉ bật `SEED_DEMO_DATA=true` khi thực sự muốn tạo dữ liệu minh họa.
9. Phiên đăng nhập mặc định hết hạn sau 12 giờ và mọi phiên cũ bị vô hiệu khi đổi hoặc đặt lại mật khẩu.

## Kiểm thử logic

Chạy toàn bộ bộ kiểm thử hồi quy:

```bash
python -m unittest discover -s tests -v
```

Bộ kiểm thử hiện tại gồm 16 trường hợp bảo mật và xếp lịch cốt lõi, bao gồm:

- Cố định nhiều cụm tiết.
- Hoàn thiện lịch còn thiếu nhưng đã có cụm cố định.
- Kiểm tra mẫu tiết sau khi áp dụng nguyện vọng.
- Thu hồi phiên sau khi đổi mật khẩu.
- Phân quyền tài khoản giữa các quản trị viên.

Bản vá cũng đã được kiểm tra bằng:

- Biên dịch Python.
- Kiểm tra cú pháp JavaScript.
- Tải toàn bộ template Jinja.
- Kiểm tra các route đăng nhập, API và chia sẻ công khai.
- Kiểm tra ngẫu nhiên trên 15 cấu hình thời khóa biểu.

Các bất biến đã xác nhận:

- Không trùng giáo viên.
- Không trùng lớp.
- Đúng mẫu cụm tiết.
- Không vượt giới hạn tiết mỗi ngày.

## Hạn chế kiến trúc còn lại

- Một tài khoản giáo viên hiện vẫn chỉ liên kết với một dòng `Teacher`. Khi nhân bản project, hệ thống tạo các dòng giáo viên mới; muốn dùng một tài khoản cho nhiều project cần bổ sung mô hình membership riêng.
- Các thao tác chỉnh sửa thời khóa biểu đồng thời hiện được kiểm tra chủ yếu ở tầng ứng dụng. Nếu triển khai nhiều server hoặc có lưu lượng chỉnh sửa lớn, nên bổ sung khóa theo project hoặc giao dịch database ở mức `SERIALIZABLE`.
