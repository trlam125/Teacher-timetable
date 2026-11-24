# Duyệt nội dung và ghi bằng chứng V4

Người dùng đã giao Codex tự rà soát thay vì tiếp tục chờ chấm 20 bộ. Lượt đó đã xong, xem [báo cáo AI/nguồn](V4_EDITORIAL_AUDIT.md) và gói `V4-20-bai-mau-da-ra-soat.zip`. Phiếu người duyệt dưới đây được giữ cho việc ghi nhận chuyên môn/Office khi có, không phải việc người dùng bắt buộc phải làm để hoàn thành lượt rà soát AI. Không điền tên giáo viên hoặc tự đánh dấu qualified_reviewer thay người dùng.

Mở `tmp/ai-studio-qa/v4-review-desk/index.html` trên Chrome/Edge. Trang chạy từ tệp, không gửi nội dung hoặc kết quả ra mạng. Có 20 bài, mỗi bài hai phiên bản riêng: AI gốc và bản Codex đã biên tập. Chọn bài ở thanh bên; xem đủ ảnh HTML, nội dung, nguồn và Notes trên một trang. Nút đầu bài trỏ đúng tệp PowerPoint trong gói.

## Chấm nội dung

Sáu mục theo plan: kiến thức 30, phạm vi/chứng cứ 20, sư phạm 20, tiếng Việt 10, học liệu 10, cấu trúc 10. Mục chưa chấm để trống. Phần mềm kiểm tra cấu trúc và ghi cảnh báo kỹ thuật riêng, không tự cho điểm kiến thức. Không tự đặt ngưỡng 85/90 thay cho quyết định của người duyệt vì plan chưa chốt ngưỡng tổng.

Ba lỗi loại trực tiếp — bịa nguồn/trang SGK, thay thông tin khóa, sai công thức trọng tâm — cần chọn rõ đã kiểm tra hay có lỗi. Tổng điểm cao không xóa hard fail. Đọc xong nội dung/Notes/nguồn, ghi nhận xét, chọn kết luận cho đúng phiên bản. Ghi tên và tư cách người duyệt; thông tin này là người ghi tự xác nhận, không được coi là danh tính hay chuyên môn đã được máy xác thực.

Bản biên tập đạt không nâng điểm của model AI gốc. Khi chưa có đủ 20 phiếu AI gốc hợp lệ, CLI vẫn báo model_content_review_complete=false. Bản raw hiện có lỗi đã ghi trong V4_BENCHMARK_REVIEW.md; không cần thử chấm đạt cho mọi bài.

## PowerPoint Desktop

Các ảnh trong trang là HTML preview, không phải Office render. Checklist Desktop chỉ đánh dấu sau khi mở đúng tệp, dùng Slide Show và kiểm tra hiệu ứng, chuyển cảnh, liên kết/quiz nếu có, Notes và khả năng sửa. Ghi phiên bản Office thực đã dùng. Có thể lưu phần kiểm tra bổ sung này cho cả 20 bài; không bắt buộc kiểm tra lại tất cả 20 chỉ để lặp gate motion ba bộ mẫu của plan.

Gate motion gốc yêu cầu ba bộ, mỗi bộ ít nhất hai slide có hiệu ứng theo đối tượng và Fade. Người dùng đã xác nhận ba bộ native-desktop chạy đúng ngày 23/11; phiên bản Office và ảnh/video chưa được cung cấp. Không điều khiển Desktop hoặc thay kết quả đó bằng Chromium. Trường edited_desktop_review_complete chỉ mô tả độ phủ bổ sung trên 20 bản biên tập, không tự quyết định toàn V4.

## Lưu, khôi phục và kiểm tra báo cáo

Điểm/nhận xét lưu trong localStorage theo mã bộ tệp. Bấm Lưu kết quả JSON để sao lưu, dùng Mở kết quả đã lưu khi cần chuyển máy. Tệp khác mã bộ bài bị từ chối và không ghi đè tiến độ đang nhập. Để kiểm tra JSON sau khi người duyệt xuất:

```powershell
.venv/Scripts/python.exe tools/review_ai_slides_v4.py --report DUONG_DAN_JSON
```

Lệnh kiểm tra mã SHA-256 thực tế của PowerPoint, JSON và từng ảnh; schema phiếu, thang điểm, hard fail và việc tách AI gốc/bản sửa. Tệp thay đổi sau khi duyệt sẽ bị từ chối. Báo cáo rỗng, tên rỗng, điểm thiếu hoặc hard fail chưa rà soát không được tính là đã đạt. Công cụ không tự bật AI_SLIDES_CONTENT_QA_APPROVED hay deploy production.

Để dựng lại bộ duyệt khi đã có đủ đầu ra benchmark và ảnh slide:

```powershell
.venv/Scripts/python.exe tools/review_ai_slides_v4.py
```

Các bộ bài được tổng hợp cho QA, không phải SGK chính thức hoặc bằng chứng phù hợp chương trình. Bộ duyệt không thay giáo viên kiểm tra kiến thức, ngữ cảnh và tính phù hợp lớp.
