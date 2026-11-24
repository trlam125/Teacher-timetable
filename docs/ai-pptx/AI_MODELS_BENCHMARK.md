# Quyết định model và benchmark V4

Đối chiếu ngày 24/11/2026. Model pilot đang cấu hình là `nvidia/nemotron-3-ultra-550b-a55b:free`; chưa phê duyệt chất lượng nội dung tự động. ID/giá được xác minh trước inference, không dùng random router hoặc fallback trả phí.

Kết quả dàn ý ban đầu, các ứng viên và độ trễ: [BENCHMARK.md](BENCHMARK.md). Benchmark 20 dàn ý + 20 bài nhỏ hoàn chỉnh và các lỗi thực tế: [V4_BENCHMARK_REVIEW.md](V4_BENCHMARK_REVIEW.md). Đây là hai giai đoạn khác nhau, không gộp thành một phép đo trên cùng prompt.

Lượt plan/author V4 dùng 43 requests thật gồm kiểm tra lại được ghi rõ; tổng quan sát các bước/probe sau đó là 51 requests trong đợt trước, không phải 51 requests của lượt rà soát offline này. Các probe Ling/Gemma/ERNIE gặp 429; không đủ bằng chứng chọn fallback. Metadata `usage_daily=0` là số tiền, không chứng minh còn quota requests. Prompt hiện ghi nhận `lesson-vi-2026-11-24-14`.

Đã có bảng rubric cho đủ 20 đầu vào và bản biên tập tương ứng: [V4_EDITORIAL_AUDIT.md](V4_EDITORIAL_AUDIT.md). Người chấm là Codex AI, ghi nhận xét chủ quan từng tiêu chí; không phải giáo viên độc lập, không nhận tỷ lệ kiến thức chính xác và không lấy bản sửa nâng điểm model thô. JSON local gắn SHA-256 của đầu ra gốc/bản sửa/PPTX. Các ca 7/17 có tham chiếu SGK tự bịa; nhiều ca khác có lỗi kiến thức/phạm vi/ngôn ngữ.

Quyết định: giữ model cho preview có nhãn thử nghiệm và rà soát, giữ `AI_SLIDES_CONTENT_QA_APPROVED=false`; không nâng thành tự động tạo nội dung được chứng nhận. Các guard số học, quote, nguồn/quiz chỉ là kiểm tra hẹp. Không cần gọi thêm AI hoặc tiêu quota để xuất/đọc lại bộ mẫu đã có.
