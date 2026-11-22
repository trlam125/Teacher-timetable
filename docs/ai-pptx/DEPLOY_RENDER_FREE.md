# Triển khai AI Studio trên Render Free

## Môi trường thử nghiệm riêng — 22/11/2026

AI Studio được triển khai tại `https://teacher-timetable-ai-preview-lam.onrender.com`, service `srv-dc1g742fngtc73fiqae0`, gói Free tại Singapore, nhánh `codex/ai-slides-render-free`. Commit ứng dụng được deploy là `e4ff5968cc839bb5dfc5249310d2f853e2ef0f61`. Auto-deploy của preview được tắt để không tự chạy các commit chưa kiểm thử.

DB preview `teacher-timetable-ai-preview-db` là Render Postgres Free riêng, tên database `ai_studio_preview`. Không sao chép dữ liệu thời khóa biểu hoặc người dùng từ website chính. DB này hết hạn ngày 22/12/2026 theo thông tin API Render. Kết nối bên ngoài chỉ mở cho IP của máy kiểm thử tại thời điểm tạo.

Website chính `https://teacher-timetable-lam.onrender.com` đã được đưa về nhánh `main`, commit `a5207d63e4eeda633e6d3bc156c2301f9a673c06`. Các biến AI_SLIDES_* đã được gỡ khỏi service chính. Năm bảng Studio rỗng đã tạo trong lần deploy ban đầu còn trong DB Neon; không có dữ liệu bài giảng thử được ghi vào các bảng đó. Bản sao lưu trước migration nằm trong thư mục local bị Git bỏ qua `tmp/ai-studio-backups`.

Tài khoản quản trị và DB preview dùng thông tin xác thực riêng, được lưu trong `.env.ai-preview` trên máy người triển khai và bị Git bỏ qua. Không lưu mật khẩu hoặc chuỗi kết nối trong tài liệu này. Preview không được cấu hình mail, Google OAuth hay key chatbot của website chính.

Lệnh khởi động preview tạo metadata Studio riêng rồi chạy ứng dụng: `python -m app.services.ai_slides.migrate --apply && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Bước bootstrap hiện hành tạo các bảng ứng dụng và quản trị viên trong DB preview mới. Không thay đổi start command của service chính.

Tách service/DB không tách hạn mức Render của workspace. Các service Free dùng chung số giờ miễn phí, băng thông và pipeline; xem [giới hạn Render Free](https://render.com/docs/free). Key OpenRouter của Studio cũng dùng chung quota của tài khoản OpenRouter. Có thể suspend preview khi không kiểm thử để giảm sử dụng tài nguyên.

Smoke test bằng OpenRouter thật đã tạo được bài 5 slide, hiển thị trong browser và tải PPTX. Đã kiểm tra thêm đăng nhập quản trị, sửa/lưu/hoàn tác, PDF 150 trang, mobile và mô phỏng. Một lượt trước đó gặp timeout provider; lượt thử lại hoàn tất. Chi tiết và giới hạn nằm trong QA.md. Hiệu ứng native vẫn chưa được bật trên UI vì chưa có xác nhận Slide Show bằng PowerPoint Desktop.

## Chuẩn bị

Xác nhận DB production, dung lượng còn lại và backup. Cấu hình local hiện nhận diện Neon. Branch, build/start command và DB thực tế trên Render cần đối chiếu Dashboard trước khi triển khai.

Source xuất PPTX ở web/ai-slides. Bundle đã build được lưu trong app/static/ai-slides/dist và phục vụ bằng Python. Render sử dụng Start Command hiện hành.

## Tạo bảng

Mặc định AI_SLIDES_ENABLED=false. Các bảng Studio dùng metadata riêng. Khởi động Smart TKB không tạo các bảng này.

Sau backup và xác nhận đúng target database, chạy từ môi trường được phép kết nối target.

```powershell
.venv/Scripts/python.exe -B -m app.services.ai_slides.migrate
.venv/Scripts/python.exe -B -m app.services.ai_slides.migrate --apply
```

Lệnh đầu chỉ liệt kê bảng. Lệnh --apply dùng PostgreSQL, khóa migration riêng và CREATE TABLE idempotent cho schema ban đầu.

## Cấu hình

Thiết lập các biến này trong môi trường triển khai.

```dotenv
AI_SLIDES_ENABLED=false
AI_SLIDES_OPENROUTER_API_KEY=
AI_SLIDES_PRIMARY_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
AI_SLIDES_FALLBACK_MODELS=
AI_SLIDES_AI_STEP_TIMEOUT_SECONDS=85
AI_SLIDES_MAX_REQUESTS_PER_USER_DAY=8
AI_SLIDES_MAX_REQUESTS_SERVER_DAY=40
```

Danh sách model được cấu hình bằng ID :free chính xác. Mỗi lượt kiểm tra catalog OpenRouter và mọi trường giá được công bố. Model hỗ trợ structured_outputs dùng JSON schema; model văn bản khác nhận schema trong prompt và vẫn phải qua Pydantic cùng kiểm tra ràng buộc ở server. Khi catalog không kiểm tra được hoặc giá chưa xác định, lượt gọi bị từ chối. Fallback cấu hình chỉ được dùng khi primary không đủ điều kiện trong catalog. Chưa chọn fallback inference đủ chất lượng.

Soạn nội dung theo nhóm tối đa 5 slide, lưu sau mỗi nhóm. Bài 15 slide thường cần 4 lượt (1 dàn ý + 3 nhóm nội dung), bài 30 slide cần 7 lượt. Một bước có deadline tổng 85 giây sau đo thực tế; cần kiểm tra timeout gateway trước khi bật ở môi trường triển khai. Không tự retry sau timeout. Thất bại có thể tiếp tục từ nhóm chưa được lưu.

Mặc định provider data_collection=deny. Với bài được đánh dấu training_consent, request cho phép provider miễn phí có thể dùng nội dung để huấn luyện. Người dùng vẫn cần cấu hình Privacy tương ứng trên tài khoản OpenRouter; hệ thống không tự đổi chính sách tài khoản.

Hạn mức tính theo ngày UTC và tính mọi lượt đã giữ chỗ, gồm lượt lỗi và đề xuất sửa. Tổng site mặc định 40 để chừa ngân sách cho giới hạn account free. Các ứng dụng khác cùng tài khoản OpenRouter có thể dùng chung quota account.

Bật AI_SLIDES_ENABLED=true sau migration, cấu hình key/model, thử bằng tài khoản kiểm thử và xác nhận tải được tệp. Việc bật production cần quyền triển khai và kiểm tra hạ tầng thực.

## Rollback

Đặt AI_SLIDES_ENABLED=false và restart/redeploy service. Cờ này ẩn menu và chặn API Studio. Dữ liệu bài giảng được giữ. Có thể phục hồi bundle từ release trước. Việc xóa bảng cần kế hoạch và backup riêng.

## Tài nguyên và quyền dữ liệu

Giới hạn 100 MB/400 trang PDF và tối đa 50 trang mỗi lượt chọn trên browser. Excerpt gửi AI giới hạn 40.000 ký tự, văn bản được hiển thị để người dùng kiểm tra trước khi consent. File gốc chỉ được cache khi người dùng chọn lưu sách trên thiết bị.

API chỉ trả bài giảng thuộc owner. Admin xem telemetry tổng hợp model/lượt/lỗi, quyền đọc deck vẫn theo owner. Xóa bài xóa revisions và steps của bài. Telemetry giữ ID lượt, token count và mã lỗi, không chứa đoạn nguồn.

Nguồn lớn, nhiều revisions và nhu cầu retention dài hạn cần theo dõi dung lượng DB trong pilot.
