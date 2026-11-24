# Thay đổi AI Studio

## 24/11/2026 — rà soát mẫu và hoàn thiện hồ sơ V4

- Rà soát nguồn và sửa 20 bộ nhỏ/100 slide, gồm mục tiêu, Notes, hoạt động, quiz, học liệu. Thêm nguồn tham khảo trong Notes; giữ riêng đầu ra AI gốc và không kế thừa bằng chứng trích nguyên văn khi biên tập.
- Thêm bảng rubric do Codex AI chấm và gói `V4-20-bai-mau-da-ra-soat.zip`. Không ghi thành giáo viên phê duyệt hoặc model đạt chất lượng.
- Gắn hash JSON/PPTX vào báo cáo export; từ chối đóng gói nếu bài đã đổi sau khi rà soát hoặc chưa xuất lại.
- Bổ sung API.md, 00-audit.md và AI_MODELS_BENCHMARK.md, liên kết các báo cáo cũ để giữ lịch sử.
- Không sửa mã ứng dụng, migration, env hoặc website chính trong lượt này.

## 24/11/2026 — mã ứng dụng `3ee49e9`

Chặn lỗi số học rõ ràng và đáp án quiz tương đương trong nội dung AI; sửa tay giữ nội dung kèm cảnh báo. Bổ sung bàn duyệt offline tách raw/edited và ràng buộc hash; CI/deploy/smoke preview đạt. Chi tiết [QA](QA.md), [V4_COMPLETION](V4_COMPLETION.md).

Các đợt trước: [PROGRESS.md](PROGRESS.md), [ANIMATIONS_COMPATIBILITY.md](ANIMATIONS_COMPATIBILITY.md). Chỉ các deploy được ghi nhận live mới tính là đã triển khai; bài test mock/HTML không được gọi là Office hoặc xác minh chất lượng model thật.
