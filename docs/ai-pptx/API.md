# API AI Studio

Đối chiếu `app/routers/ai_slides.py` và `app/services/ai_slides/schemas.py`, ngày 24/11/2026. API dùng phiên đăng nhập của website. Teacher, admin và super_admin dùng Studio khi feature flag bật; các bài/revision/step chỉ truy cập theo owner. Admin không vì có quyền tổng hợp mà được đọc nội dung bài của owner khác.

Các yêu cầu ghi cần CSRF token theo ứng dụng. Với bài đã lưu, gửi `If-Match: <version>`; thiếu phiên bản trả 428, xung đột trả 409. Các bước AI cần `Idempotency-Key` dài 8–128 ký tự; dùng lại cùng key để đọc kết quả bước cũ, không tạo lượt suy luận mới. Không tự retry inference sau timeout/429.

| Phương thức / đường dẫn | Công dụng |
|---|---|
| GET `/api/ai-slides/capabilities` | Khả năng/cờ tính năng và trạng thái thử nghiệm |
| GET `/api/ai-slides/resources` | Kho học liệu có giới hạn và credit |
| POST `/api/ai-slides/analyze-sources` | Phân tích quy tắc nguồn; không phải bước inspect bằng AI |
| GET / POST `/api/ai-slides/decks` | Danh sách owner / tạo bài từ Profile |
| GET / DELETE `/api/ai-slides/decks/{id}` | Đọc / xóa bài thuộc owner |
| PATCH `/api/ai-slides/decks/{id}/input-profile` | Sửa Profile, kiểm tra field khóa và thay đổi nguồn |
| PATCH `/api/ai-slides/decks/{id}/source-review` | Lưu lựa chọn giải quyết nguồn mâu thuẫn |
| POST `/api/ai-slides/decks/{id}/inspect-sources` | Gợi ý metadata/xung đột bằng AI; có quota và chứng cứ quote |
| POST `/api/ai-slides/decks/{id}/plan` | Tạo dàn ý; không nhận đã có nội dung hoàn chỉnh |
| PATCH `/api/ai-slides/decks/{id}/outline` | Sửa dàn ý; `discard_content` cho phép chủ động bỏ nội dung cũ |
| POST `/api/ai-slides/decks/{id}/approve-outline` | Xác nhận dàn ý hiện tại trước khi author |
| POST `/api/ai-slides/decks/{id}/author` | Soạn nhóm tiếp theo, tối đa 5 slide |
| POST `/api/ai-slides/decks/{id}/slides/{slide}/propose` | Đề xuất sửa một slide từ `instruction`; chưa tự áp dụng |
| PATCH `/api/ai-slides/decks/{id}/slides/{slide}` | Lưu `slide`, có thể kèm `proposal_step_id` để xác minh đề xuất |
| PATCH `/api/ai-slides/decks/{id}/presentation` | Theme/motion; không gọi AI |
| GET `/api/ai-slides/decks/{id}/revisions` | Lịch sử snapshot |
| POST `/api/ai-slides/decks/{id}/restore` | Khôi phục snapshot bằng `version` |
| GET `/api/ai-slides/decks/{id}/steps` | Trạng thái bước/lỗi đã lưu |
| GET `/api/ai-slides/admin/usage` | Admin: tối đa 100 usage gần nhất, không có nội dung nguồn |
| GET `/api/ai-slides/admin/summary` | Admin: số bài/bước/lỗi, quota ngày UTC, token theo model/status |

Profile, Blueprint, Manifest, SourceReview và các payload được định nghĩa bằng Pydantic trong `schemas.py`; dùng mã hiện hành làm hợp đồng chi tiết. Phản hồi bài có `id`, `version`, `status`, `busy`, `profile`, `blueprint`, `manifest`, `review`, `source_analysis`, `grounding_report`. Trạng thái `ready` mô tả tiến độ lưu, không phải chứng nhận kiến thức.

Lỗi Studio có dạng `{"code":"…","message":"…","step_id":null,"provider_status":null}`. Lỗi auth/validation HTTP của FastAPI có thể dùng `detail`. `AI_ARITHMETIC_ERROR` và `AI_QUIZ_ERROR` chỉ chặn các lỗi số học/đáp án rõ ràng trong phạm vi kiểm tra; không xác minh toàn bộ tri thức. Quota/provider có thể trả 429 hoặc timeout; phần đã lưu được giữ, lease được giải phóng theo luồng lỗi.

Không có API backend nhận file PPTX để render. Parse tài liệu, OCR, ảnh xem trước, xuất PPTX/ZIP chạy trong browser. Thư viện sách và hàng đợi lô dùng bộ nhớ thiết bị; dữ liệu bài đã lưu nằm trong DB Studio. [Triển khai/rollback](DEPLOY_RENDER_FREE.md), [hướng dẫn](README.md).
