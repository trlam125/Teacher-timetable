# OpenRouter miễn phí: kết quả kiểm tra thực tế

Ngày 22/11/2026. Chỉ dùng dữ kiện mẫu do bộ kiểm thử cung cấp; không gửi sách hay dữ liệu người dùng.

Model chọn cho pilot: `nvidia/nemotron-3-ultra-550b-a55b:free`. ID và mọi trường giá trong catalog được kiểm tra trước khi gọi; request có max_price prompt/completion bằng 0. Không có fallback sang model tính phí.

## Dàn ý đa môn

Bộ dữ kiện có 20 đề bài. Vòng đầu đạt 8/20 kiểm tra tự động; 12 lỗi gồm thiếu/sai source_ids, sai số slide và sai tổng thời lượng. Sau khi thêm hợp đồng đầu ra (số slide, mã nguồn hợp lệ, lịch thời lượng từng vị trí), kiểm tra lại 12 ca lỗi đạt 12/12. Tám ca đã đạt từ vòng đầu chưa được chạy lại bằng prompt mới; không coi đây là phép đo 20/20 trên cùng một cấu hình.

Trong kết quả đạt gần nhất của mỗi ca, độ trễ min/trung vị/max là 8.81/11.71/24.0 giây.

| Đề bài | Vòng đầu | Kiểm tra lại |
|---|---|---|
| Định luật Ôm | AI_SOURCE_ERROR | pass |
| Chu kỳ con lắc đơn | AI_SOURCE_ERROR | pass |
| Khối lượng riêng | pass | — |
| Điện trở mắc nối tiếp | pass | — |
| Định lý Pythagore | AI_SOURCE_ERROR | pass |
| Phương trình bậc hai | pass | — |
| Tỉ số phần trăm | AI_SOURCE_ERROR | pass |
| Số trung bình cộng | pass | — |
| Quang hợp | pass | — |
| Tế bào thực vật | AI_CONSTRAINT_ERROR | pass |
| Chuỗi thức ăn | AI_SOURCE_ERROR | pass |
| Vòng tuần hoàn nước | AI_SOURCE_ERROR | pass |
| Bảo toàn khối lượng | AI_CONSTRAINT_ERROR | pass |
| Thang pH | AI_CONSTRAINT_ERROR | pass |
| Tọa độ địa lí | AI_SOURCE_ERROR | pass |
| Khí hậu gió mùa | AI_CONSTRAINT_ERROR | pass |
| Cách mạng công nghiệp lần thứ nhất | pass | — |
| Ẩn dụ và so sánh | pass | — |
| Thì hiện tại đơn | pass | — |
| Chu vi hình chữ nhật | AI_CONSTRAINT_ERROR | pass |

Phạm vi chấm tự động: JSON/schema, số slide, tiêu đề giữ nguyên, ID không trùng, source_ids hợp lệ, đa dạng mục đích và tổng thời lượng. Các cảnh báo thiếu tư liệu được giữ và chặn soạn cho đến khi giáo viên xác nhận. Đây chưa phải điểm chất lượng sư phạm, độ chính xác toàn bộ nội dung hoặc đo chất lượng 20 bộ PPTX hoàn chỉnh.

## Bài hoàn chỉnh và đối chiếu

Nemotron Ultra đã soạn bài Định luật Ôm 15 slide qua 3 nhóm 5 slide. Các nhóm đầu mất khoảng 41,30 và 79,94 giây. Nhóm cuối sau cập nhật schema/prompt mất 65,64 giây. Timeout toàn bước đặt 85 giây; vượt hạn vẫn có thể xảy ra trên provider miễn phí và phần đã xong được giữ.

Bài mẫu có rà soát thủ công: đổi loại map sang concept cho sơ đồ mạch, đổi video không có trong kho thành mô phỏng, sửa ghi chú nói tới điều khiển nhiệt độ không tồn tại, bỏ gợi ý tên sách chưa xác minh. Bản thô và lịch sử rà soát được giữ trong tmp/ai-studio-qa, không đưa dữ liệu đó vào Git.

Xuất browser cho bài mẫu tạo 15 slide bài học và 4 trang phản hồi quiz. Bản gentle/minimal có 14 timing trees và 19 transitions; mọi XML được parse. Chưa chạy Slide Show bằng PowerPoint Desktop.

## Các ứng viên đã thử

- Particle: trả được JSON nhưng dàn ý 15 slide lặp tiêu đề/hoạt động; bị chặn bởi quality gate.
- Nemotron 3.5 Super VL: phản hồi dàn ý sai số slide trong lần thử.
- Ling và ERNIE Flash: HTTP 429 từ upstream tại thời điểm kiểm tra.
- Flint: phản hồi quá dài/chậm ở bài 15 slide.
- Chưa có fallback đủ bằng chứng chất lượng để tự động thay primary.

Kết luận sử dụng: phù hợp pilot có giáo viên rà soát, chưa đủ bằng chứng nghiệm thu đầy đủ V4.
