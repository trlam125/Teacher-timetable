# Tiếp tục V4 — 23/11/2026

Nhánh: `codex/ai-slides-render-free`. Website chính giữ `main`; chỉ deploy service preview riêng. Không dùng desktop automation. Node chạy trong `codex-skill-env`, Python trong `.venv`.

Đợt tiếp theo theo F16/F26/F29/F32 và phần QA của plan V4:

1. Sửa dàn ý: tiêu đề, mục tiêu, thứ tự, loại slide, thời lượng và nguồn. Giữ ràng buộc tổng bài, version/owner; khi đã có nội dung phải xác nhận soạn lại. Có thể hoàn tác.
2. Đổi theme/mức hiệu ứng riêng, giữ nguyên manifest và dàn ý, không gọi AI. Native motion vẫn khóa theo gate Desktop hiện hành.
3. Sửa quiz/biểu đồ/học liệu bằng tay; cảnh báo tham chiếu trang sách chưa xác minh, số liệu minh họa và nội dung quá dài. Không coi cảnh báo heuristic là kiểm chứng kiến thức.
4. Tìm nội dung trong PDF ngay trên thiết bị, gồm tệp không có bookmark. Không gửi các trang chưa chọn tới server.
5. Kiểm thử API SQLite/PostgreSQL, exporter và browser headless; deploy và smoke trên preview riêng; đối chiếu website chính vẫn ở bản cũ.

Trạng thái: API/UX hoàn tất; 40 ca backend SQLite/PostgreSQL, 6 ca exporter Node, 14 nhóm browser hồi quy và 8 nhóm editor/search headless đều đạt. Đã xem ảnh dàn ý và rà soát độc lập delta. Đã deploy `5ac5b23` lên preview riêng; smoke provider thật và editor trên preview đạt, có PPTX tải xuống. Không thay đổi metadata DB; không cần migration mới. Website chính giữ main/bản cũ.

Đã quan sát kiểm thử mới thất bại khi chưa có endpoint/editor, sau đó đạt sau khi bổ sung. Một thao tác test ban đầu chọn theme khi phần thiết lập còn thu gọn; đã sửa script mở phần thiết lập trước khi chọn, không đổi hành vi sản phẩm để che lỗi test.

Quyết định: chỉnh dàn ý đã có nội dung yêu cầu `discard_content=true` rõ ràng, đồng thời giữ revision để hoàn tác. Không tự xóa slide đã soạn chỉ vì thay đổi theme.

Giới hạn giữ nguyên: chưa thể nghiệm thu native motion trong PowerPoint Desktop khi không được điều khiển desktop; không tự bật gate này.

Rà soát độc lập phát hiện cảnh báo tham chiếu sách chưa quét câu hỏi và phương án quiz. Đã viết subtest tái hiện (4 trường câu hỏi/phương án/hoạt động giáo viên/hoạt động học sinh đều thất bại), rồi mở rộng kiểm tra cho toàn bộ các trường này. Test browser mới đưa tham chiếu trang SGK vào câu hỏi để kiểm tra đường xuất PPTX. Sau sửa, 40 ca backend và cả 22 nhóm headless đạt. Không có finding khác được báo; giới hạn review là source/diff, không xác minh kiến thức AI.

Đã tạo ba bộ QA native motion khác môn bằng browser, kiểm tra XML/timing/targets: Ôm 19 slide, vòng tuần hoàn nước 10 slide, địa lí 10 slide (gồm feedback). File nằm trong `tmp/ai-studio-qa/native-desktop`; đã gửi yêu cầu người dùng kiểm tra thủ công PowerPoint Desktop. Chưa nhận kết quả nên gate trên UI vẫn tắt.
