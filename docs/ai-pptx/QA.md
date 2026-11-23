# Kết quả kiểm thử AI Studio

Ngày 22/11/2026. Nhánh codex/ai-slides-render-free từ a5207d6.

## Phương pháp

Kiểm thử API qua FastAPI TestClient, PostgreSQL tạm trên loopback, Node.js trong codex-skill-env và Chromium headless từ .venv của dự án. Từ khi người dùng yêu cầu ngừng điều khiển máy, mọi kiểm tra tiếp theo dùng dòng lệnh và tệp đầu ra.

## Đã đạt

Đợt kiểm tra cuối gồm 32 ca backend trên SQLite/PostgreSQL, 6 ca exporter Node và 14 nhóm kiểm tra qua Chromium headless. Các ca đều đạt. Provider headless dùng fixture, tệp PPTX tải xuống được tạo thực trong browser.

- Quyền teacher/admin/super_admin, feature flag và CSRF.
- Cách ly bài giảng theo owner, gồm đọc, sửa, lịch sử và xóa.
- Kiểm tra consent trước cloud call và lưu nguồn.
- Plan/author lưu kết quả, replay yêu cầu hoàn thành không gọi provider lần nữa.
- Author nhóm 5 slide, lưu 3 nhóm cho bài 15 slide; lỗi nhóm sau giữ phần trước và tiếp tục đúng vị trí.
- Nhật ký theo owner có model, loại bước, phiên bản, mã lượt và lỗi. Lỗi schema ghi đường dẫn trường, không ghi nội dung nguồn hoặc API key.
- Timeout giữ dàn ý và giải phóng lease, lượt lỗi tính quota.
- Khóa phiên bản, yêu cầu đồng thời và kết quả về muộn.
- Schema structured output, kiểm tra model miễn phí, nguồn hợp lệ và mục tiêu giáo viên khóa.
- Headless tạo bài, reload, xuất PPTX, sửa, undo, scoped AI proposal và duyệt thay đổi.
- PDF 150 trang có bookmark, chọn trang 35–36 và trích đúng hai trang.
- DOCX có đoạn và bảng, TXT UTF-8, cảnh báo PDF scan.
- IndexedDB giữ sách sau reload, màn hình 390 px không tràn ngang.
- Công thức Ôm, chu kỳ góc nhỏ và chọn vùng trên bản đồ khái quát.
- PPTX giữ chữ Việt, notes, hyperlink, đối tượng chỉnh sửa được và timing/transition qua round-trip.

Báo cáo chi tiết chạy headless và ảnh do trình duyệt headless tạo nằm ở tmp/ai-studio-qa. Tệp browser-export.pptx được tạo bằng exporter trong browser.

## Giới hạn đã xác định

Provider của bộ E2E dùng fixture riêng cho test. OpenRouter thật đã được kiểm tra với key riêng và model miễn phí. Xem BENCHMARK.md: vòng đầu đạt 8/20 dàn ý, sau siết hợp đồng đầu ra kiểm tra lại 12 lỗi đạt 12/12. Chưa có điểm chất lượng sư phạm 20 bài hoàn chỉnh.

Bài Định luật Ôm 15 slide được soạn bằng API thật, có rà soát/sửa nội dung mẫu được ghi lại riêng. Các nhóm 5 slide mất khoảng 41–80 giây, timeout tổng 85 giây. Tệp live-ohm-basic.pptx có 19 slide gồm 4 trang phản hồi. Hai bản QA gentle/minimal có 14 timing trees và 19 transitions; không đồng nghĩa đã xác nhận playback.

Đã xác nhận website chính trên Render dùng Neon. Lần triển khai ban đầu đã sao lưu DB, tạo 5 bảng Studio riêng, rồi deploy `e4ff596`. Theo yêu cầu tách kiểm thử, service chính đã được đưa về nhánh main và commit `a5207d6`; các biến AI_SLIDES_* đã gỡ. Năm bảng Studio trên Neon đều có 0 dòng khi kiểm tra trước khi tạo môi trường preview riêng. Không có bài giảng thử được lưu vào DB chính.

PowerPoint Desktop Slide Show chưa được kiểm tra. Native motion vẫn bị khóa ở capabilities.

Đã có 15 bố cục riêng dùng cùng scene cho preview/PPTX, với sơ đồ chỉnh sửa được, biểu đồ native và SVG bản đồ. Ảnh headless cho bài thật đã được xem và sửa tương phản mạch điện trên cover. Chưa render trực tiếp bằng PowerPoint hoặc LibreOffice. Bản đồ dùng đường bao đất liền Natural Earth, không biểu diễn địa giới hành chính hoặc phạm vi biển đảo đầy đủ.

## Kiểm thử preview Render riêng

Service `teacher-timetable-ai-preview-lam.onrender.com` chạy commit ứng dụng `e4ff596`, gói Free, với DB Render Postgres `ai_studio_preview` riêng. Không sao chép dữ liệu người dùng hoặc thời khóa biểu từ website chính; không cấu hình mail hoặc key chatbot cũ cho preview. Tài khoản quản trị preview dùng thông tin xác thực riêng trong `.env.ai-preview` bị Git bỏ qua.

Đã kiểm tra thực tế trên preview:

- Đăng nhập bằng tài khoản giáo viên tạm; capabilities nhận đúng cấu hình AI; API từ chối thiếu đăng nhập và CSRF.
- OpenRouter thật tạo dàn ý 5 slide trong 12,20 giây và soạn nội dung trong 48,13 giây ở lượt thành công. Lượt trước đó gặp AI_TIMEOUT ở giới hạn 85 giây; có log model, mã lỗi và mã lượt. Không tự retry vô hạn.
- Browser headless mở bài đã lưu, xem nhật ký model và tải PPTX thực tế. Không có lỗi JavaScript chưa xử lý. Tài khoản/dữ liệu smoke tạm đã được xóa sau kiểm thử.
- Ba kiểm tra tệp tải xuống đạt: tiêu đề slide đầu đúng manifest, metadata giữ tên bài, các XML hợp lệ và notes được giữ. Script smoke ban đầu nhầm slide đầu luôn là cover; đã sửa giả định và kiểm tra lại chính tệp tải xuống, không gọi AI lại để sửa test này.
- Tài khoản quản trị preview đăng nhập đúng; sửa slide, reload và hoàn tác qua API thật; tải được bài mẫu đã rà soát.
- Browser trên preview đọc PDF mẫu 150 trang, chọn bookmark và chỉ trích trang 35–36; màn hình 390 px không tràn ngang; mô phỏng Ôm đổi U cập nhật đúng I.

Bài mẫu lưu cho quản trị preview đã rà soát thủ công: bỏ tham chiếu trang SGK không có nguồn, làm rõ sự phụ thuộc R theo nhiệt độ và quan hệ nghịch biến I–R. Bản AI thô còn trong artifact local để đối chiếu. Kết quả này xác nhận luồng phần mềm, không chứng minh mọi nội dung AI tạo đều đúng kiến thức. Giáo viên vẫn cần rà soát bài giảng.

Báo cáo và artifact nằm trong `tmp/ai-studio-qa`: `preview-smoke-report.json`, `preview-smoke-timeout-report.json`, `preview-admin-browser-report.json`, `preview-smoke-export.pptx` và `preview-reviewed-export.pptx`. Thông tin triển khai và thời hạn DB xem DEPLOY_RENDER_FREE.md.

## Đợt hoàn thiện editor — 23/11/2026

Đã chạy đạt 40 ca backend trên SQLite và PostgreSQL kiểm thử riêng, 6 ca exporter Node cùng spike 5 slide, 14 nhóm browser hồi quy và 8 nhóm editor/search mới. Node chạy trong container `codex-skill-env`; browser chỉ chạy headless.

Các ca mới kiểm tra sửa/reorder dàn ý và thời lượng được lưu sau reload; ràng buộc owner/version/nguồn; xác nhận rõ khi soạn lại bài đã có nội dung và hoàn tác phục hồi nội dung cũ. Đổi theme/mức hiệu ứng giữ nguyên manifest và dàn ý, không gọi provider. Có thể sửa câu hỏi/phương án/đáp án/giải thích quiz và kiểu/dữ liệu biểu đồ bằng tay. Slide đang chọn được giữ khi reload.

Kiểm tra biên tập nêu tham chiếu sách/số trang chưa xác minh trong tiêu đề, bullets, notes, câu hỏi/phương án, giải thích và hoạt động GV/HS. Có test tái hiện trường bị bỏ sót trước khi sửa. Khi có cảnh báo, browser yêu cầu xác nhận rà soát trước khi tải PPTX/ghi chú. Đây không phải phép kiểm chứng độ đúng kiến thức hoặc nguồn gốc; không coi việc người dùng đánh dấu xác nhận là nguồn đã được xác minh.

PDF mẫu 150 trang được tìm theo nội dung tại thiết bị, chọn được trang 35 mà không gửi toàn sách lên server. Search giới hạn cache mỗi trang 40.000 ký tự và kết quả tối đa 40 trang. Chưa có OCR hay tự suy luận tên bài/chương khi PDF không có lớp chữ.

Artifact mới: `editor-headless-report.json`, `outline-editor-desktop.png`, `rich-editor-desktop.png`, `reviewed-editor-export.pptx` trong thư mục local `tmp/ai-studio-qa`. Đã xem ảnh dàn ý. Native motion vẫn chưa đạt gate PowerPoint Desktop.

Đã deploy commit ứng dụng `5ac5b23` lên preview riêng và smoke bằng provider thật: tạo dàn ý 11,05 giây, lưu chỉnh dàn ý bằng API rồi soạn 5 slide có chart/quiz trong 39,46 giây. Browser thật chạy headless trên preview đã đổi theme, sửa quiz/biểu đồ, lưu, soạn lại dàn ý và hoàn tác, xem nhật ký và tải PPTX có chart. Tài khoản và bài smoke tạm đã được dọn. Báo cáo `phase2-smoke-report.json`, `phase2-smoke-export.pptx`, `phase2-studio.png` ở artifact local.

Nội dung mẫu provider vẫn có diễn đạt khái quát quá mức về dây kim loại và điều kiện nhiệt độ; có hướng dẫn xem video tùy chọn dù phạm vi yêu cầu không dùng video. Đây là hạn chế chất lượng AI, không được tính là nội dung đã nghiệm thu. Tệp smoke phục vụ kiểm tra phần mềm và bài trên tài khoản tạm đã bị xóa. Các cảnh báo heuristic hiện chưa phát hiện mọi sai kiến thức hoặc sai phạm vi bằng ngôn ngữ tự nhiên.

Lượt chạy smoke trước đó dừng ở chờ người kiểm thử rà soát dàn ý, trước khi gọi author; đây là lỗi điều phối script QA, không phải lỗi ứng dụng. Lượt sau đã được rà soát và hoàn thành. Không tính lượt dừng này là một ca đầu ra thành công.

## Bật native sau phản hồi Desktop — 23/11/2026

Người dùng báo “Cả 3 tệp chạy đúng” cho ba bộ QA Ôm/khoa học nước/địa lí và checklist Slide Show, đối tượng hiện từng bước, chuyển cảnh, quiz/Notes, không repair warning. Đây là xác nhận thủ công do người dùng cung cấp; agent không điều khiển Desktop. Chưa có phiên bản Office hoặc ảnh/video. Không suy ra tương thích mọi Office.

Đã bổ sung AI_SLIDES_NATIVE_MOTION_ENABLED mặc định false. Sau QA này có thể bật riêng preview. Bộ kiểm thử cuối đạt 42 ca backend SQLite/PostgreSQL, 6 ca exporter, 14 + 8 + 4 nhóm browser. Bốn nhóm mới tải từ nút UI thật và kiểm tra timing/transition có mặt trong bản native, vắng trong bản cơ bản/reduced motion, và basic fallback dùng được sau khi cố tình chặn motion bundle. Không sửa engine/tham số animation của các fixture đã được người dùng xác nhận.

Artifact: `motion-headless-report.json`, `ui-native-motion.pptx`, `ui-basic-choice.pptx`, `ui-reduced-motion.pptx`, `ui-motion-fallback.pptx` trong `tmp/ai-studio-qa`.

Sau deploy `a923455` và bật cờ riêng trên preview, đã kiểm tra bằng tài khoản giáo viên tạm cùng bài mẫu Ôm trước đó: capabilities trả native_motion=true; nút tải xuất bản native 19 slide với 14 timing trees/19 transitions. Nút bản cơ bản và chế độ reduced-motion đều xuất 19 slide với 0 timing/0 transition. Mọi XML parse được, browser không có lỗi JavaScript chưa xử lý, tài khoản/bài tạm đã dọn. Không gọi AI ở smoke export này. Artifact `preview-native-ui-report.json`, `preview-native-ui.pptx`, `preview-basic-ui.pptx`, `preview-reduced-ui.pptx`, `preview-native-enabled.png`.

## Nhận diện và rà soát nguồn — 23/11/2026

56 ca backend SQLite/PostgreSQL đạt, gồm consent/nhận diện có bằng chứng, mâu thuẫn chặn provider trước quota, owner/version, lựa chọn giả/cũ bị từ chối, metadata giáo viên được giữ, quyết định gửi vào payload AI, nguồn thay đổi cần rà soát lại, xác nhận soạn lại khi đã có nội dung và undo. Các bài cũ không có source_resolutions vẫn đọc được; không cần đổi schema DB.

8 ca Node đạt; 7 nhóm mới `tests/studio_sources_headless.py` đạt với PDF tự tạo không có bookmark và dữ liệu văn bản tổng hợp. Kiểm tra không có request API trong lúc nhận diện tiêu đề PDF; trang in 93/108 trong mục lục không bị dùng làm trang PDF 3/6; chọn bài đặt phạm vi 3–5; tự điền metadata trống; không ghi đè tên khóa; chọn bằng chứng/persist/reload/plan; đổi nguồn xóa consent và quyết định cũ; mobile không tràn ngang/lỗi JavaScript. Bộ cũ 14 + 8 + 4 nhóm đạt. Đã xem ảnh nguồn trên mobile. Artifact mới: `source-review-headless-report.json`, `source-review-mobile.png`, `book-without-bookmarks.pdf` trong tmp/ai-studio-qa.

Thuật toán chỉ nhận diện tiêu đề rõ ràng và biểu thức ký hiệu trong ngữ pháp giới hạn. Không kiểm chứng đúng/sai, không giải tương đương toán tổng quát hoặc hiểu mâu thuẫn bằng văn xuôi. Chọn nguồn là chỉ dẫn cho AI; giáo viên vẫn cần rà soát đầu ra. Không tính các ca này là benchmark sư phạm hay chứng minh tách bài tự động hoàn hảo.

Đã deploy `7fc95c4` sau CI thành công. Smoke trên preview với tài khoản giáo viên tạm xác nhận API nhận diện và nguồn/trang PDF; plan bị chặn khi chưa chọn bằng chứng; UI hiển thị quyết định đã lưu. Planner thật mất 8,45 giây, có cảnh báo nguồn B; agent đọc dàn ý/cảnh báo rồi xác nhận để tiếp tục **kiểm thử phần mềm**. Author thật mất 43,26 giây. Nút tải native xuất 5 slide/5 timing/5 transitions, mọi XML parse được. Bài dùng I=U/R làm công thức chính, nguồn B được trình bày để đối chiếu biểu thức sai. Tài khoản và dữ liệu tạm đã dọn, không hoàn lại quota site.

Hạn chế thực tế quan sát: strict vẫn thêm dụng cụ đo/linh kiện không có trong excerpt và gợi bài tập SGK không xác định. Không tính là đầu ra bám sát nguồn đạt hoặc bài giảng đã nghiệm thu. Artifact: `preview-source-smoke-report.json`, `preview-source-plan.json`, `preview-source-deck.json`, `preview-source-smoke.pptx`, `preview-source-choice.png` tại tmp/ai-studio-qa. Chỉ là nguồn tổng hợp, không chứa tài liệu người dùng.

Website chính vẫn commit `a5207d6`, /login=200, /ai-studio=404; không đổi DB/env chính. Chỉ service preview được deploy. Các lần chạy local và cloud đều dùng headless/HTTP/CLI, không điều khiển desktop.

## Hợp đồng trích đoạn strict — 23/11/2026

68 ca SQLite/PostgreSQL đạt, gồm từ chối mã trích đoạn giả/ngoài phạm vi, loại biểu thức đã bị giáo viên bỏ, giữ dàn ý khi lỗi, ghi log mã lỗi an toàn, literal quote/proof digest, legacy replan trước provider, sửa tay không tự nhận proof, đúng đề xuất AI mới được apply giữ proof và undo khôi phục proof. Chỉ JSON của deck/revision thay đổi; không đổi schema DB.

9 ca Node đạt, gồm ca mới tái hiện/sửa sơ đồ tự thêm I=U/R từ tên bài khi strict. Các ca motion/links/notes và 15 layout vẫn đạt. 6 nhóm headless mới đạt, bộ 33 nhóm cũ vẫn đạt. Tệp tải từ UI có timing native, quiz thêm đúng số trang phản hồi theo số phương án. Đã xem ảnh mobile, không tràn ngang/lỗi JS. Artifact: grounding-headless-report.json, grounded-headless.pptx, grounding-evidence-mobile.png trong tmp/ai-studio-qa.

Live benchmark: `tools/benchmark_ai_slides_grounding.py`, fixtures tổng hợp trong tests/fixtures/ai_slides_grounding.json. Ba bộ Ôm/nước/bản đồ, mỗi bộ 5 slide; 15 proof hợp lệ, 32 bullet literal. Hai ca author ban đầu bị chặn an toàn vì quiz fields trên slide thường, sau siết schema chỉ chạy lại hai ca thất bại và đạt. Không lặng lẽ bỏ nội dung sai để đánh dấu thành công. Tổng 8 calls, kết quả tại tmp/ai-studio-qa/grounding-live. Notes chỉ gồm các trích đoạn đã chọn; phần hướng dẫn lớp học có tập câu cố định. Không đánh giá đây là bản giảng dạy đã được nghiệm thu.

Giới hạn: chứng minh đối chiếu văn bản, không chứng minh nguồn đúng, trích đoạn đủ ngữ cảnh hoặc phù hợp sư phạm. Phân đoạn dài có thể chia ở ranh giới từ; nguồn ngắn có thể lặp và cần giảm thời lượng/slide. Bài cũ hoặc chỉnh tay hiện cảnh báo. Chế độ Cân bằng vẫn cần giáo viên kiểm tra ý ngoài nguồn. Agent không điều khiển desktop.

Rà soát độc lập đợt strict và sửa: lọc span công thức trước tách dòng/chunk; lọc metadata bị bỏ; không tự xác nhận tiêu đề ngoài khung/attachment chỉnh tay khi AI edit; phương án quiz chỉ lấy từ nguồn slide và có quote evidence; dàn ý không lưu nguồn rỗng/đã bị loại, không nhận grounding_version do client tự đổi; preflight trước quota; diff có hoạt động lớp/đáp án đúng. Đã tái hiện các finding trọng yếu bằng test thất bại trước sửa. Test metadata/attachment bổ sung bảo vệ đường chạy. Sau sửa 84 backend (SQLite/PostgreSQL), 9 Node, 39 nhóm headless đạt; không dispatch re-review theo workflow một lượt sửa.

Deploy `f862799` và `3850f7c` đã live sau CI. Smoke trực tiếp provider trên preview chưa đạt do hai planner timeout; bản nháp/version giữ nguyên, dữ liệu tạm được dọn. Model/key/timeout so khớp với benchmark local, không in secrets. Ca mâu thuẫn local cũng timeout; một probe streaming có HTTP200, 177 keepalive nhưng 0 event/0 ký tự nội dung trong 85 giây. Ca Ôm đơn giản đã đạt trước đó cũng timeout khi đối chiếu lại. Chưa xác định nguyên nhân cụ thể; không coi tách prompt là đã sửa timeout. Artifact: preview-grounding-initial-timeout.json, preview-grounding-smoke-report.json, grounding-conflict-probe.json, grounding-stream-report.json. Những lỗi này phải được tính trong báo cáo pilot.
