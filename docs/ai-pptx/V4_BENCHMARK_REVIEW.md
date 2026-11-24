# Rà soát benchmark V4 — 24/11/2026

## Kết quả quan sát

Model hiện hành: nvidia/nemotron-3-ultra-550b-a55b:free. 20 dàn ý hợp cấu trúc; lần soạn đầu 18/20 đạt cấu trúc. Ca 2 lỗi JSON, ca 12 chọn từ điền không hợp lệ. Kiểm tra lại hai ca: ca 2 lỗi labels/values biểu đồ không khớp, ca 12 đạt sau khi máy chủ hỗ trợ tự dựng câu điền nguyên văn. Sau khi siết chart_data=null cho nhóm không có chart, kiểm tra lại riêng ca 2 đạt. Tổng 43 requests plan/author cho 20 bộ hoàn chỉnh; có thêm một probe inspect đạt và hai probe model thay thế (Ling/Gemma) trả 429. Không đổi model đang chạy, không gọi paid model.

100 slide nội dung đã được mở qua UI loopback, kiểm tra chữ tràn và xuất browser thành 107 trang PPTX gồm phản hồi quiz; 107 Notes, XML parse được. Bốn theme được chọn riêng cho QA trình bày, không thay nội dung AI. Đây là render HTML và kiểm tra OOXML, không phải render bằng PowerPoint Desktop. Không gọi AI cho lượt render/export.

**Không đạt nghiệm thu model về chất lượng sư phạm.** Không chấm điểm 100 hoặc tự nhận giáo viên đã duyệt. Kết quả thô được giữ trong tmp/ai-studio-qa/v4-benchmark; bản chỉnh biên tập tách ở v4-reviewed, có editorial_review.changes và teacher_approved=false. Không dùng các bản đã sửa để nâng tỷ lệ chất lượng của model thô.

Hai mươi bản biên tập cũng đã được xuất qua UI (107 trang PPTX/107 Notes), XML parse được, không tràn theo kiểm tra HTML; bốn theme QA. Gói V4-20-bai-mau-can-giao-vien-duyet.zip chứa PPTX/JSON/cover/danh sách để xem. Việc xuất được file không thay thế giáo viên kiểm tra kiến thức và PowerPoint Desktop kiểm tra hiển thị.

## Những gì đọc thấy trong bài thô

| Ca | Chủ đề | Nhận xét biên tập trước khi dùng |
|---|---|---|
| 1 | Ôm, strict | Trích đoạn đúng, ít ý và lặp do nguồn rất ngắn; chưa đủ độ sâu cho một tiết. |
| 2 | Con lắc | Gọi đồ thị T theo L là parabol, có chữ Hàn và hướng dẫn mô phỏng cần làm rõ; câu hỏi ẩn ở layout không quiz có giải thích mâu thuẫn. |
| 3 | Khối lượng riêng | So sánh nặng/nhẹ thiếu điều kiện cùng thể tích; đoán vật liệu từ một giá trị chưa đủ căn cứ. |
| 4 | Điện trở nối tiếp | Mô tả PhET có hai điều khiển R1/R2 và mở rộng sang song song ngoài trọng tâm. |
| 5 | Pythagore, strict | Trích đoạn đúng; lặp và ít hoạt động vì nguồn ngắn. |
| 6 | Bậc hai | Bài hình chữ nhật mở đầu không khớp ví dụ sau; câu hỏi ẩn có hai phương án nghiệm tương đương. |
| 7 | Phần trăm | Bịa SGK trang 45, bài 1–3: hard fail của benchmark. |
| 8 | Trung bình cộng | Phép tính mẫu đúng; cần điều kiện tập hữu hạn không rỗng, n > 0. |
| 9 | Quang hợp | Có chữ Hàn xen trong Notes, diễn đạt vụng; nhiều kiến thức ngoài nguồn cần giáo viên kiểm tra. |
| 10 | Tế bào | Có thuật ngữ vô nghĩa, lẫn vai trò thành tế bào/sức trương; tự suy đoán giới hạn chương trình. |
| 11 | Chuỗi thức ăn | Thêm tỷ lệ 10% ngoài nguồn rồi lặp như quy luật cố định; cần giữ định tính hoặc cung cấp dữ liệu có nguồn. |
| 12 | Nước, strict | Trích đoạn và câu điền đối chiếu được sau sửa hợp đồng; nội dung vẫn mỏng vì nguồn ngắn. |
| 13 | Bảo toàn khối lượng | Diễn đạt hệ kín/hệ mở và bài khí tạo ra cần làm rõ để tránh hiểu luật không còn đúng trong hệ mở. |
| 14 | pH | Diễn giải giấy chỉ thị, giới hạn 0–14 và độ mạnh acid quá mức/ngoài nguồn; ví dụ y sinh chưa có nguồn. |
| 15 | Tọa độ, strict | Trích đoạn đúng, có đối chiếu; cần thêm dữ liệu để xây hoạt động phong phú. |
| 16 | Gió mùa | Gán mùa mưa/khô đồng nhất theo vùng không có bằng chứng; xen chữ Hán trong Notes. |
| 17 | Công nghiệp | Tự gắn Bài 15 và ngày cụ thể không có trong nguồn; thuật ngữ/diễn đạt cần chỉnh. |
| 18 | Tu từ | Từ ngữ lỗi và quy tắc A+là+B cho mọi ẩn dụ không được nguồn hỗ trợ; cần xét nghĩa/ngữ cảnh. |
| 19 | Hiện tại đơn | Mẫu động từ thường hợp lý; cần nêu phạm vi do/does và ngoại lệ be. |
| 20 | Chu vi | Công thức và ví dụ nguồn đúng; xen chữ Hán trong Notes. |

## Thay đổi phần mềm sau các phát hiện

- Schema/prompt yêu cầu chart_data=null ở nhóm không có chart; số JSON dùng dấu chấm thập phân.
- Nhóm không quiz yêu cầu trường quiz rỗng. Máy chủ bỏ các trường quiz không sử dụng trên layout khác, không giấu câu hỏi chưa rà soát trong manifest.
- Với quiz strict, model có thể trả null/[] để máy chủ chọn từ và đáp án khác từ đúng nguồn của slide. Lựa chọn sai do model gửi rõ vẫn bị chặn; không sửa đáp án bịa.
- Kết quả AI mới có trang SGK không khớp nguồn, chữ Hán/Hàn không có trong nguồn hoặc điều khiển PhET R1/R2 sai bị chặn và ghi mã lỗi. Chỉnh tay của giáo viên vẫn có thể thực hiện với cảnh báo; đề xuất AI chỉ được kiểm tra phần thay đổi.
- Log lỗi JSON có đường dẫn và mô tả ràng buộc, không log nguồn hoặc API key.
- AI_SLIDES_CONTENT_QA_APPROVED mặc định false. UI ghi rõ đang thử nghiệm chất lượng; không tự bật cờ này vì test phần mềm đạt.

Các chặn trên chỉ xử lý những dạng lỗi cụ thể, không phải hệ thống kiểm chứng tri thức. Còn cần benchmark model miễn phí khác khi có endpoint/quota và nghiệm thu độc lập về kiến thức, sư phạm, phù hợp lớp. Dữ liệu QA tổng hợp không phải bản quét SGK hay xác nhận chương trình học hiện hành.
