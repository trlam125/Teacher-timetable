# Bảo vệ lưu lượng Smart TKB

Các thay đổi trong repository bảo vệ tài nguyên ứng dụng. Chúng không thay thế
lớp chống DDoS của nhà cung cấp và không tự bật WAF trên tài khoản hosting.

## Triển khai bản sửa

- Cài lại `requirements.txt` trong môi trường Python của **dự án/backend** và
  khởi động lại toàn bộ worker. Không cài Python hoặc dependency backend vào
  container Node.js `codex-skill-env`.
- FastAPI 0.163.1 và Starlette 1.10.0 được ghim cùng nhau. Adapter template giữ
  các lời gọi hiện có tương thích với API request-first của Starlette.
- Windows: dùng `run-production.bat` sau reverse proxy/tunnel; `run-local.bat`
  vẫn chỉ phục vụ phát triển. Không dùng `--reload` cho production.
- Render hoặc hosting tương đương: cấu hình start command với các giới hạn
  Uvicorn giống script; host/port dùng giá trị mà nền tảng yêu cầu.
- Đọc các biến mới trong `.env.example`. Body mặc định 32 MiB cho phép một
  file 15 MiB kèm report JSON, nhưng từng file vẫn chịu giới hạn nghiệp vụ cũ.

## Phạm vi giới hạn

| Kiểm soát | Mặc định | Phạm vi |
|---|---|---|
| HTTP theo IP | 600/phút, burst 120 | Mỗi worker |
| HTTP tổng | 120/giây, burst 240 | Mỗi worker |
| Trang/luồng xác thực theo IP | 60/phút, burst 20 | Mỗi worker, trước DB/CAPTCHA |
| Thời tiết/vị trí theo IP | 30/phút, burst 10 | Mỗi worker |
| HTTP đồng thời | 64 | Mỗi worker |
| Body lớn/không rõ kích thước đồng thời | 4 | Mỗi worker |
| Body | 32 MiB, tối đa 30 giây tiếp nhận | Mỗi yêu cầu |
| Cache thời tiết/vị trí | 256 mục mỗi cache, TTL 10 phút/24 giờ | Mỗi worker |
| Gọi dịch vụ thời tiết/vị trí | Tối đa 4 đồng thời, response 256 KiB | Mỗi worker |
| WebSocket | 128 tổng, 16/IP | Mỗi worker |
| WebSocket theo tài khoản | 8 | Chia sẻ qua PostgreSQL và khóa giao dịch |
| Sự kiện WebSocket | 120/phút, burst 30, theo IP và tài khoản | Mỗi worker |
| Frame WebSocket | 32 KiB | Mỗi frame |

Token bucket có thể cho phép burst; đây không phải cửa sổ cố định. Bộ nhớ lưu
identity có trần 8192 mục; không đẩy bucket đang hoạt động ra để cấp lại lượt.
Giới hạn xác thực trong PostgreSQL vẫn được giữ để chia sẻ giữa các worker.
Lớp chặn bộ nhớ chạy trước để giảm lượng request bị từ chối phải truy vấn DB.
AI không được thêm quota theo tài khoản, ngân sách hoặc số lần gọi.
Body tối đa 64 KiB có Content-Length đi qua ngân sách HTTP chung để upload/AI
chậm không chiếm hết slot dành cho form đăng nhập/chỉnh sửa nhỏ. Body không rõ
kích thước được trả slot upload sau khi đã nhận xong và xác nhận đủ nhỏ.

Khi tăng worker/instance, các ngân sách cục bộ tăng theo số bản sao. Muốn có
trần toàn hệ thống cần thêm giới hạn tại edge/proxy; không coi chúng là quota
phân tán. Kiểm tra mức sử dụng thực tế của trường có nhiều người chung IP trước
khi điều chỉnh ngưỡng; không tắt tất cả giới hạn để xử lý tình huống NAT.

## Proxy, WAF và backend gốc

1. Bật lớp DDoS/WAF của nhà cung cấp trên **hostname backend thực tế**, cả
   WebSocket; chỉ bảo vệ trang Vercel launcher không bao phủ các cuộc gọi tới
   backend Render.
2. Cấu hình rate limit và giới hạn body/header tại edge trước khi forward.
   Body/header ứng dụng giới hạn 32 MiB/16 KiB; hạn chế cả thời gian gửi header
   và body tại proxy. Thử với upload và OAuth hợp lệ trước khi áp dụng rộng.
3. Hạn chế truy cập trực tiếp origin bằng tính năng origin authentication hoặc
   firewall/ACL của nền tảng, nếu có. Kiểm tra cả hostname mặc định của hosting.
4. `FORWARDED_ALLOW_IPS` phải là IP/CIDR của proxy thực sự, đặt ở môi trường
   **tiến trình Uvicorn**. Không dùng `*` khi còn đường truy cập trực tiếp.
   Ứng dụng không tự tin các header `X-Forwarded-For`/`CF-Connecting-IP` do khách
   gửi. Kiểm chứng `request.client.host` qua proxy bằng tài khoản thử, không ghi
   cookie/token vào log.
5. Theo dõi 429/503, CPU/RAM, disk tạm, DB pool và số socket. Các thay đổi WAF,
   DNS, firewall và cấu hình hosting cần thao tác trên tài khoản triển khai;
   chưa được thực hiện chỉ bằng việc sửa repository.

Nguồn chính thức: [DDoS](https://developers.cloudflare.com/ddos-protection/),
[rate limiting](https://developers.cloudflare.com/waf/rate-limiting-rules/),
[Uvicorn settings](https://www.uvicorn.org/settings/).

## Kiểm tra hồi quy

Các test chạy với app ASGI và tài khoản giả, chặn kết nối ngoài; dữ liệu chat
dùng SQLite trong RAM, không truy cập PostgreSQL đang triển khai. Chạy trong
môi trường Python của dự án đã cài `requirements.txt`:

```text
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Đã chạy 26 test thành công trên Windows/Python 3.13 với bộ dependency được
ghim, gồm:

- Body có/không có Content-Length, dọn file multipart bị từ chối, timeout,
  giới hạn đồng thời, giả header proxy, cache và frame WebSocket.
- Khởi tạo app/OpenAPI, render trang xác thực và trang lỗi, upload hợp lệ
  ở parser và upload chưa đăng nhập, cache thời tiết và header Retry-After.
- Gửi/sửa/xóa tin nhắn theo chủ sở hữu và trường học, chặn trả lời tin nhắn
  khác trường, phiên bị thu hồi, đếm giới hạn kết nối qua hai manager và trả
  slot sau khi đóng kết nối. Fixture SQLite không thực thi advisory lock.

GitHub Actions cũng chạy bộ test này. Trước phát hành vẫn cần kiểm thử riêng
với PostgreSQL: admission đồng thời trên nhiều worker phải không vượt 8
socket/tài khoản, và socket rảnh phải ngắt trong tối đa 15 giây sau khi phiên
bị thu hồi. Đây là phần chưa được xác minh bằng fixture SQLite.
Không thử tải hoặc quét chống DDoS trên hệ thống production.
