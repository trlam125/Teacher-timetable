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

Giới hạn kiểm chứng: agent không điều khiển Desktop. Có thể dùng kết quả kiểm thử thủ công do người dùng báo lại, ghi rõ nguồn bằng chứng và phần chưa được cung cấp.

Rà soát độc lập phát hiện cảnh báo tham chiếu sách chưa quét câu hỏi và phương án quiz. Đã viết subtest tái hiện (4 trường câu hỏi/phương án/hoạt động giáo viên/hoạt động học sinh đều thất bại), rồi mở rộng kiểm tra cho toàn bộ các trường này. Test browser mới đưa tham chiếu trang SGK vào câu hỏi để kiểm tra đường xuất PPTX. Sau sửa, 40 ca backend và cả 22 nhóm headless đạt. Không có finding khác được báo; giới hạn review là source/diff, không xác minh kiến thức AI.

Đã tạo ba bộ QA native motion khác môn bằng browser, kiểm tra XML/timing/targets: Ôm 19 slide, vòng tuần hoàn nước 10 slide, địa lí 10 slide (gồm feedback). File nằm trong `tmp/ai-studio-qa/native-desktop`. Người dùng xác nhận cả ba chạy đúng trên Desktop theo checklist; phiên bản Office/ảnh/video chưa được cung cấp. Đã bổ sung cờ môi trường bật native, default false, để bật riêng preview sau kiểm thử này. Bốn ca browser xác nhận tải native, tải cơ bản, reduced motion và engine-failure fallback đạt; backend tổng 42 ca đạt. Không thay đổi motion engine hoặc bố cục của ba fixture đã xác nhận.

Đã deploy `a923455` lên preview và bật cờ. Smoke từ nút UI trên preview xác nhận native 19 slide / 14 timing / 19 transitions; basic và reduced không có timing/transition. Không gọi AI cho smoke này; dữ liệu thử tạm đã dọn. Còn thiếu các phần V4 khác như nhận diện bài/chương tự động, giải quyết xung đột đa nguồn, mở rộng danh mục tài nguyên và đánh giá chất lượng nhiều bộ bài hoàn chỉnh; không đánh dấu toàn bộ V4 hoàn thành.

## Nhận diện nguồn và lựa chọn thông tin — 23/11/2026

Đã bổ sung đợt tiếp theo của F25/F26/F28/F29:

- Nhận diện từ tiêu đề rõ ràng trong đoạn đã chọn: môn, lớp, tên bài, thời lượng. Trả trích dẫn/tên nguồn/trang PDF; tự điền ô trống có một gợi ý, giữ thông tin đã nhập/khóa. Chế độ tài liệu có thể bắt đầu khi ba ô môn/lớp/tên bài còn trống. Nhận diện cần consent gửi đoạn đã chọn tới server, không gọi AI hoặc dùng quota.
- Tìm tiêu đề bài/chương trong lớp chữ PDF không có bookmark ngay trên thiết bị. Bỏ các mục lục rõ ràng, không suy ra trang PDF từ số trang in; giáo viên kiểm tra gợi ý và khoảng trang trước khi trích. Giới hạn 400 trang, tối đa 200 gợi ý. Không phải OCR hay tách bài hoàn hảo, nhất là bài chung trang.
- Cảnh báo các metadata khác nhau và một số biểu thức ký hiệu khác nhau. Hiển thị bằng chứng cho từng phương án; giáo viên chọn thông tin ưu tiên, không coi đây là xác minh kiến thức. Chặn plan/author/propose trước khi giữ quota nếu còn điểm chưa chọn. Giá trị trên biểu mẫu luôn được giữ; muốn đổi metadata phải sửa biểu mẫu.
- Quyết định lưu trong profile JSON và revision hiện có, kiểm tra lại bằng dấu vết nội dung/metadata; nguồn đổi thì quyết định cũ hết hiệu lực. Chọn lại sau khi có dàn ý/nội dung cần xác nhận soạn lại và giữ lịch sử hoàn tác. Không thêm bảng/cột hoặc chạy migration DB cho đợt này.
- Đã sửa lỗi đóng PDF khi đổi PDF sang Word/TXT được browser test mới phát hiện. Không đổi bộ máy native motion đã được người dùng xác nhận.

Kiểm thử local: 56 ca backend SQLite/PostgreSQL; 8 ca Node (6 exporter + 2 tiêu đề); 14 + 8 + 4 nhóm browser hồi quy; 7 nhóm nguồn mới. Đã xem ảnh rà soát nguồn trên mobile. Đã tái hiện lỗi thiếu API trước triển khai và các lỗi selector/đổi PDF bằng headless, sửa rồi chạy lại đạt.

Giới hạn còn lại: nhận diện nội dung mơ hồ/mục tiêu bằng AI nhỏ, phân tích mâu thuẫn ngữ nghĩa, tách chính xác nhiều bài cùng trang và kiểm tra tri thức không nằm trong thuật toán này. V4 còn các yêu cầu khác (luồng tự động liền mạch, danh mục học liệu phong phú hơn, đánh giá nhiều bộ bài hoàn chỉnh); chưa đánh dấu hoàn thành toàn plan.

CI đúng commit `7fc95c4` đạt, đã deploy lên preview riêng (`dep-dc1r1tcs728c73d6sbc0`, live). Smoke nguồn tổng hợp trên preview xác nhận nhận diện/bằng chứng, chặn plan trước provider, lưu lựa chọn và hiển thị lại trong giao diện. Provider thật tạo dàn ý 8,45 giây; sau khi agent đọc cảnh báo/dàn ý cho mục đích kiểm thử phần mềm, đã soạn 5 slide trong 43,26 giây và tải PPTX qua nút UI. Cả 5 slide có timing/transition, toàn bộ XML parse được. Tài khoản/bài/steps/revisions/usage thử được dọn; lượt AI vẫn tính quota site.

Đầu ra vẫn có ý ngoài nguồn ở chế độ strict: dụng cụ đo, ví dụ linh kiện ngoài phạm vi và bài tập SGK không có nguồn cụ thể. Phép thử này đạt về phần mềm/lựa chọn công thức ưu tiên, **chưa đạt nghiệm thu bám sát nguồn hoặc sư phạm**. Không dùng bộ bài smoke như bài đã được duyệt để dạy. Đây là việc cần giải quyết ở đợt chất lượng tiếp theo, không coi source review là bộ kiểm chứng kiến thức.

Website chính giữ commit `a5207d6` và deploy ID cũ; kiểm tra HTTP /login=200, /ai-studio=404. Không thay env hay DB của website chính. Server fixture và cụm PostgreSQL kiểm thử local đã dừng; không điều khiển Desktop.
