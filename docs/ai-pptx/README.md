# AI Studio

Bản triển khai đầu cho giáo viên, Admin và Super Admin. Bật tính năng sau khi tạo bảng bằng lệnh riêng và cấu hình OpenRouter.

## Sử dụng

Vào AI Studio từ menu tài khoản. Cổng giáo viên có thêm nút Tạo bài giảng AI.

1. Chọn Nhập thủ công, Từ tài liệu hoặc Kết hợp.
2. Điền môn, lớp, tên bài, thời lượng và số slide. Khi chọn sách PDF, chọn bài từ bookmark hoặc nhập khoảng trang PDF.
3. Xem lại từng đoạn nguồn. Có thể sửa văn bản trích xuất và bỏ thông tin cá nhân trước khi đồng ý gửi tới OpenRouter.
4. Tạo dàn ý. Nếu có cảnh báo, kiểm tra và xác nhận trước khi soạn slide.
   Chọn Chỉnh dàn ý để sửa mục tiêu, tiêu đề, loại slide, thứ tự, thời lượng và nguồn. Chỉnh dàn ý của bài đã có nội dung cần xác nhận soạn lại; bản cũ vẫn có trong Hoàn tác.
5. Sửa nội dung slide, ghi chú hoặc yêu cầu AI đề xuất thay đổi. Xem thay đổi trước khi áp dụng.
6. Tải PowerPoint, ghi chú hoặc JSON sao lưu. Mỗi lần xuất PPTX chạy trên thiết bị.

Hoàn tác lấy dữ liệu từ lịch sử đã lưu trên tài khoản. Đổi nguồn tạo bản nháp mới, phiên bản cũ còn trong lịch sử. Sách được lưu trong IndexedDB chỉ có trên thiết bị đã chọn lưu.

Trong bài đã soạn, mở Giao diện và hiệu ứng của bài để đổi theme/mức hiệu ứng mà không gọi AI hoặc xóa nội dung. Quiz có trường câu hỏi, phương án, đáp án và giải thích; biểu đồ có dữ liệu số, kiểu cột/đường và nhãn số liệu minh họa. Các học liệu chỉ chọn từ danh mục cho phép.

Phần Rà soát trước khi dạy nêu các dấu hiệu cần kiểm tra, như tham chiếu sách/số trang chưa được xác minh hoặc ý quá dài. Khi có cảnh báo, cần đọc và xác nhận trước khi xuất PPTX/ghi chú. Đây là kiểm tra biên tập có giới hạn, không phải dịch vụ xác minh toàn bộ kiến thức.

PDF không có bookmark vẫn có thể tìm theo từ khóa bằng Tìm bài trong nội dung PDF. Tìm kiếm chạy trên thiết bị, hiển thị tối đa 40 trang phù hợp; chỉ các trang được chọn và trích mới trở thành đoạn nguồn để gửi AI khi có consent.

## Trạng thái

Đã kiểm thử bằng fixture qua API, PostgreSQL tạm, Chromium headless và tệp PPTX. Provider trong bài kiểm thử headless được thay thế bằng fixture riêng trong tests/studio_preview_server.py.

OpenRouter thật đã tạo được bài Định luật Ôm 15 slide, có rà soát nội dung mẫu. Đã kiểm tra dàn ý 20 đề bài đa môn; xem BENCHMARK.md về hai vòng kiểm tra và giới hạn chấm tự động. Soạn theo nhóm 5 slide và lưu sau mỗi nhóm, hỗ trợ tiếp tục khi gặp lỗi. Nhật ký từng bài ghi bước, model, phiên bản và mã lỗi.

Môi trường Render thử nghiệm đã được tách riêng service/DB; xem DEPLOY_RENDER_FREE.md. Website chính vẫn ở bản cũ. Ngày 23/11/2026 người dùng xác nhận ba tệp native QA chạy đúng trong PowerPoint Desktop; không cung cấp phiên bản Office hoặc ảnh/video. Có thể bật Appear/Fade và chuyển cảnh Fade bằng cờ AI_SLIDES_NATIVE_MOTION_ENABLED tại môi trường đã kiểm thử. Nút tải cho biết rõ có/không hiệu ứng; chế độ giảm chuyển động xuất bản không hiệu ứng. Có nút tải bản cơ bản khi engine native gặp lỗi.

Chưa nghiệm thu chất lượng sư phạm 20 bộ bài hoàn chỉnh hoặc tương thích nhiều phiên bản Office. Việc xác nhận ba tệp không có nghĩa toàn bộ V4 đã hoàn thành.

Đã có 15 bố cục riêng dùng chung scene giữa preview và PPTX, gồm sơ đồ mạch, con lắc, biểu đồ native và bản đồ khái quát. Đã bổ sung chỉnh dàn ý trực tiếp, đổi theme sau khi soạn và tìm nội dung PDF. Các mở rộng V4 còn cần hoàn thiện gồm tự nhận diện bài/chương ngoài bookmark, trình giải quyết xung đột đa nguồn và QA thị giác PowerPoint. OCR, nhập PPTX cũ, giọng nói và batch toàn sách thuộc P2.

## Kiểm thử

Python dùng .venv hiện có. Bộ unittest dùng SQLite trong bộ nhớ. Khi có AUTH_TEST_DATABASE_URL trỏ DB kiểm thử riêng, cùng bộ API chạy thêm trên PostgreSQL, gồm kiểm thử tranh chấp khóa giữa hai yêu cầu.

Windows build và test JavaScript bằng container codex-skill-env hiện có.

```powershell
.venv/Scripts/python.exe -B -m unittest discover -s tests -v
./web/ai-slides/scripts/build-windows.ps1 -Test
```

Kiểm thử trình duyệt chạy headless, sử dụng server fixture chỉ bind 127.0.0.1:8766.

```powershell
# Terminal test thứ nhất
.venv/Scripts/python.exe -B tests/studio_preview_server.py
# Terminal test thứ hai
.venv/Scripts/python.exe -B tests/studio_headless.py
.venv/Scripts/python.exe -B tests/studio_editor_headless.py
```

Python Playwright thuộc .venv của dự án. Trình duyệt kiểm thử được cài trong cache chuẩn, chạy headless.
