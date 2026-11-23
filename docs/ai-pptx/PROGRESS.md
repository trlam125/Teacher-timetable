# Tiếp tục V4 — 23/11/2026

Nhánh: `codex/ai-slides-render-free`. Website chính giữ `main`; chỉ deploy service preview riêng. Không dùng desktop automation. Node chạy trong `codex-skill-env`, Python trong `.venv`.

Đợt tiếp theo theo F16/F26/F29/F32 và phần QA của plan V4:

1. Sửa dàn ý: tiêu đề, mục tiêu, thứ tự, loại slide, thời lượng và nguồn. Giữ ràng buộc tổng bài, version/owner; khi đã có nội dung phải xác nhận soạn lại. Có thể hoàn tác.
2. Đổi theme/mức hiệu ứng riêng, giữ nguyên manifest và dàn ý, không gọi AI. Native motion vẫn khóa theo gate Desktop hiện hành.
3. Sửa quiz/biểu đồ/học liệu bằng tay; cảnh báo tham chiếu trang sách chưa xác minh, số liệu minh họa và nội dung quá dài. Không coi cảnh báo heuristic là kiểm chứng kiến thức.
4. Tìm nội dung trong PDF ngay trên thiết bị, gồm tệp không có bookmark. Không gửi các trang chưa chọn tới server.
5. Kiểm thử API SQLite/PostgreSQL, exporter và browser headless; deploy và smoke trên preview riêng; đối chiếu website chính vẫn ở bản cũ.

Trạng thái: API/UX hoàn tất; 40 ca backend SQLite/PostgreSQL, 6 ca exporter Node, 14 nhóm browser hồi quy và 8 nhóm editor/search headless đều đạt. Đã xem ảnh dàn ý và rà soát độc lập delta. Đã deploy `5ac5b23` lên preview riêng; smoke provider thật và editor trên preview đạt, có PPTX tải xuống. Không thay đổi metadata DB; không cần migration mới. Website chính giữ main/bản cũ.

Đã quan sát kiểm thử mới thất bại khi chưa có endpoint/editor, sau đó đạt sau khi bổ sung. Một thao tác test ban đầu chọn theme khi phần thiết lập còn thu gọn; đã sửa script mở phần thiết lập trước khi chọn, không đổi hành vi sản phẩm để che lỗi test.

Quyết định: chỉnh dàn ý đã có nội dung yêu cầu `discard_content=true` rõ ràng, đồng thời giữ revision để hoàn tác. Không tự xóa slide đã soạn chỉ vì thay đổi theme.

Giới hạn kiểm chứng: agent không điều khiển Desktop. Có thể dùng kết quả kiểm thử thủ công do người dùng báo lại, ghi rõ nguồn bằng chứng và phần chưa được cung cấp.

Rà soát độc lập phát hiện cảnh báo tham chiếu sách chưa quét câu hỏi và phương án quiz. Đã viết subtest tái hiện (4 trường câu hỏi/phương án/hoạt động giáo viên/hoạt động học sinh đều thất bại), rồi mở rộng kiểm tra cho toàn bộ các trường này. Test browser mới đưa tham chiếu trang SGK vào câu hỏi để kiểm tra đường xuất PPTX. Sau sửa, 40 ca backend và cả 22 nhóm headless đạt. Không có finding khác được báo; giới hạn review là source/diff, không xác minh kiến thức AI.

Đã tạo ba bộ QA native motion khác môn bằng browser, kiểm tra XML/timing/targets: Ôm 19 slide, vòng tuần hoàn nước 10 slide, địa lí 10 slide (gồm feedback). File nằm trong `tmp/ai-studio-qa/native-desktop`. Người dùng xác nhận cả ba chạy đúng trên Desktop theo checklist; phiên bản Office/ảnh/video chưa được cung cấp. Đã bổ sung cờ môi trường bật native, default false, để bật riêng preview sau kiểm thử này. Bốn ca browser xác nhận tải native, tải cơ bản, reduced motion và engine-failure fallback đạt; backend tổng 42 ca đạt. Không thay đổi motion engine hoặc bố cục của ba fixture đã xác nhận.

Đã deploy `a923455` lên preview và bật cờ. Smoke từ nút UI trên preview xác nhận native 19 slide / 14 timing / 19 transitions; basic và reduced không có timing/transition. Không gọi AI cho smoke này; dữ liệu thử tạm đã dọn. Còn thiếu các phần V4 khác như nhận diện bài/chương tự động, giải quyết xung đột đa nguồn, mở rộng danh mục tài nguyên và đánh giá chất lượng nhiều bộ bài hoàn chỉnh; không đánh dấu toàn bộ V4 hoàn thành.

## Nhận diện nguồn và lựa chọn thông tin — 23/11/2026

Đã bổ sung đợt tiếp theo của F25/F26/F28/F29:

- Nhận diện từ tiêu đề rõ ràng trong đoạn đã chọn: môn, lớp, tên bài, thời lượng. Trả trích dẫn/tên nguồn/trang PDF; tự điền ô trống có một gợi ý, giữ thông tin đã nhập/khóa. Chế độ tài liệu có thể bắt đầu khi ba ô môn/lớp/tên bài còn trống. Nhận diện cần consent gửi đoạn đã chọn tới server, không gọi AI hoặc dùng quota.
- Tìm tiêu đề bài/chương trong lớp chữ PDF không có bookmark ngay trên thiết bị. Bỏ các mục lục rõ ràng, không suy ra trang PDF từ số trang in; giáo viên kiểm tra gợi ý và khoảng trang trước khi trích. Giới hạn 400 trang, tối đa 200 gợi ý. Không phải OCR hay tách bài hoàn hảo, nhất là bài chung trang.
- Cảnh báo các metadata khác nhau và một số biểu thức ký hiệu khác nhau. Hiển thị bằng chứng cho từng phương án; giáo viên chọn thông tin ưu tiên, không coi đây là xác minh kiến thức. Chặn plan/author/propose trước khi giữ quota nếu còn điểm chưa chọn. Giá trị trên biểu mẫu luôn được giữ; muốn đổi metadata phải sửa biểu mẫu.
- Quyết định lưu trong profile JSON và revision hiện có, kiểm tra lại bằng dấu vết nội dung/metadata; nguồn đổi thì quyết định cũ hết hiệu lực. Chọn lại sau khi có dàn ý/nội dung cần xác nhận soạn lại và giữ lịch sử hoàn tác. Không thêm bảng/cột hoặc chạy migration DB cho đợt này.
- Đã sửa lỗi đóng PDF khi đổi PDF sang Word/TXT được browser test mới phát hiện. Không đổi bộ máy native motion đã được người dùng xác nhận.

Kiểm thử local: 56 ca backend SQLite/PostgreSQL; 8 ca Node (6 exporter + 2 tiêu đề); 14 + 8 + 4 nhóm browser hồi quy; 7 nhóm nguồn mới. Đã xem ảnh rà soát nguồn trên mobile. Đã tái hiện lỗi thiếu API trước triển khai và các lỗi selector/đổi PDF bằng headless, sửa rồi chạy lại đạt.

Giới hạn còn lại: nhận diện nội dung mơ hồ/mục tiêu bằng AI nhỏ, phân tích mâu thuẫn ngữ nghĩa, tách chính xác nhiều bài cùng trang và kiểm tra tri thức không nằm trong thuật toán này. V4 còn các yêu cầu khác (luồng tự động liền mạch, danh mục học liệu phong phú hơn, đánh giá nhiều bộ bài hoàn chỉnh); chưa đánh dấu hoàn thành toàn plan.

CI đúng commit `7fc95c4` đạt, đã deploy lên preview riêng (`dep-dc1r1tcs728c73d6sbc0`, live). Smoke nguồn tổng hợp trên preview xác nhận nhận diện/bằng chứng, chặn plan trước provider, lưu lựa chọn và hiển thị lại trong giao diện. Provider thật tạo dàn ý 8,45 giây; sau khi agent đọc cảnh báo/dàn ý cho mục đích kiểm thử phần mềm, đã soạn 5 slide trong 43,26 giây và tải PPTX qua nút UI. Cả 5 slide có timing/transition, toàn bộ XML parse được. Tài khoản/bài/steps/revisions/usage thử được dọn; lượt AI vẫn tính quota site.

Đầu ra vẫn có ý ngoài nguồn ở chế độ strict: dụng cụ đo, ví dụ linh kiện ngoài phạm vi và bài tập SGK không có nguồn cụ thể. Phép thử này đạt về phần mềm/lựa chọn công thức ưu tiên, **chưa đạt nghiệm thu bám sát nguồn hoặc sư phạm**. Không dùng bộ bài smoke như bài đã được duyệt để dạy. Đây là việc cần giải quyết ở đợt chất lượng tiếp theo, không coi source review là bộ kiểm chứng kiến thức.

Website chính giữ commit `a5207d6` và deploy ID cũ; kiểm tra HTTP /login=200, /ai-studio=404. Không thay env hay DB của website chính. Server fixture và cụm PostgreSQL kiểm thử local đã dừng; không điều khiển Desktop.

## Bám nguồn bằng trích đoạn — 23/11/2026

Đã thay hợp đồng strict từ soạn văn bản tự do sang chọn trích đoạn. Planner chọn mã trích đoạn, loại hoạt động và thời lượng; máy chủ dựng tiêu đề/mục tiêu và nội dung từ đoạn nguồn. Author/edit chọn mã cho ý chính/ghi chú; mã lạ, mã ngoài nguồn của slide hoặc biểu thức đã bị loại trong lựa chọn nguồn bị chặn. Không có bước AI bổ sung hoặc tăng lượt gọi. Chế độ Cân bằng giữ khả năng soạn diễn đạt tự do.

Nội dung strict không tự thêm số liệu/chart, video, mô phỏng hoặc sơ đồ suy ra từ tên bài. Quiz là điền đúng nguyên văn trích đoạn; từ điền và phương án đều lấy trong nguồn. Hướng dẫn giáo viên/học sinh dùng tập câu hướng dẫn lớp học cố định, không thêm kiến thức. Giáo viên vẫn sửa tay/gắn học liệu được, nhưng slide đổi sẽ mất dấu đối chiếu và phải rà soát trước tải.

Mỗi slide có bằng chứng nguồn/trang/quote và dấu vết nội dung. Đề xuất AI chỉ giữ bằng chứng khi áp dụng đúng đề xuất đã lưu, đúng deck/version; không nhận bằng chứng tự gửi qua PATCH thủ công. Undo khôi phục đúng snapshot. Bài strict cũ hiện cảnh báo chưa đối chiếu; muốn soạn tiếp theo hợp đồng mới phải chủ động Lập lại dàn ý bám nguồn. Không tự xóa bài cũ. Không cần thêm bảng/cột hay migration DB.

Kiểm thử: 68 ca backend SQLite/PostgreSQL; 9 ca Node; 14 + 8 + 4 + 7 nhóm headless cũ, 6 nhóm mới cho nguồn/quiz/PPTX/manual edit/AI apply/undo/mobile. Đã xem ảnh bằng chứng nguồn trên mobile. Script QA mới ban đầu dùng sai phép đọc textarea và giả định 2 trang phản hồi quiz; đã sửa script theo giá trị và số phương án thực tế. Các lỗi source ref và sơ đồ tự thêm công thức có test tái hiện rồi đạt sau sửa.

Live benchmark nguồn tổng hợp 3 môn: 3 dàn ý, 3 bộ hoàn chỉnh × 5 slide; 15/15 slide có đối chiếu, 32 ý chính lấy nguyên văn. Có 2 lượt author ban đầu bị chặn do model điền trường quiz vào slide thường; đã siết schema null/empty cho nhóm không quiz và chạy lại riêng 2 ca đạt. Tổng 8 requests thật cho benchmark, không gọi model trả phí. Chưa coi là nghiệm thu sư phạm 20 bộ bài; title/hoạt động dạng khung và câu hỏi điền nguyên văn là chủ đích của chế độ trích đoạn. Diễn đạt linh hoạt dùng Cân bằng và cần giáo viên rà soát.

Đang chuẩn bị CI/deploy/smoke trên preview riêng; chỉ ghi nhận hoàn tất deploy sau khi quan sát live. V4 vẫn còn luồng tự động liền mạch, phân tích nguồn mơ hồ/ngữ nghĩa, học liệu mở rộng và đánh giá chất lượng rộng hơn.

### Rà soát cuối và tình trạng provider

CI của `f862799` và `3850f7c` đã đạt, cả hai đã lên preview riêng; main giữ nguyên. Hai lần planner trên preview (86,02 / 85,41 giây) timeout; lần sau xác nhận version/nội dung không đổi và lease được giải phóng. Tài khoản/dữ liệu tạm đã dọn sau mỗi lượt. Không tăng timeout hay đổi sang model trả phí.

Đã tách prompt strict khỏi chỉ dẫn soạn tự do (v7) và thêm test kiểm tra request; đây là làm rõ hợp đồng, **chưa có bằng chứng nó sửa timeout**. Cùng ca nguồn mâu thuẫn trên local vẫn timeout. Một probe streaming giới hạn 85 giây nhận HTTP200 và 177 keepalive, không nhận event/nội dung. Ca Ôm đơn giản từng đạt cũng timeout ở lần đối chiếu mới (85,02 giây). Chưa xác định nguyên nhân cụ thể phía provider, không kết luận lỗi riêng của Render hoặc chỉ do dữ liệu mâu thuẫn.

Một review độc lập toàn delta của đợt bám nguồn phát hiện các trường hợp biên. Đã sửa trong một lượt:

- Loại các span công thức bị bỏ **trước khi** tách dòng/chunk; test newline và ranh giới 280 ký tự tái hiện thất bại rồi đạt. Cũng loại tiêu đề metadata bị giáo viên bỏ, giữ phần nội dung khác của nguồn.
- Tiêu đề ngoài khung do giáo viên sửa và học liệu gắn tay không được tự nhận đã đối chiếu khi AI chọn lại nội dung. Giữ nguyên tiêu đề/học liệu và cảnh báo, không tự ghi đè. Test tiêu đề/attachment và API propose/apply đạt.
- Đáp án nhiễu chỉ lấy từ nguồn được chọn cho slide, có quote evidence cho từng phương án. Test trước sửa cho phép nguồn ngoài slide, sau sửa bị chặn.
- Dàn ý strict phải có trích đoạn khả dụng cho **mọi** slide trước khi lưu/reset, refresh mã trích đoạn khi đổi nguồn, giữ grounding_version do máy chủ đã lưu. Các slide/nguồn chưa hỗ trợ bị từ chối trước quota.
- Diff đề xuất hiển thị cả hoạt động giáo viên/học sinh và đáp án đúng; headless xác nhận hoạt động xuất hiện trước khi áp dụng.

Kết quả cuối sau sửa: 84 ca SQLite/PostgreSQL, 9 ca Node, 39 nhóm headless đạt. Không phát hiện test hồi quy còn thất bại. Chứng cứ trước đó vẫn là 3 bộ AI thật/15 slide/32 bullet khớp nguồn; tình trạng provider mới được ghi riêng, không xóa lỗi hoặc nhận là live AI đang ổn định. Không có finding quan trọng nào trong review này được bỏ qua; không yêu cầu reviewer lặp lại toàn bộ diff.

CI đúng commit `f5c6507` đạt và deploy `dep-dc1s7it9fdbs73bnqe6g` đã live trên preview riêng. Đã đưa **ba bộ tổng hợp do AI tạo ở benchmark trước đó** vào tài khoản giáo viên QA tạm, ở trạng thái dàn ý đã được rà soát. Cả 15 slide hiển thị đối chiếu nguồn hợp lệ trên API/UI; tải từng bộ qua nút thật được 5 slide/5 timing/5 transitions, XML parse được, không lỗi JavaScript và mobile không tràn ngang. Smoke này **không gọi AI**, không xác nhận provider đã phục hồi. Tài khoản/bài/revisions/device QA đã dọn. Artifact: preview-grounded-saved-export-report.json, preview-grounded-ohm/water/map.pptx, preview-grounded-evidence-mobile.png.

Website chính được Render xác nhận giữ nguyên deploy/commit `a5207d6`; không thay DB/env chính. Các bước sửa/trích đoạn đã được cập nhật trên preview, còn hạn chế availability của provider và các phần V4 khác vẫn mở. Không chạy thêm retry AI tự động hoặc tăng timeout để nhận thành công giả.

## Tiếp tục sau khi quyền mạng bị thu hồi — 23/11/2026 (chưa deploy)

Đang bổ sung luồng tạo liền mạch theo mục 5.3 V4. Nút chính Tạo PowerPoint bằng AI tự gọi plan rồi các nhóm author khi không có cảnh báo; nút Tạo dàn ý giữ đường xem trước. generation_mode lưu trong profile JSON, API client cũ mặc định outline để giữ hành vi. Bộ điều phối dừng tại consent/source review/outline warning/busy/legacy strict, không tự retry inference, không tự gọi AI khi reload và không tự tải tệp. Sau lỗi chỉ đọc lại deck một lần, giữ các nhóm đã lưu để người dùng tiếp tục.

Đã thêm test Node cho chuỗi 15 slide, chỉ dàn ý, cảnh báo/approval, consent/source/busy/legacy, lỗi giữa bài/resume và phản hồi không tăng tiến độ. Đã quan sát test fail khi module chưa tồn tại; sau triển khai 5/6 ca đạt, ca cuối chỉ sai hoa/thường trong assertion thông báo, đã sửa assertion nhưng chưa chạy lại bản cuối. Backend SQLite hiện 42/42 đạt, gồm lưu generation_mode và tương thích API cũ. Đã chuẩn bị 6 nhóm headless mới cho UI automatic/warning/resume và runner chặn mọi request trình duyệt ngoài loopback; CI được chuẩn bị chạy qua runner offline. Python syntax/diff được kiểm tra, chưa tính là browser QA đã đạt.

Giới hạn thực thi hiện tại: ứng dụng báo thu hồi quyền mạng ngay khi bắt đầu kiểm tra model thay thế. Lệnh Docker ngoài sandbox bị từ chối; Docker trong sandbox không truy cập được named pipe. Không đi đường vòng để gọi mạng, không cài Node trên Windows. Chưa build bundle mới, chưa chạy lại Node/headless, chưa push/deploy hoặc kiểm tra giá/model hiện hành. Tất cả thay đổi của đợt này là mã local chưa hoàn tất, preview vẫn ở bản triển khai trước.

Việc tiếp theo khi được phép: build/test offline qua codex-skill-env, chạy runner loopback và PostgreSQL QA, rà soát delta; sau khi quyền mạng được bật lại mới kiểm tra catalog zero-price, benchmark ứng viên có giới hạn lượt, CI và cập nhật preview riêng. Không chọn model dựa trên tên hoặc catalog cũ.

## Hoàn thiện luồng một nút trên local — 23/11/2026

Đã được phép dùng lại Docker cho build/test offline. Bản cuối đạt 15 ca Node (9 cũ + 6 bộ điều phối), build Vite thành công với dependencies hiện có, không npm install/download. Đã chép bundle mới vào dist. 86 ca backend SQLite/PostgreSQL đạt (DB QA riêng 127.0.0.1:18765), gồm generation_mode=automatic được lưu và client cũ mặc định outline. Không đổi schema DB.

Toàn bộ 6 bộ headless chạy qua run_studio_offline.py đạt 45 nhóm (14+8+4+7+6+6); request HTTP/HTTPS ngoài loopback bị chặn. Sáu nhóm mới xác nhận tạo 15 slide qua một thao tác và ba batch; không gọi AI khi reload; giữ đường chỉ tạo dàn ý; cảnh báo dừng automation; chỉ tiếp tục sau bấm duyệt; lỗi batch thứ hai giữ 5 slide và không tự retry; resume chỉ soạn hai nhóm còn lại; mâu thuẫn nguồn chặn trước mọi inference. Không lỗi JavaScript/tràn ngang, đã xem ảnh mobile. Provider là fixture local; **không suy ra model thật đã phục hồi**.

Luồng không tự tải PowerPoint khi vừa soạn xong: giáo viên xem/chỉnh rồi bấm tải, tránh tự phát hành nội dung chưa rà soát và hạn chế tải trình duyệt. Mở lại trang chỉ đọc trạng thái đã lưu; tiếp tục AI cần thao tác rõ ràng. Sau lỗi chỉ GET deck một lần, không retry inference, giữ version/idempotency mới cho từng bước. Engine có giới hạn số bước và dừng nếu tiến độ không tăng.

Artifact local: workflow-headless-report.json, automatic-generation-mobile.png và các báo cáo hồi quy trong tmp/ai-studio-qa. Đã rà soát delta tạo bài/schema/CI/test và git diff --check sạch. Chưa xác nhận deploy của đợt này, chưa thay model/timeout/API key và chưa kiểm tra lại catalog ngoài mạng.

Đã được phép đẩy nhánh và dùng mạng trở lại. CI của commit `f4a30c1` đạt; deploy `dep-dc243r142hec738uk56g` đã live trên **preview riêng**. Smoke UI/profile/persistence/export trên preview dùng fixture rõ ràng tại ranh giới plan/author, không gọi provider: một bấm gửi plan + ba nhóm author, version 1→2→3→4→5, bốn idempotency key riêng, lưu đủ 15 slide và reload không gọi thêm. Nút UI xuất 21 trang gồm 6 phản hồi quiz, 12 timing trees và 21 transitions; mọi XML parse, không lỗi JS/tràn ngang. Đã xem ảnh mobile và dọn user/deck/revisions/device QA. Assertion smoke ban đầu đếm nhầm quiz cũng phải có timing; đã đối chiếu exporter (quiz dùng hyperlink), sửa kỳ vọng script theo 12 trang nội dung động và chạy lại đạt, không đổi sản phẩm để che lỗi test.

Catalog OpenRouter công khai hiện có 12 model văn bản thỏa is_free (tất cả giá được công bố bằng 0). Một probe giới hạn trên liquid/lfm-3-1.7b:free trả HTTP429 trong 2,74 giây; đã dừng ngay, không probe tiếp Ling hoặc đổi primary/fallback. Đây chỉ là kiểm tra availability bước đầu, không phải nghiệm thu model mới. Thông tin provider cũ chưa được coi đã khắc phục. Không thay key/model/timeout/env trên preview trong đợt này.

Website chính giữ nguyên deploy/commit `a5207d6`; HTTP /login=200, /ai-studio=404. Không thay DB/env main. Server fixture và cụm PostgreSQL QA local đã dừng. Artifact bổ sung: preview-workflow-report.json (inference_calls=0, inference_boundary_fixtures=true), preview-automatic-workflow.pptx, preview-automatic-workflow-mobile.png, workflow-candidate-probe.json và free-model-catalog-current.json. V4 còn chất lượng/availability AI, nguồn mơ hồ, học liệu mở rộng và nghiệm thu sư phạm nhiều bộ bài.
