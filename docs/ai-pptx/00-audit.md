# Dữ kiện triển khai V4

Ghi nhận ngày 24/11/2026; trạng thái triển khai dưới đây là lần xác minh Render API gần nhất đã ghi trong [V4_COMPLETION.md](V4_COMPLETION.md), không phải một đợt deploy mới của lượt biên tập mẫu.

| Thành phần | Dữ kiện |
|---|---|
| Repo | FastAPI/Jinja2, SQLAlchemy, static browser bundle; nhánh `codex/ai-slides-render-free` |
| Mốc bắt đầu | `a5207d63e4eeda633e6d3bc156c2301f9a673c06` |
| Preview | `https://teacher-timetable-ai-preview-lam.onrender.com`, service `srv-dc1g742fngtc73fiqae0`, autoDeploy tắt |
| Mã ứng dụng preview | `3ee49e904a878a897ffee6ea087b0908e91a2cb3`, deploy `dep-dc2pvlek1f9s738p157g` |
| Website chính | Lần xác minh gần nhất giữ commit `a5207d63e4eeda633e6d3bc156c2301f9a673c06`; không cập nhật website/DB/env chính trong lượt này |
| DB preview | Render PostgreSQL `ai_studio_preview`, hạn hiện được ghi nhận 22/12/2026; chưa phải lưu trữ production bền vững |
| DB trong `.env` chính | Trỏ Neon; không dùng để chạy fixture hoặc tự migrate Studio |
| DB kiểm thử | Fixture SQLite trong bộ nhớ; PostgreSQL QA riêng cổng 18765 khi cần integration |
| Provider | OpenRouter riêng cho Studio, kiểm tra ID/giá bằng 0 tại runtime; không gọi chatbot/key cũ |
| Xuất slide | Browser PptxGenJS/OOXML; Render không chạy Node PPTX worker, LibreOffice hay mô hình AI local |
| Runtime dev Windows | Python `.venv`; Node build/test qua container `codex-skill-env` hiện có, không cài Node trên host |

Studio dùng metadata/bảng riêng, migrations chủ động sau backup. Không tự tạo bảng lúc startup. Xem [triển khai](DEPLOY_RENDER_FREE.md) để biết cấu hình và rollback bằng feature flag.

Đợt mã ứng dụng gần nhất đạt CI 116 backend/tooling, 20 Node và 80 nhóm headless. Đợt biên tập mẫu tiếp theo chỉ sửa tooling/docs/QA, không thay API, schema DB hoặc cấu hình preview. Kết quả mới ghi riêng ở [QA](QA.md) và [rà soát nội dung](V4_EDITORIAL_AUDIT.md); không cộng lượt chạy lặp thành số ca mới.

Phạm vi còn mở: chất lượng/availability model free, bằng chứng Office rộng hơn và lưu trữ production sau hạn DB preview. Ba bộ motion đã được người dùng báo chạy đúng trong PowerPoint; không có phiên bản Office hoặc video/screenshot để tự nhận bộ bằng chứng đầy đủ theo plan.
