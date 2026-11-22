# Kết quả kiểm thử AI Studio

Ngày 22/11/2026. Nhánh codex/ai-slides-render-free từ a5207d6.

## Phương pháp

Kiểm thử API qua FastAPI TestClient, PostgreSQL tạm trên loopback, Node.js trong codex-skill-env và Chromium headless từ .venv của dự án. Từ khi người dùng yêu cầu ngừng điều khiển máy, mọi kiểm tra tiếp theo dùng dòng lệnh và tệp đầu ra.

## Đã đạt

Đợt kiểm tra cuối gồm 32 ca backend trên SQLite/PostgreSQL, 6 ca exporter Node và 14 nhóm kiểm tra qua Chromium headless. Các ca đều đạt. Provider headless dùng fixture, tệp PPTX tải xuống được tạo thực trong browser.

- Quyền teacher/admin/super_admin, feature flag và CSRF.
- Cách ly bài giảng theo owner, gồm đọc, sửa, lịch sử và xóa.
- Kiểm tra consent trước cloud call và lưu nguồn.
- Plan/author lưu kết quả, replay yêu cầu hoàn thành không gọi provider lần nữa.
- Author nhóm 5 slide, lưu 3 nhóm cho bài 15 slide; lỗi nhóm sau giữ phần trước và tiếp tục đúng vị trí.
- Nhật ký theo owner có model, loại bước, phiên bản, mã lượt và lỗi. Lỗi schema ghi đường dẫn trường, không ghi nội dung nguồn hoặc API key.
- Timeout giữ dàn ý và giải phóng lease, lượt lỗi tính quota.
- Khóa phiên bản, yêu cầu đồng thời và kết quả về muộn.
- Schema structured output, kiểm tra model miễn phí, nguồn hợp lệ và mục tiêu giáo viên khóa.
- Headless tạo bài, reload, xuất PPTX, sửa, undo, scoped AI proposal và duyệt thay đổi.
- PDF 150 trang có bookmark, chọn trang 35–36 và trích đúng hai trang.
- DOCX có đoạn và bảng, TXT UTF-8, cảnh báo PDF scan.
- IndexedDB giữ sách sau reload, màn hình 390 px không tràn ngang.
- Công thức Ôm, chu kỳ góc nhỏ và chọn vùng trên bản đồ khái quát.
- PPTX giữ chữ Việt, notes, hyperlink, đối tượng chỉnh sửa được và timing/transition qua round-trip.

Báo cáo chi tiết chạy headless và ảnh do trình duyệt headless tạo nằm ở tmp/ai-studio-qa. Tệp browser-export.pptx được tạo bằng exporter trong browser.

## Giới hạn đã xác định

Provider của bộ E2E dùng fixture riêng cho test. OpenRouter thật đã được kiểm tra với key riêng và model miễn phí. Xem BENCHMARK.md: vòng đầu đạt 8/20 dàn ý, sau siết hợp đồng đầu ra kiểm tra lại 12 lỗi đạt 12/12. Chưa có điểm chất lượng sư phạm 20 bài hoàn chỉnh.

Bài Định luật Ôm 15 slide được soạn bằng API thật, có rà soát/sửa nội dung mẫu được ghi lại riêng. Các nhóm 5 slide mất khoảng 41–80 giây, timeout tổng 85 giây. Tệp live-ohm-basic.pptx có 19 slide gồm 4 trang phản hồi. Hai bản QA gentle/minimal có 14 timing trees và 19 transitions; không đồng nghĩa đã xác nhận playback.

Đã xác nhận website chính trên Render dùng Neon. Lần triển khai ban đầu đã sao lưu DB, tạo 5 bảng Studio riêng, rồi deploy `e4ff596`. Theo yêu cầu tách kiểm thử, service chính đã được đưa về nhánh main và commit `a5207d6`; các biến AI_SLIDES_* đã gỡ. Năm bảng Studio trên Neon đều có 0 dòng khi kiểm tra trước khi tạo môi trường preview riêng. Không có bài giảng thử được lưu vào DB chính.

PowerPoint Desktop Slide Show chưa được kiểm tra. Native motion vẫn bị khóa ở capabilities.

Đã có 15 bố cục riêng dùng cùng scene cho preview/PPTX, với sơ đồ chỉnh sửa được, biểu đồ native và SVG bản đồ. Ảnh headless cho bài thật đã được xem và sửa tương phản mạch điện trên cover. Chưa render trực tiếp bằng PowerPoint hoặc LibreOffice. Bản đồ dùng đường bao đất liền Natural Earth, không biểu diễn địa giới hành chính hoặc phạm vi biển đảo đầy đủ.

## Kiểm thử preview Render riêng

Service `teacher-timetable-ai-preview-lam.onrender.com` chạy commit ứng dụng `e4ff596`, gói Free, với DB Render Postgres `ai_studio_preview` riêng. Không sao chép dữ liệu người dùng hoặc thời khóa biểu từ website chính; không cấu hình mail hoặc key chatbot cũ cho preview. Tài khoản quản trị preview dùng thông tin xác thực riêng trong `.env.ai-preview` bị Git bỏ qua.

Đã kiểm tra thực tế trên preview:

- Đăng nhập bằng tài khoản giáo viên tạm; capabilities nhận đúng cấu hình AI; API từ chối thiếu đăng nhập và CSRF.
- OpenRouter thật tạo dàn ý 5 slide trong 12,20 giây và soạn nội dung trong 48,13 giây ở lượt thành công. Lượt trước đó gặp AI_TIMEOUT ở giới hạn 85 giây; có log model, mã lỗi và mã lượt. Không tự retry vô hạn.
- Browser headless mở bài đã lưu, xem nhật ký model và tải PPTX thực tế. Không có lỗi JavaScript chưa xử lý. Tài khoản/dữ liệu smoke tạm đã được xóa sau kiểm thử.
- Ba kiểm tra tệp tải xuống đạt: tiêu đề slide đầu đúng manifest, metadata giữ tên bài, các XML hợp lệ và notes được giữ. Script smoke ban đầu nhầm slide đầu luôn là cover; đã sửa giả định và kiểm tra lại chính tệp tải xuống, không gọi AI lại để sửa test này.
- Tài khoản quản trị preview đăng nhập đúng; sửa slide, reload và hoàn tác qua API thật; tải được bài mẫu đã rà soát.
- Browser trên preview đọc PDF mẫu 150 trang, chọn bookmark và chỉ trích trang 35–36; màn hình 390 px không tràn ngang; mô phỏng Ôm đổi U cập nhật đúng I.

Bài mẫu lưu cho quản trị preview đã rà soát thủ công: bỏ tham chiếu trang SGK không có nguồn, làm rõ sự phụ thuộc R theo nhiệt độ và quan hệ nghịch biến I–R. Bản AI thô còn trong artifact local để đối chiếu. Kết quả này xác nhận luồng phần mềm, không chứng minh mọi nội dung AI tạo đều đúng kiến thức. Giáo viên vẫn cần rà soát bài giảng.

Báo cáo và artifact nằm trong `tmp/ai-studio-qa`: `preview-smoke-report.json`, `preview-smoke-timeout-report.json`, `preview-admin-browser-report.json`, `preview-smoke-export.pptx` và `preview-reviewed-export.pptx`. Thông tin triển khai và thời hạn DB xem DEPLOY_RENDER_FREE.md.
