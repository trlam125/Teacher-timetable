# Hoàn thiện V4 — 24/11/2026

Theo IMPLEMENTATION_PLAN_V4.md, đối chiếu mã và PROGRESS.md. Nhánh codex/ai-slides-render-free; chỉ triển khai preview riêng. Không điều khiển Desktop. Chỉ AI miễn phí đã kiểm tra giá tại runtime; không dùng chatbot cũ.

## Đợt chốt bổ sung ngày 24/11

Đã deploy mã ứng dụng 3ee49e904a878a897ffee6ea087b0908e91a2cb3 (dep-dc2pvlek1f9s738p157g) sau CI thành công: 116 backend/tooling, 20 Node và 80 nhóm headless. Smoke preview thật đạt cảnh báo phép tính/đáp án tương đương, persist/reload, sửa đúng hết cảnh báo và tải PPTX native; 0 inference, 0 JS error, dọn dữ liệu QA. Main giữ commit/deploy cũ theo Render API. Không thêm bảng/cột hoặc thay model/key. Fixture/PG QA local đã dừng; các thư mục thử rỗng đã dọn.

Người dùng xác nhận chưa kiểm tra 20 bộ. Đã hoàn thiện bộ duyệt offline tại tmp/ai-studio-qa/v4-review-desk/index.html: 20 bài × hai phiên bản AI gốc/bản biên tập, 200 ảnh HTML, nguồn/Notes, rubric 100 điểm và ba hard fail; ghi kết quả Desktop riêng, lưu/khôi phục JSON có SHA-256 của từng tệp. Không tự chấm điểm kiến thức, không lấy kết quả bản sửa nâng điểm model và không tự bật cờ phê duyệt. Xem HUMAN_REVIEW.md. ZIP V4-ban-duyet-20-bai-offline.zip khoảng 7,7 MB, chỉ nằm local.

Đã bổ sung kiểm tra hẹp về phép tính số/phần trăm và đáp án quiz trùng hoặc tương đương cùng đơn vị. AI trả lỗi rõ ràng bị chặn và giữ dàn ý; sửa tay được giữ kèm cảnh báo. Có mã AI_ARITHMETIC_ERROR/AI_QUIZ_ERROR và ID slide trong log. Không coi bộ kiểm tra này là chứng minh đại số, đổi đơn vị hoặc kiểm chứng kiến thức. Đã phát hiện và sửa false positive do cắt đuôi biểu thức; quét lại 200 slide thô/biên tập không còn false positive đã biết, không nâng trạng thái sư phạm của chúng.

Local đạt 116 ca backend/tooling và 80 nhóm headless. Bộ duyệt thực có 40 bản/200 ảnh, cấu trúc JSON/PPTX/Notes đọc được, không request HTTP hoặc JS error, số phiếu thật đã duyệt vẫn bằng 0. Ảnh là HTML, không phải Office renderer. CI/deploy/smoke của đợt này đã đạt theo ghi nhận ở đầu mục.

Đã đọc lại catalog/key: key free-tier, không gọi paid. Probe bổ sung đúng một request vào baidu/ernie-5.5-flash-preview:free trả 429; dừng, không đổi model/key. Không có đủ bằng chứng để chọn model miễn phí thay thế đạt chất lượng. usage_daily=0 trong metadata key là số tiền sử dụng, không phải bộ đếm lượt còn lại.

## Mã chức năng đã bổ sung trong đợt này

- [x] F36: liên kết HTTPS từ tên miền cho phép, chuẩn hóa video ID, không fetch URL tùy ý; luôn ghi chưa xác minh nội dung/quyền sử dụng. PPTX/Notes giữ link và nguồn.
- [x] F25/F26/F28: bước AI inspect có quota, idempotency, lịch sử; kiểm tra quote nguyên văn; gợi ý metadata trước khi điền đủ form hoặc trong bài đã lưu. Không ghi đè trường giáo viên. Mâu thuẫn ngữ nghĩa là gợi ý để chọn, không xác minh tri thức.
- [x] F29/F35: cắt đoạn bài theo tiêu đề kể cả chung trang, lưu index/phạm vi; relink kiểm tra fingerprint. Giới hạn 200 tiêu đề, 400 trang/sách và 50 trang/bài.
- [x] F31: mở rộng chỉ từ tài liệu tham khảo đã chọn, có provenance và nhãn nguồn bổ sung; không tự tìm web hoặc nhận kiến thức model tự sinh là verified.
- [x] F13: tuyến quan sát địa hình minh họa, điểm/vùng, phóng to và credit; không phải bản đồ hành chính hoặc chỉ đường.
- [x] F19: admin xem tổng deck/step/lỗi, token theo model/status và quota ngày UTC; không đọc nội dung bài của owner khác. Kill flag vẫn là cấu hình triển khai.
- [x] F20 phần mềm: kiểm tra chữ tràn ở cỡ tối thiểu và đối tượng vượt khung trước download; đã render HTML/export 20 bộ thô, 100 slide nội dung/107 trang PPTX. Chưa có visual regression bằng Office.
- [x] Hướng dẫn giáo viên tiếng Việt với ảnh UI từ fixture thật, chức năng và giới hạn được ghi rõ.

## P2 đã có bản giới hạn, có kiểm thử

- OCR tiếng Việt trên thiết bị, một ảnh hoặc một trang PDF; tự phục vụ worker/core/WASM/vie, không gửi ảnh ra ngoài. Chỉ thêm nguồn sau khi sửa/xác nhận. CER trên mẫu chữ rõ/PDF raster là 0; công thức mẫu 31,91%, không được nhận là OCR công thức chính xác.
- Nhập chữ PPTX theo thứ tự presentation relationships; macro/ActiveX bị chặn. Nhập style chỉ đọc bảng màu và gợi ý một theme hiện có, áp dụng do giáo viên chọn. Không bảo toàn ảnh/chart/OLE/SmartArt/Notes/template/hiệu ứng gốc.
- Giọng nói Web Speech nếu trình duyệt hỗ trợ; consent riêng, bản chép lời sửa được và áp dụng rõ ràng. Adapter dùng microphone giả trong test; chưa đo chất lượng nhận giọng nói thật.
- Lô tối đa 20 bài: xem/sửa từng đoạn, lưu draft, chạy tuần tự, dừng tại quota/cảnh báo, reload không inference, resume bỏ qua bài hoàn tất. Queue cục bộ chỉ có IDs/tên/tiến độ, không chứa file sách.
- ZIP offline có PPTX/Notes/JSON và hai mô phỏng + map cục bộ; map chạy được từ file URL. PhET/video/web ngoài cần Internet; nút trong PPTX vẫn trỏ website, dùng index.html khi offline.

## Chưa đóng nghiệm thu toàn V4

- [ ] Model/chất lượng nội dung: bộ 20 bài thô có lỗi kiến thức, ngôn ngữ, scope và SGK bịa. Đã ghi rõ trong V4_BENCHMARK_REVIEW.md; bản biên tập giữ riêng, không nâng điểm model thô. Ling/Gemma thử thay thế trả 429. Chưa chọn fallback hoặc nhận model đã đạt chuẩn sư phạm.
- [ ] Nghiệm thu độc lập/giáo viên và visual QA rộng bằng PowerPoint Desktop. Ba file motion đã được người dùng xác nhận từ đợt trước; không điều khiển Office trong đợt này.
- [x] CI đúng commit, deploy/smoke preview và mẫu số liệu vận hành; chi tiết bản cuối bên dưới.

AI_SLIDES_CONTENT_QA_APPROVED mặc định false; không tự bật vì test code đạt. Website chính không được cập nhật trong đợt này. Không thay schema DB cho các trường JSON mới.

## Kiểm thử và bộ mẫu giao được

Bản kiểm thử ở đợt trước: 7bf769a386032a318d79d249aa4cc88f609802f1, preview deploy dep-dc2p987lk1mc73al5ud0 (live tại thời điểm đó). CI đúng commit đạt 106 backend SQLite/PostgreSQL, 20 Node, build tái lập và 74 nhóm headless. Website chính vẫn deploy/commit a5207d63e4eeda633e6d3bc156c2301f9a673c06 theo Render API; không kiểm tra HTTP main hoặc đổi env/DB chính.

Smoke trên preview thật đạt hướng dẫn/ảnh/OCR assets, quyền teacher/admin, URL save/reload, native PPTX có nguồn và ZIP offline, OCR dưới CSP và inspect v14. Cùng profile/nguồn từng bị chặn nay trả HTTP200 trong 13,13 giây: 5 metadata gợi ý, 0 conflict, quote khớp, tăng version. Chỉ một AI request trong smoke cuối, tổng đợt 50 requests thật (gồm hai probe thay thế 429). Không tự retry hoặc gọi paid. Dọn toàn bộ user/deck/step/revision/usage/device QA; site quota vẫn tính lượt thật.

Metrics API chỉ của preview, khoảng 67 giây đầu sau deploy: mẫu RAM lớn nhất 172.355.580 byte (~164,4 MiB), giới hạn ~512 MiB. Studio capability/guide 113/81 ms, WASM/vie 507/346 ms trong smoke. Đây là mẫu warm/smoke rất ngắn, không phải kiểm thử tải hay cam kết không OOM. Không có lỗi JS hoặc service lỗi trong lượt quan sát. Fixture và cụm PostgreSQL QA local đã dừng.

CSP riêng cho các trang Studio đã được kiểm thử thực: chặn script/handler tùy ý, giữ hai handler cài đặt có hash và cho phép worker/WASM nội bộ. Không đổi CSP các trang Smart TKB cũ.

106 ca backend SQLite/PostgreSQL tạm, 20 test Node, compatibility spike và đủ 74 nhóm headless đạt. OCR dùng engine thực; giọng nói dùng adapter microphone giả. Hai mươi bộ thô và hai mươi bản biên tập đều xuất từ browser: mỗi bộ có 5 slide nội dung, tổng 107 trang PPTX/107 Notes, XML hợp lệ và không tràn theo kiểm tra HTML. Đây không phải render PowerPoint.

Gói cục bộ: tmp/ai-studio-qa/V4-20-bai-mau-can-giao-vien-duyet.zip (20 PPTX, JSON thay đổi biên tập, ảnh cover, danh sách và giới hạn). Chưa có giáo viên duyệt; dữ liệu thô vẫn giữ riêng. Các mẫu đã sửa không nâng kết quả benchmark AI thô.

DB preview Free có ngày hết hạn 22/12/2026, chỉ phục vụ thử nghiệm. Chưa coi preview là kho lưu trữ production bền vững. Chuyển production cần DB ổn định/backup và nghiệm thu nội dung; không tự đổi DB chính.

## Bằng chứng đã có trước đợt này

88 ca backend, 16 Node, 51 nhóm headless; native motion được người dùng xác nhận trên 3 tệp Desktop. Ba bộ strict AI thật/15 slide có đối chiếu trích đoạn; luồng một nút và PhET đã lên preview. Provider vẫn có timeout/429; chưa có nghiệm thu 20 bộ bài hoàn chỉnh. Các bằng chứng này không chứng minh provider hiện tại ổn định hoặc mọi nội dung đúng.
