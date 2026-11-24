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

Trong **Học liệu liên kết → PhET**, có ba mô phỏng tiếng Việt: định luật Ôm, phân số và trạng thái vật chất. Chọn học liệu để xem mô tả/nguồn, mở xem trước rồi **Lưu slide**. PowerPoint giữ liên kết và ghi nguồn trong Notes; cần Internet để mở PhET. Thao tác chọn, lưu hoặc gỡ liên kết không gọi AI.

Phần Rà soát trước khi dạy nêu các dấu hiệu cần kiểm tra, như tham chiếu sách/số trang chưa được xác minh hoặc ý quá dài. Khi có cảnh báo, cần đọc và xác nhận trước khi xuất PPTX/ghi chú. Đây là kiểm tra biên tập có giới hạn, không phải dịch vụ xác minh toàn bộ kiến thức.

PDF không có bookmark vẫn có thể tìm theo từ khóa bằng Tìm bài trong nội dung PDF. Tìm kiếm chạy trên thiết bị, hiển thị tối đa 40 trang phù hợp; chỉ các trang được chọn và trích mới trở thành đoạn nguồn để gửi AI khi có consent.

## Trạng thái

Đã kiểm thử bằng fixture qua API, PostgreSQL tạm, Chromium headless và tệp PPTX. Provider trong bài kiểm thử headless được thay thế bằng fixture riêng trong tests/studio_preview_server.py.

OpenRouter thật đã tạo được bài Định luật Ôm 15 slide, có rà soát nội dung mẫu. Đã kiểm tra dàn ý 20 đề bài đa môn; xem BENCHMARK.md về hai vòng kiểm tra và giới hạn chấm tự động. Soạn theo nhóm 5 slide và lưu sau mỗi nhóm, hỗ trợ tiếp tục khi gặp lỗi. Nhật ký từng bài ghi bước, model, phiên bản và mã lỗi.

Môi trường Render thử nghiệm đã được tách riêng service/DB; xem DEPLOY_RENDER_FREE.md. Website chính vẫn ở bản cũ. Ngày 23/11/2026 người dùng xác nhận ba tệp native QA chạy đúng trong PowerPoint Desktop; không cung cấp phiên bản Office hoặc ảnh/video. Có thể bật Appear/Fade và chuyển cảnh Fade bằng cờ AI_SLIDES_NATIVE_MOTION_ENABLED tại môi trường đã kiểm thử. Nút tải cho biết rõ có/không hiệu ứng; chế độ giảm chuyển động xuất bản không hiệu ứng. Có nút tải bản cơ bản khi engine native gặp lỗi.

Chưa nghiệm thu chất lượng sư phạm 20 bộ bài hoàn chỉnh hoặc tương thích nhiều phiên bản Office. Việc xác nhận ba tệp không có nghĩa toàn bộ V4 đã hoàn thành.

Đã có 15 bố cục riêng dùng chung scene giữa preview và PPTX, gồm sơ đồ mạch, con lắc, biểu đồ native và bản đồ khái quát. Đã bổ sung chỉnh dàn ý, đổi theme sau khi soạn, tìm nội dung và nhận diện tiêu đề bài/chương PDF không bookmark trên thiết bị. Môn/lớp/tên bài/thời lượng có thể nhận diện từ tiêu đề rõ ràng của đoạn đã chọn; chỉ tự điền ô trống có một gợi ý. Chỗ khác nhau giữa nguồn và thông tin giáo viên, hoặc một số công thức khác nhau, hiện bằng chứng để chọn trước khi gọi AI. Quyết định được lưu/hoàn tác và hết hiệu lực khi nguồn đổi.

Ngày 24/11 đã bổ sung phân tích nguồn bằng AI tùy chọn, lựa chọn mâu thuẫn ngữ nghĩa, cắt bài chung trang, lưu/relink chỉ mục sách, URL học liệu riêng và mở rộng bằng nguồn tham khảo đã chọn. Có OCR tiếng Việt trên thiết bị, nhập chữ/tham khảo màu PPTX, adapter giọng nói tùy browser, hàng đợi tối đa 20 bài/lô và ZIP dạy offline. Xem trang /ai-studio/guide và V4_COMPLETION.md về giới hạn cụ thể.

V4 chưa được nghiệm thu toàn bộ: model thô trong bộ 20 bài có lỗi nội dung, hai ứng viên miễn phí thay thế trả 429, chưa có giáo viên duyệt và visual QA rộng bằng Office. AI_SLIDES_CONTENT_QA_APPROVED mặc định false; UI giữ nhãn thử nghiệm chất lượng. Chặn một số dạng lỗi cụ thể không phải bộ kiểm chứng kiến thức. Xem V4_BENCHMARK_REVIEW.md; các mẫu sửa biên tập không được dùng để nâng kết quả model thô.

Chế độ **Bám nguồn bằng trích đoạn** cho AI chọn đoạn, máy chủ đối chiếu rồi lấy nguyên văn; quiz điền đúng nguyên văn, không tự thêm số liệu/học liệu/sơ đồ kiến thức. Dưới preview có nguồn/trang/trích dẫn. Sửa tay làm mất trạng thái đối chiếu và cần rà soát; undo khôi phục bản cũ. Chế độ **Cân bằng** vẫn dành cho diễn đạt linh hoạt. Đây là đối chiếu văn bản, không kiểm chứng tính đúng hoặc đủ ngữ cảnh của nguồn. Dàn ý strict cũ có nút lập lại để dùng hợp đồng mới, giữ lịch sử hoàn tác.

Luồng một nút đã lên preview ở `f4a30c1`: **Tạo PowerPoint bằng AI** tự đi từ dàn ý sang các nhóm nội dung hợp lệ; **Tạo dàn ý bằng AI** vẫn dừng để chỉnh trước. Cảnh báo/nguồn mâu thuẫn sẽ dừng để rà soát. Lỗi giữ các nhóm đã lưu; bấm tiếp tục chỉ soạn phần còn lại, không tự retry hoặc tự gọi inference khi reload. Giáo viên xem lại rồi chủ động tải tệp. Kiểm thử luồng trên preview có fixture tại ranh giới inference; availability và chất lượng AI thật vẫn cần theo dõi, không coi là đã hết timeout. Xem PROGRESS.md cho bằng chứng/giới hạn.

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
.venv/Scripts/python.exe -B tests/run_studio_offline.py
```

Python Playwright thuộc .venv của dự án. Trình duyệt kiểm thử được cài trong cache chuẩn, chạy headless.
