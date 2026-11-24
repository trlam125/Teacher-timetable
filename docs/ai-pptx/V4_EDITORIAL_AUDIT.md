# Rà soát nội dung V4 do Codex thực hiện — 24/11/2026

Đã đọc và biên tập 20 bộ mẫu, 100 slide nội dung, gồm mục tiêu, Notes, hoạt động, quiz và học liệu. Điểm dưới đây là nhận xét chủ quan của AI theo rubric 100 điểm, không phải tỷ lệ chính xác, không có ngưỡng đỗ tự đặt và không phải phiếu duyệt của giáo viên. Không lấy điểm bản sửa để đánh giá model thô.

Mỗi bộ chỉ có 5 slide nội dung để QA. Đây chưa phải 20 giáo án hoàn chỉnh cho thời lượng nhập. Bản sửa bỏ bằng chứng trích nguyên văn kế thừa; các bài strict đã mở rộng sẽ hiện cảnh báo cần rà soát. Nguồn bổ sung ghi trong Notes, không thay nguồn người dùng đã nhập.

Rubric: kiến thức 30 / bằng chứng 20 / sư phạm 20 / tiếng Việt 10 / học liệu 10 / cấu trúc 10. JSON đi kèm giữ điểm từng tiêu chí, lý do, SHA-256 và kiểm tra cấu trúc.

| Ca | Bài | AI gốc | Bản sửa | Phát hiện và sửa chính |
|---|---|---:|---:|---|
| 1 | Định luật Ôm | 73 | 80 | Đúng trích đoạn nhưng lặp; quiz điền từ chưa kiểm tra vận dụng công thức. |
| 2 | Chu kỳ con lắc đơn | 46 | 82 | Sai dạng đồ thị; lẫn tiếng Hàn; mô tả đo thực nghiệm vượt chức năng mô phỏng. |
| 3 | Khối lượng riêng | 61 | 79 | Lẫn khối lượng với khối lượng riêng; suy tên vật liệu từ một giá trị. |
| 4 | Điện trở mắc nối tiếp | 57 | 82 | Mô tả hai điện trở trong mô phỏng một điện trở; lệch phạm vi nối tiếp. |
| 5 | Định lý Pythagore | 72 | 80 | Nguồn đúng nhưng lặp; thiếu kiểm tra nhận diện cạnh huyền và vận dụng. |
| 6 | Phương trình bậc hai | 52 | 79 | Điều kiện bài hình chữ nhật không khớp phương trình; thiếu phạm vi nghiệm thực. |
| 7 | Tỉ số phần trăm | 61 | 79 | Bịa trang SGK 45; ký hiệu đổi phần trăm cần làm rõ. |
| 8 | Số trung bình cộng | 72 | 79 | Thiếu điều kiện n > 0; cần giải thích ảnh hưởng giá trị rất lớn. |
| 9 | Quang hợp | 55 | 79 | Lẫn tiếng Hàn; suy khả năng quang hợp từ màu lá; mở rộng thiếu nguồn. |
| 10 | Tế bào thực vật | 48 | 79 | Thuật ngữ vô nghĩa; lẫn thành tế bào với sức trương; khẳng định quá rộng. |
| 11 | Chuỗi thức ăn | 57 | 79 | Cố định truyền năng lượng 10%; chữ Trung còn trong hoạt động giáo viên. |
| 12 | Vòng tuần hoàn nước | 72 | 80 | Nguồn đúng nhưng lặp; câu điền từ ít giá trị đánh giá hiểu chu trình. |
| 13 | Bảo toàn khối lượng | 64 | 79 | Hệ mở/kín và cân riêng chất rắn chưa phân biệt rõ. |
| 14 | Thang pH | 54 | 79 | Giới hạn pH 0–14 tuyệt đối; lẫn độ mạnh với nồng độ; hoạt động vượt nguồn. |
| 15 | Tọa độ địa lí | 72 | 80 | Đúng khái niệm nhưng lặp; thiếu bài đọc tọa độ minh họa. |
| 16 | Khí hậu gió mùa | 44 | 75 | Gán mùa mưa/khô đồng loạt cho vùng; bản đồ địa hình không có dữ liệu gió. |
| 17 | Cách mạng công nghiệp lần thứ nhất | 55 | 75 | Bịa số bài SGK; thêm mốc/điều kiện lịch sử chưa được nguồn ngắn hỗ trợ. |
| 18 | Ẩn dụ và so sánh | 47 | 75 | Quy tắc A+là+B và từ nối bị tuyệt đối hóa; chữ Trung trong tổng kết. |
| 19 | Thì hiện tại đơn | 71 | 79 | Quy tắc es theo đuôi o quá rộng; mẫu do/does cần giới hạn động từ thường. |
| 20 | Chu vi hình chữ nhật | 74 | 79 | Chữ Trung, thiếu đáp án bài tập và nói có hình trên slide khi chưa có. |

## Nguồn đối chiếu và phạm vi

- Bài 1 — Định luật Ôm: [OpenStax Physics 19.1](https://openstax.org/books/physics/pages/19-1-ohms-law). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 2 — Chu kỳ con lắc đơn: [OpenStax University Physics 15.4](https://openstax.org/books/university-physics-volume-1/pages/15-4-pendulums). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 3 — Khối lượng riêng: [OpenStax College Physics 11.2](https://openstax.org/books/college-physics-2e/pages/11-2-density). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 4 — Điện trở mắc nối tiếp: [OpenStax Physics 19.2](https://openstax.org/books/physics/pages/19-2-series-circuits). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 5 — Định lý Pythagore: [OpenStax Prealgebra 9.3](https://openstax.org/books/prealgebra-2e/pages/9-3-use-properties-of-angles-triangles-and-the-pythagorean-theorem). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 6 — Phương trình bậc hai: [OpenStax Algebra and Trigonometry 2.5](https://openstax.org/books/algebra-and-trigonometry-2e/pages/2-5-quadratic-equations). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 7 — Tỉ số phần trăm: [OpenStax Prealgebra 6.1](https://openstax.org/books/prealgebra-2e/pages/6-1-understand-percent). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 8 — Số trung bình cộng: [OpenStax Introductory Statistics 2.5](https://openstax.org/books/introductory-statistics-2e/pages/2-5-measures-of-the-center-of-the-data). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 9 — Quang hợp: [OpenStax Biology 8.1](https://openstax.org/books/biology-2e/pages/8-1-overview-of-photosynthesis). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 10 — Tế bào thực vật: [OpenStax Biology 4.3](https://openstax.org/books/biology-2e/pages/4-3-eukaryotic-cells). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 11 — Chuỗi thức ăn: [OpenStax Biology 46.2](https://openstax.org/books/biology-2e/pages/46-2-energy-flow-through-ecosystems). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 12 — Vòng tuần hoàn nước: [NOAA — The Hydrologic Cycle](https://www.noaa.gov/jetstream/atmosphere/hydro). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 13 — Bảo toàn khối lượng: [OpenStax Chemistry 1.2](https://openstax.org/books/chemistry-2e/pages/1-2-phases-and-classification-of-matter). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 14 — Thang pH: [OpenStax Chemistry 14.2](https://openstax.org/books/chemistry-2e/pages/14-2-ph-and-poh). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 15 — Tọa độ địa lí: [NOAA — Latitude / Longitude](https://oceanservice.noaa.gov/facts/latitude.html), [NOAA — Latitude / Longitude](https://oceanservice.noaa.gov/facts/longitude.html). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 16 — Khí hậu gió mùa: [NOAA — The North American Monsoon, p. 2](https://www.cpc.ncep.noaa.gov/products/outreach/Report-to-the-Nation-Monsoon_aug04.pdf). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 17 — Cách mạng công nghiệp lần thứ nhất: [OpenStax World History 6.3](https://openstax.org/books/world-history-volume-2/pages/6-3-capitalism-and-the-first-industrial-revolution). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 18 — Ẩn dụ và so sánh: [Academy of American Poets — Poetry Glossary](https://poets.org/lesson-plan/poetry-glossary). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 19 — Thì hiện tại đơn: [British Council — Present simple](https://learnenglish.britishcouncil.org/free-resources/grammar/english-grammar-reference/present-simple). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.
- Bài 20 — Chu vi hình chữ nhật: [OpenStax Prealgebra 9.4](https://openstax.org/books/prealgebra-2e/pages/9-4-use-properties-of-rectangles-triangles-and-trapezoids). Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.

## Kết luận sử dụng

Đã hoàn tất lượt rà soát AI thay cho việc yêu cầu người dùng chấm 20 bộ trong lượt này. 20 bản sửa đã được xuất lại bằng Chromium ẩn; đây là ảnh HTML và kiểm tra OOXML, không phải PowerPoint renderer. Ba tệp motion trước đó được người dùng báo chạy đúng trong PowerPoint Desktop; không gán kết quả đó cho 20 tệp mới.

Bộ AI gốc có lỗi rõ ràng, gồm tham chiếu SGK tự bịa ở ca 7/17. Model hiện tại chưa đủ bằng chứng để phê duyệt nội dung tự động. Giữ AI_SLIDES_CONTENT_QA_APPROVED=false. Không chặn việc dùng preview có rà soát và không thay website/DB chính.
