"""Second editorial pass of the saved V4 samples. AI review, never teacher approval.

These are authored corrections, not an automatic knowledge verifier. Raw provider
outputs stay unchanged. References were read by Codex on 2026-11-24; they support
the limited claims identified below, not Vietnamese curriculum alignment.
"""

SOURCES = {
    1: ('OpenStax Physics 19.1', 'https://openstax.org/books/physics/pages/19-1-ohms-law'),
    2: ('OpenStax University Physics 15.4', 'https://openstax.org/books/university-physics-volume-1/pages/15-4-pendulums'),
    3: ('OpenStax College Physics 11.2', 'https://openstax.org/books/college-physics-2e/pages/11-2-density'),
    4: ('OpenStax Physics 19.2', 'https://openstax.org/books/physics/pages/19-2-series-circuits'),
    5: ('OpenStax Prealgebra 9.3', 'https://openstax.org/books/prealgebra-2e/pages/9-3-use-properties-of-angles-triangles-and-the-pythagorean-theorem'),
    6: ('OpenStax Algebra and Trigonometry 2.5', 'https://openstax.org/books/algebra-and-trigonometry-2e/pages/2-5-quadratic-equations'),
    7: ('OpenStax Prealgebra 6.1', 'https://openstax.org/books/prealgebra-2e/pages/6-1-understand-percent'),
    8: ('OpenStax Introductory Statistics 2.5', 'https://openstax.org/books/introductory-statistics-2e/pages/2-5-measures-of-the-center-of-the-data'),
    9: ('OpenStax Biology 8.1', 'https://openstax.org/books/biology-2e/pages/8-1-overview-of-photosynthesis'),
    10: ('OpenStax Biology 4.3', 'https://openstax.org/books/biology-2e/pages/4-3-eukaryotic-cells'),
    11: ('OpenStax Biology 46.2', 'https://openstax.org/books/biology-2e/pages/46-2-energy-flow-through-ecosystems'),
    12: ('NOAA — The Hydrologic Cycle', 'https://www.noaa.gov/jetstream/atmosphere/hydro'),
    13: ('OpenStax Chemistry 1.2', 'https://openstax.org/books/chemistry-2e/pages/1-2-phases-and-classification-of-matter'),
    14: ('OpenStax Chemistry 14.2', 'https://openstax.org/books/chemistry-2e/pages/14-2-ph-and-poh'),
    15: ('NOAA — Latitude / Longitude', 'https://oceanservice.noaa.gov/facts/latitude.html', 'https://oceanservice.noaa.gov/facts/longitude.html'),
    16: ('NOAA — The North American Monsoon, p. 2', 'https://www.cpc.ncep.noaa.gov/products/outreach/Report-to-the-Nation-Monsoon_aug04.pdf'),
    17: ('OpenStax World History 6.3', 'https://openstax.org/books/world-history-volume-2/pages/6-3-capitalism-and-the-first-industrial-revolution'),
    18: ('Academy of American Poets — Poetry Glossary', 'https://poets.org/lesson-plan/poetry-glossary'),
    19: ('British Council — Present simple', 'https://learnenglish.britishcouncil.org/free-resources/grammar/english-grammar-reference/present-simple'),
    20: ('OpenStax Prealgebra 9.4', 'https://openstax.org/books/prealgebra-2e/pages/9-4-use-properties-of-rectangles-triangles-and-trapezoids'),
}

# Scores are Codex's ordinal editorial judgments, not measured accuracy or a
# qualified teacher's assessment. No passing threshold or acceptance is inferred.
# Order: knowledge / evidence / pedagogy / Vietnamese / resources / structure.
RAW_SCORES = {
    1: [28, 18, 5, 9, 5, 8], 2: [12, 8, 10, 5, 3, 8], 3: [18, 10, 12, 8, 5, 8],
    4: [18, 9, 12, 8, 2, 8], 5: [28, 18, 4, 9, 5, 8], 6: [14, 8, 10, 8, 5, 7],
    7: [23, 5, 12, 8, 5, 8], 8: [25, 12, 13, 9, 5, 8], 9: [19, 8, 10, 5, 5, 8],
    10: [14, 7, 10, 4, 5, 8], 11: [19, 9, 11, 5, 5, 8], 12: [27, 18, 5, 9, 5, 8],
    13: [20, 11, 12, 8, 5, 8], 14: [15, 8, 10, 8, 5, 8], 15: [27, 18, 5, 9, 5, 8],
    16: [13, 6, 9, 5, 3, 8], 17: [18, 5, 12, 7, 5, 8], 18: [13, 7, 10, 4, 5, 8],
    19: [23, 12, 14, 9, 5, 8], 20: [27, 13, 14, 7, 5, 8],
}
FINDINGS = {
    1: 'Đúng trích đoạn nhưng lặp; quiz điền từ chưa kiểm tra vận dụng công thức.',
    2: 'Sai dạng đồ thị; lẫn tiếng Hàn; mô tả đo thực nghiệm vượt chức năng mô phỏng.',
    3: 'Lẫn khối lượng với khối lượng riêng; suy tên vật liệu từ một giá trị.',
    4: 'Mô tả hai điện trở trong mô phỏng một điện trở; lệch phạm vi nối tiếp.',
    5: 'Nguồn đúng nhưng lặp; thiếu kiểm tra nhận diện cạnh huyền và vận dụng.',
    6: 'Điều kiện bài hình chữ nhật không khớp phương trình; thiếu phạm vi nghiệm thực.',
    7: 'Bịa trang SGK 45; ký hiệu đổi phần trăm cần làm rõ.',
    8: 'Thiếu điều kiện n > 0; cần giải thích ảnh hưởng giá trị rất lớn.',
    9: 'Lẫn tiếng Hàn; suy khả năng quang hợp từ màu lá; mở rộng thiếu nguồn.',
    10: 'Thuật ngữ vô nghĩa; lẫn thành tế bào với sức trương; khẳng định quá rộng.',
    11: 'Cố định truyền năng lượng 10%; chữ Trung còn trong hoạt động giáo viên.',
    12: 'Nguồn đúng nhưng lặp; câu điền từ ít giá trị đánh giá hiểu chu trình.',
    13: 'Hệ mở/kín và cân riêng chất rắn chưa phân biệt rõ.',
    14: 'Giới hạn pH 0–14 tuyệt đối; lẫn độ mạnh với nồng độ; hoạt động vượt nguồn.',
    15: 'Đúng khái niệm nhưng lặp; thiếu bài đọc tọa độ minh họa.',
    16: 'Gán mùa mưa/khô đồng loạt cho vùng; bản đồ địa hình không có dữ liệu gió.',
    17: 'Bịa số bài SGK; thêm mốc/điều kiện lịch sử chưa được nguồn ngắn hỗ trợ.',
    18: 'Quy tắc A+là+B và từ nối bị tuyệt đối hóa; chữ Trung trong tổng kết.',
    19: 'Quy tắc es theo đuôi o quá rộng; mẫu do/does cần giới hạn động từ thường.',
    20: 'Chữ Trung, thiếu đáp án bài tập và nói có hình trên slide khi chưa có.',
}


def amend(data, number):
    slides = data['manifest']['slides']

    def put(index, **fields):
        slide = slides[index - 1]
        slide.update(fields)
        slide['source_proof'] = None
        for field in ('title', 'kind'):
            if field in fields:
                data['blueprint']['slides'][index - 1][field] = fields[field]
        data['editorial_review']['changes'].append({'slide': index, 'reason': 'Second source/editorial review: ' + ', '.join(fields)})

    def objectives(*values):
        data['blueprint']['objectives'] = list(values)

    if number == 1:
        objectives('Dùng I = U/R cho điện trở thuần có R không đổi.', 'Tính và kiểm tra đơn vị của I trong ví dụ 6 V, 3 Ω.')
        put(1, title='Định luật Ôm: từ dự đoán đến tính toán', bullets=['Với điện trở thuần có R không đổi: I = U/R.', 'U đo bằng V; R bằng Ω; I bằng A.'], speaker_notes='Phạm vi: điện trở tuân theo định luật Ôm, điều kiện vật lí không đổi. Không khẳng định mọi linh kiện đều có R không đổi.', teacher_action='Hỏi: tăng U và giữ R thì I thay đổi thế nào?', student_action='Nêu dự đoán và giải thích bằng công thức.')
        put(2, title='Giữ cố định đại lượng nào?', bullets=['Giữ R không đổi: U tăng thì I tăng cùng tỉ lệ.', 'Giữ U không đổi: R tăng thì I giảm.', 'Mỗi lượt chỉ thay đổi một đại lượng.'], speaker_notes='Dùng quan hệ I = U/R. Không đồng thời thay U và R khi muốn xét ảnh hưởng riêng.', teacher_action='Ghi hai tình huống trên bảng.', student_action='Chỉ ra đại lượng cần giữ cố định.')
        put(3, title='Ví dụ: 6 V và 3 Ω', bullets=['Dữ kiện: U = 6 V, R = 3 Ω.', 'I = 6/3 = 2 A.', 'Kiểm tra: I × R = 2 × 3 = 6 V.'], speaker_notes='Cho học sinh tính trước khi xem đáp án; kiểm tra đơn vị A.', teacher_action='Che đáp án, mời học sinh tính.', student_action='Tính I và kiểm tra lại U.')
        put(4, title='Tự kiểm tra cách áp dụng', kind='quiz', bullets=['Giữ R = 3 Ω; tăng U từ 6 V lên 12 V.'], question='Cường độ dòng điện mới bằng bao nhiêu?', options=['1 A', '2 A', '4 A', '6 A'], correct_option=2, explanation='I = 12/3 = 4 A. R không đổi và U tăng gấp đôi nên I tăng gấp đôi.', speaker_notes='Ví dụ luyện tập tự tạo, không phải số đo.', teacher_action='Cho học sinh chọn rồi giải thích.', student_action='Chọn đáp án và trình bày phép chia.')
        put(5, title='Nhớ công thức và điều kiện', bullets=['Xác định U, R và đổi về đơn vị phù hợp.', 'Dùng I = U/R với R > 0 trong mô hình đã xét.', 'Kiểm tra kết quả bằng U = IR.'], speaker_notes='Câu ra về: R tăng gấp đôi khi U giữ nguyên thì I giảm một nửa.', teacher_action='Đặt câu ra về trong Notes.', student_action='Giải thích bằng công thức.')
    elif number == 2:
        objectives('Áp dụng T = 2π√(L/g) trong mô hình con lắc đơn góc nhỏ.', 'Giải thích T tỉ lệ với √L khi g không đổi.', 'Đọc giá trị mô hình tính; không nhận là phép đo kiểm chứng thực nghiệm.')
        put(2, speaker_notes='Trong mô hình con lắc đơn lí tưởng, góc nhỏ: T = 2π√(L/g). Khối lượng triệt tiêu khi lập phương trình chuyển động. T gần như không phụ thuộc biên độ trong xấp xỉ này; không áp dụng kết luận cho góc lớn.')
        put(4, bullets=['Chọn L trong khoảng 0,2–3 m, biên độ 1–10°.', 'Giữ g = 9,81 m/s²; đọc T được tính trên màn hình.', 'So sánh dự đoán khi L tăng bốn lần.'], teacher_action='Mở mô phỏng con lắc, thay L và đọc giá trị T tính sẵn.', student_action='Ghi giá trị hiển thị và so với dự đoán; không gọi là số đo thực nghiệm.')
        put(5, bullets=['Trong xấp xỉ góc nhỏ: T = 2π√(L/g).', 'Giữ g: L tăng bốn lần thì T tăng hai lần.', 'Phân biệt giá trị mô hình tính với kết quả đo.'], speaker_notes='Tổng kết ba ý. Bài tự tạo: so sánh T của L = 0,5 m và L = 2 m tại cùng g; tỉ số chu kỳ bằng 2.', teacher_action='Hỏi bài so sánh trong Notes.', student_action='Tóm tắt và giải thích tỉ số chu kỳ.')
    elif number == 3:
        objectives('Nêu ρ = m/V và điều kiện V > 0.', 'Tính, đổi đơn vị khối lượng riêng.', 'So sánh vật liệu trong điều kiện xác định, không suy tên chỉ từ ρ.')
        put(2, speaker_notes='ρ = m/V, V > 0. Đơn vị SI kg/m³; 1 g/cm³ = 1000 kg/m³. Nước tinh khiết ở khoảng 4 °C có khối lượng riêng xấp xỉ 1 g/cm³. Dữ liệu phụ thuộc điều kiện.')
        put(4, title='So sánh khối lượng riêng', bullets=['500 g/200 cm³ = 2,5 g/cm³.', '2700 kg/m³ = 2,7 g/cm³.', 'So sánh khối lượng chỉ khi cùng thể tích.', 'Một giá trị ρ chưa đủ xác định tên vật liệu.'], teacher_action='Cho đổi đơn vị rồi so sánh hai giá trị.', student_action='Giải thích điều kiện cùng thể tích.')
        put(5, bullets=['ρ = m/V với V > 0.', 'Đổi đơn vị trước khi tính và so sánh.', 'Nêu điều kiện của dữ liệu; không đoán tên vật liệu.'], speaker_notes='Ôn ví dụ 2 kg/0,001 m³ = 2000 kg/m³ = 2 g/cm³. Nêu rõ đây là bài tính minh họa.', teacher_action='Giao ví dụ trong Notes.', student_action='Tính và kiểm tra đơn vị.')
    elif number == 4:
        objectives('Nêu quan hệ I, U và R trong mạch điện trở nối tiếp lí tưởng.', 'Tính R tương đương và I trong ví dụ hai điện trở dương.')
        put(1, bullets=['Một nhánh nối tiếp: cùng một dòng điện qua các điện trở.', 'Dự đoán ảnh hưởng khi thêm điện trở nối tiếp.'], speaker_notes='Vẽ mạch điện trở lí tưởng trên bảng, bỏ qua điện trở dây và nguồn. Không lắp mạch vật lí hoặc hứa có mô phỏng hai điện trở.', teacher_action='Vẽ sơ đồ và nêu giả thiết.', student_action='Dự đoán, chưa cần thao tác thiết bị.')
        put(3, bullets=['R tương đương = R₁ + R₂.', 'Với R₁ > 0, R₂ > 0: tổng lớn hơn từng điện trở.', 'U = U₁ + U₂ và I như nhau qua hai điện trở.'])
        put(4, resource_id='ohm', bullets=['U = 12 V; R₁ = 2 Ω, R₂ = 3 Ω nối tiếp.', 'R tương đương = 5 Ω; I = 12/5 = 2,4 A.', 'U₁ = 4,8 V; U₂ = 7,2 V.'], speaker_notes='Bài tính minh họa, không phải số đo. Mô phỏng Ôm cục bộ chỉ có một điện trở: chọn U = 12 V, R = 5 Ω để kiểm tra dòng qua điện trở tương đương. Không dựng trực tiếp mạch R₁, R₂ trong mô phỏng.', teacher_action='Tính hai điện trở trên bảng, dùng mô phỏng Ôm cho điện trở tương đương.', student_action='Kiểm tra I và tổng U₁ + U₂.')
        put(5, teacher_action='Hỏi vì sao phải cộng R trước khi tính I.', student_action='Tóm tắt riêng mạch nối tiếp và giải thích ví dụ.')
    elif number == 5:
        objectives('Nhận diện cạnh huyền trong tam giác vuông.', 'Dùng c² = a² + b² khi a, b là hai cạnh góc vuông.', 'Tính cạnh huyền trong ví dụ 3–4–5.')
        put(1, title='Pythagore: bắt đầu từ góc vuông', bullets=['Chỉ xét tam giác vuông.', 'Cạnh huyền đối diện góc vuông.'], speaker_notes='Vẽ tam giác vuông ABC trên bảng, góc A vuông. BC là cạnh huyền.', teacher_action='Vẽ và đánh dấu góc vuông.', student_action='Chỉ cạnh huyền và hai cạnh góc vuông.')
        put(2, title='Đặt tên cạnh trước khi tính', bullets=['Gọi hai cạnh góc vuông là a, b; cạnh huyền là c.', 'Độ dài các cạnh cùng đơn vị.', 'c² = a² + b².'], speaker_notes='Không dùng tổng hai cạnh góc vuông để tính cạnh huyền.', teacher_action='Yêu cầu giải thích vai trò c.', student_action='Đọc công thức bằng lời.')
        put(3, title='Ví dụ hai cạnh 3 cm và 4 cm', bullets=['c² = 3² + 4² = 9 + 16 = 25.', 'Vì c là độ dài dương nên c = 5 cm.', 'Kiểm tra: 5² = 3² + 4².'], speaker_notes='Phân biệt c² = 25 cm² với c = 5 cm.', teacher_action='Cho tính từng bước.', student_action='Giải thích vì sao chọn căn dương.')
        put(4, title='Tự kiểm tra cạnh huyền', kind='quiz', bullets=['Tam giác vuông có hai cạnh góc vuông 6 cm và 8 cm.'], question='Cạnh huyền bằng bao nhiêu?', options=['14 cm', '10 cm', '2 cm', '100 cm'], correct_option=1, explanation='c² = 36 + 64 = 100 nên c = 10 cm.', speaker_notes='Bài luyện tập tự tạo. Đáp án 14 là lỗi cộng cạnh, 100 là quên lấy căn.', teacher_action='Cho chọn và giải thích lỗi từng phương án.', student_action='Tính rồi kiểm tra bằng bình phương.')
        put(5, title='Ba bước cần nhớ', bullets=['Xác định tam giác vuông và cạnh huyền.', 'Thay số đúng vị trí trong c² = a² + b².', 'Lấy căn dương và ghi đơn vị độ dài.'], speaker_notes='Yêu cầu học sinh chỉ lại cạnh huyền trên hình đã vẽ.', teacher_action='Đổi hướng hình trên bảng.', student_action='Nhận diện cạnh theo góc, không theo hướng hình.')
    elif number == 6:
        put(2, bullets=['ax² + bx + c = 0, a ≠ 0; xét nghiệm thực.', 'Δ = b² − 4ac.', 'Δ > 0: hai nghiệm thực; Δ = 0: nghiệm kép.', 'Δ < 0: không có nghiệm thực.'], speaker_notes='Với Δ ≥ 0, nghiệm x = (−b ± √Δ)/(2a). Với Δ < 0 không có nghiệm trong tập số thực. Ví dụ 2x² − 3x − 2 = 0 có nghiệm 2 và −0,5.')
        put(3, speaker_notes='Quy trình: đưa về dạng chuẩn, kiểm tra a ≠ 0, tính Δ, xét số nghiệm thực, dùng công thức khi Δ ≥ 0 rồi thế lại. Không lấy căn bậc hai thực của Δ âm.')
        put(5, bullets=['Xác định a ≠ 0 và Δ = b² − 4ac.', 'Kết luận số nghiệm trong tập số thực.', 'Thế lại nghiệm và kiểm tra điều kiện bài toán.'], speaker_notes='Bài tự tạo: x² − 4x + 4 = 0 có nghiệm kép 2; 3x² + 2x + 5 = 0 có Δ = −56, không có nghiệm thực; 2x² − 7x + 3 = 0 có nghiệm 3 và 0,5. Bài hai số dương có hiệu 3, tích 10 cho 5 và 2; nếu không yêu cầu dương còn cặp −2 và −5.', teacher_action='Giao các phương trình trong Notes và yêu cầu kiểm tra.', student_action='Giải trong tập số thực, ghi điều kiện.')
    elif number == 7:
        objectives('Đổi p% = p/100 sang phân số hoặc số thập phân.', 'Tính p% của một đại lượng gốc.', 'Giải thích đại lượng gốc trong ví dụ minh họa.')
        put(2, bullets=['p% = p/100.', '25% = 25/100 = 0,25.', 'Phần trăm là một cách biểu diễn tỉ số.'], speaker_notes='Đổi số thập phân r sang phần trăm: r = (100r)%. Ví dụ 0,25 = 25%. Không viết nhân thêm 100 vào 25% một lần nữa.')
        put(3, bullets=['p% của A bằng A × p/100.', '25% của 80 bằng 80 × 25/100 = 20.', 'Xác định đại lượng gốc A khi tính giá trị.'], speaker_notes='Bài tự tạo: 15% của 500 bằng 75. Khi diễn giải một mức tăng/giảm phần trăm, cần biết đại lượng gốc.')
        put(4, bullets=['50% = 0,5; 75% = 0,75.', '10% = 0,1; 125% = 1,25.', '30% của 200 bằng 60.'], speaker_notes='Cho học sinh đổi trước, sau đó kiểm tra bằng phép chia cho 100. Phần trăm có thể lớn hơn 100%.', teacher_action='Cho ba phép đổi và một bài tìm giá trị.', student_action='Nêu phép tính, không chỉ đọc đáp án.')
        put(5, speaker_notes='Câu ra về: tính 30% của 200 và giải thích đại lượng gốc. Đáp án 60. Bài tự tạo, không gán trang sách giáo khoa.')
    elif number == 8:
        put(4, speaker_notes='Bộ số minh họa 2, 4, 100 có trung bình 106/3 ≈ 35,3. Giá trị lớn có thể kéo trung bình lên; không suy mọi giá trị đều gần trung bình. Dùng dữ liệu giả lập, không yêu cầu công khai điểm cá nhân.', teacher_action='Viết bộ số giả lập 2, 4, 100.', student_action='Tính trung bình và nhận xét ảnh hưởng của 100.')
        put(5, bullets=['Với n > 0: trung bình cộng = tổng các giá trị/n.', 'Giữ cùng loại đại lượng và đơn vị khi tính.', 'Trung bình có thể bị ảnh hưởng bởi giá trị rất lớn hoặc rất nhỏ.'], speaker_notes='Bài tự tạo: 2, 4, 6 có trung bình 4; 5, 10, 15 có trung bình 10.', teacher_action='Giao hai bộ số trong Notes.', student_action='Nêu n và tính trung bình.')
    elif number == 9:
        objectives('Nêu đầu vào, sản phẩm và vai trò ánh sáng trong quang hợp ở cây xanh.', 'Giải thích vai trò của diệp lục ở mức khái quát.', 'Không suy tốc độ quang hợp chỉ từ màu lá.')
        put(1, bullets=['Cây xanh tạo chất hữu cơ nhờ năng lượng ánh sáng.', 'Quang hợp ở cây xanh sử dụng CO₂, nước và giải phóng O₂.', 'O₂ cần cho hô hấp hiếu khí của nhiều sinh vật.'], speaker_notes='Hỏi cây lấy chất để tạo chất hữu cơ từ đâu. Đây là bài khái quát về cây xanh, không bao quát mọi dạng quang hợp.', teacher_action='Nêu câu hỏi mở đầu.', student_action='Dự đoán đầu vào và sản phẩm.')
        put(2, bullets=['Đầu vào: CO₂ và nước.', 'Năng lượng: ánh sáng được hệ sắc tố hấp thụ.', 'Sản phẩm khái quát: carbohydrate và O₂.'], speaker_notes='Sơ đồ bằng lời không phải phương trình hóa học đã cân bằng. Có thể ghi phương trình tổng quát giản lược: 6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂, có ánh sáng và hệ sắc tố. Quá trình thực có nhiều bước; không nói glucose là sản phẩm trực tiếp duy nhất.', teacher_action='Vẽ sơ đồ đầu vào → quá trình → sản phẩm trên bảng.', student_action='Điền tên chất và nguồn năng lượng.')
        put(3, bullets=['Diệp lục tham gia hấp thụ năng lượng ánh sáng.', 'Ở cây xanh, quang hợp gắn với lục lạp.', 'Không kết luận khả năng quang hợp chỉ từ màu lá.'], speaker_notes='Lá có thể chứa nhiều sắc tố. Quan sát màu lá chưa đủ đo tốc độ quang hợp; cần phương pháp và điều kiện phù hợp.', teacher_action='Hỏi màu lá có đủ để đo tốc độ quang hợp không.', student_action='Nêu cần thêm dữ liệu và điều kiện.')
        put(4, bullets=['Quang hợp tạo nguồn chất hữu cơ cho nhiều chuỗi thức ăn.', 'Chuyển năng lượng ánh sáng thành năng lượng hóa học.', 'Góp phần trao đổi CO₂ và O₂ trong sinh quyển.'], speaker_notes='Chỉ nêu vai trò khái quát. Không suy một hoạt động trồng cây luôn bảo đảm giảm hiệu ứng nhà kính hay thay thế đo đạc.', teacher_action='Cho học sinh nối mỗi vai trò với đầu vào/sản phẩm.', student_action='Giải thích bằng sơ đồ đã vẽ.')
        put(5, bullets=['Nhớ CO₂, nước, ánh sáng và hệ sắc tố.', 'Phân biệt chất tham gia với nguồn năng lượng.', 'Sản phẩm khái quát: carbohydrate và O₂.'], speaker_notes='Câu ra về: ánh sáng có phải một chất tham gia không? Không; đây là nguồn năng lượng. Không giao thí nghiệm chưa có quy trình.', teacher_action='Đặt câu ra về trong Notes.', student_action='Trả lời và giải thích.')
    elif number == 10:
        put(2, bullets=['Tế bào thực vật điển hình có thành tế bào, màng sinh chất, tế bào chất và nhân.', 'Thành tế bào thực vật chủ yếu chứa cellulose.', 'Đây là mô hình khái quát; tế bào chuyên hóa có thể khác.'], speaker_notes='Vẽ sơ đồ đơn giản trên bảng. Thành nằm ngoài màng; nhân chứa thông tin di truyền. Không khẳng định mọi tế bào thực vật trưởng thành đều có đủ mọi cấu trúc.', teacher_action='Vẽ sơ đồ khái quát, phân biệt thành và màng.', student_action='Ghi tên, vị trí và chức năng chính.')
        put(4, teacher_action='Vẽ hai mô hình khái quát lên bảng để đối chiếu.', student_action='So sánh thành tế bào và giải thích vì sao không nên gán một hình dạng cho mọi tế bào.')
        put(5, bullets=['Phân biệt thành tế bào và màng sinh chất.', 'Tế bào chất chứa các bào quan; nhân chứa thông tin di truyền.', 'Thành tế bào là một điểm khác biệt với tế bào động vật.', 'Không phải mọi tế bào thực vật đều có lục lạp.'], speaker_notes='Câu ra về: thành tế bào và màng có cùng chức năng không? Không; thành hỗ trợ và định hình, màng kiểm soát trao đổi có chọn lọc.', teacher_action='Đặt câu so sánh thành và màng.', student_action='Nêu một chức năng mỗi cấu trúc.')
    elif number == 11:
        put(3, bullets=['Ví dụ minh họa: cỏ → châu chấu → ếch → rắn.', 'Mũi tên chỉ chiều truyền vật chất và năng lượng qua quan hệ ăn.', 'Trong ví dụ này cỏ là sinh vật sản xuất; các động vật là sinh vật tiêu thụ.'], speaker_notes='Đây là một chuỗi thức ăn minh họa, không phải số liệu điều tra. Không khẳng định mọi chuỗi đều bắt đầu bằng cỏ hoặc cây còn sống.', teacher_action='Vẽ chuỗi trên bảng, hỏi nghĩa mũi tên.', student_action='Đọc quan hệ ăn và vai trò từng mắt xích.')
        put(4, bullets=['Chỉ một phần năng lượng được chuyển lên bậc tiếp theo.', 'Sinh vật sử dụng năng lượng; một phần phân tán dưới dạng nhiệt.', 'Không coi 10% là tỉ lệ cố định cho mọi hệ sinh thái.'], speaker_notes='Thảo luận định tính; không cung cấp tháp số liệu hoặc hiệu suất giả làm dữ liệu thực.', teacher_action='Hỏi vì sao năng lượng không truyền nguyên vẹn qua mỗi bậc.', student_action='Giải thích định tính, không áp một tỉ lệ cố định.')
        put(5, teacher_action='Tóm tắt chuỗi và chiều mũi tên; đặt câu hỏi ngắn.', student_action='Nêu sinh vật sản xuất, tiêu thụ và giải thích mũi tên.')
    elif number == 12:
        objectives('Mô tả bốc hơi, ngưng tụ và giáng thủy.', 'Giải thích nước chuyển trạng thái/vị trí trong chu trình.')
        put(1, title='Nước đi đâu sau một cơn mưa?', bullets=['Theo dõi sự thay đổi vị trí và trạng thái của nước.', 'Nước được luân chuyển trong hệ Trái Đất – khí quyển.'], speaker_notes='Hỏi một vũng nước nhỏ dần thì nước có biến mất không. Không mô tả thí nghiệm đã thực hiện.', teacher_action='Nêu câu hỏi vũng nước.', student_action='Dự đoán vị trí nước chuyển tới.')
        put(2, title='Bốc hơi → ngưng tụ → mưa hoặc tuyết', bullets=['Bốc hơi: nước lỏng chuyển thành hơi nước.', 'Ngưng tụ: hơi nước tạo giọt nước nhỏ.', 'Mưa hoặc tuyết đưa nước trở lại bề mặt.'], speaker_notes='Đây là sơ đồ giản lược. Mây có giọt nước và/hoặc tinh thể băng; hơi nước dạng khí không phải đám mây nhìn thấy.', teacher_action='Vẽ ba mũi tên lên bảng.', student_action='Ghép mỗi mũi tên với tên quá trình.')
        put(3, title='Năng lượng giúp nước luân chuyển', bullets=['Mặt Trời là nguồn năng lượng quan trọng của chu trình.', 'Bốc hơi cần năng lượng.', 'Nước thay đổi trạng thái và vị trí; không tự mất đi.'], speaker_notes='Không nói chỉ Mặt Trời mới có thể cung cấp năng lượng cho mọi trường hợp bốc hơi.', teacher_action='Hỏi vì sao không nên gọi vũng nước khô là nước biến mất.', student_action='Giải thích bằng bốc hơi.')
        put(4, title='Phân biệt hai quá trình', question='Quá trình nào chuyển hơi nước thành các giọt nước nhỏ?', options=['Bốc hơi', 'Ngưng tụ', 'Dòng chảy', 'Thấm xuống đất'], correct_option=1, explanation='Ngưng tụ là chuyển từ hơi sang lỏng; bốc hơi có chiều ngược lại.', bullets=['Xét sự thay đổi trạng thái của nước.'], speaker_notes='Câu hỏi khái niệm tự tạo, không còn là bài nhớ nguyên văn.', teacher_action='Cho học sinh chọn và giải thích.', student_action='Nêu chiều thay đổi trạng thái.')
        put(5, title='Tóm tắt bằng ba mũi tên', bullets=['Gọi đúng tên bốc hơi, ngưng tụ, mưa/tuyết.', 'Nêu vai trò năng lượng và sự luân chuyển nước.', 'Sơ đồ giản lược không bao quát mọi nhánh chu trình.'], speaker_notes='Câu ra về: vũng nước nhỏ dần có chứng minh nước tự biến mất không? Không; cần theo dõi chuyển trạng thái và vị trí.', teacher_action='Cho vẽ lại sơ đồ trên giấy.', student_action='Giải thích sơ đồ trong một phút.')
    elif number == 13:
        put(5, bullets=['Tổng khối lượng trước và sau phản ứng được bảo toàn.', 'Hệ kín không trao đổi chất với môi trường, giúp theo dõi tổng khối lượng.', 'Trong hệ mở phải tính cả chất đi vào hoặc đi ra.'], speaker_notes='Không nói hệ kín là điều kiện làm định luật mới đúng. Bài tự tạo: 3 g A và 5 g B phản ứng hoàn toàn thành tổng 8 g sản phẩm, không thất thoát chất.', teacher_action='Hỏi sự khác nhau giữa cân phần rắn và cân toàn bộ hệ.', student_action='Giải thích phải tính cả khí.')
    elif number == 14:
        objectives('Phân loại dung dịch nước acid/trung tính/base theo pH tại 25 °C.', 'Biết khoảng 0–14 thường gặp không phải giới hạn tuyệt đối.', 'Dùng thẻ số minh họa, không nếm/chạm hóa chất.')
        put(2, teacher_action='Viết các thẻ số pH lên bảng; không tổ chức thí nghiệm.', student_action='Đọc thẻ và phân loại tại 25 °C.')
        put(3, teacher_action='Giải thích cách so sánh pH với 7 tại 25 °C.', student_action='Ghi điều kiện, không học thêm công thức ngoài phạm vi bài.')
        put(4, teacher_action='Cho phân loại bốn giá trị minh họa 2, 7, 9, 12.', student_action='Giải thích kết quả bằng so sánh với 7.')
    elif number == 15:
        objectives('Phân biệt vĩ độ với kinh độ.', 'Đọc tọa độ theo cách ghi độ và hướng trong bài.')
        put(1, title='Một điểm cần hai thông tin', bullets=['Vĩ độ: bắc hoặc nam so với xích đạo.', 'Kinh độ: đông hoặc tây so với kinh tuyến gốc.'], speaker_notes='Bài dùng cách ghi độ và chữ hướng. Quy ước dấu số cũng tồn tại, nhưng không trộn hai cách trong ví dụ.', teacher_action='Vẽ xích đạo và kinh tuyến gốc trên bảng.', student_action='Chỉ hai mốc tham chiếu.')
        put(2, title='Vĩ độ: bắc – nam', bullets=['Xích đạo có vĩ độ 0°.', 'Vĩ độ tăng tới 90° ở mỗi cực.', 'Ví dụ: 20°B chỉ phía bắc xích đạo.'], speaker_notes='20°B là tọa độ minh họa, không gán cho địa danh.', teacher_action='Ghi hai ví dụ bắc/nam.', student_action='Nêu phía so với xích đạo.')
        put(3, title='Kinh độ: đông – tây', bullets=['Kinh tuyến gốc có kinh độ 0°.', 'Kinh độ được ghi đông hoặc tây tới 180°.', 'Ví dụ: 105°Đ chỉ phía đông kinh tuyến gốc.'], speaker_notes='Không nói các kinh tuyến là đường song song. Bài không yêu cầu tính khoảng cách từ số độ.', teacher_action='Ghi một ví dụ đông và một ví dụ tây.', student_action='Nêu mốc tham chiếu.')
        put(4, title='Đọc một tọa độ minh họa', bullets=['Điểm P: 20°B, 105°Đ.', 'P ở phía bắc xích đạo và phía đông kinh tuyến gốc.', 'Chưa thể suy P là tên một thành phố từ ví dụ này.'], speaker_notes='Điểm P tự tạo để luyện đọc. Không trình bày như số đo vị trí thật.', teacher_action='Yêu cầu đọc cả hai thành phần.', student_action='Giải thích B và Đ.')
        put(5, title='Kiểm tra trước khi kết luận vị trí', bullets=['Xác định thành phần vĩ độ và kinh độ.', 'Đọc số độ kèm hướng theo quy ước đã dùng.', 'Phân biệt ví dụ minh họa với dữ liệu địa danh thật.'], speaker_notes='Câu ra về: 15°N, 70°T nghĩa là gì? Phía nam xích đạo và phía tây kinh tuyến gốc.', teacher_action='Đặt câu ra về trong Notes.', student_action='Giải thích hai mốc tham chiếu.')
    elif number == 16:
        objectives('Nêu gió mùa đổi hướng theo mùa.', 'Giải thích vai trò góp phần của chênh lệch nhiệt lục địa – đại dương.', 'Nhận biết cần dữ liệu địa phương để kết luận mùa mưa/khô.')
        put(1, bullets=['Gió mùa đổi hướng theo mùa.', 'Chênh lệch nhiệt lục địa – đại dương góp phần hình thành hoàn lưu.', 'Không gán cùng mùa mưa cho mọi địa phương.'])
        put(3, title='Vì sao cần xem từng địa phương?', resource_id=None, bullets=['Cơ chế chung chưa đủ mô tả mưa từng nơi.', 'Vị trí, địa hình và thời kỳ ảnh hưởng kết luận.', 'Cần dữ liệu khí tượng có nguồn khi so sánh các vùng.'], speaker_notes='Bài không đính kèm bản đồ gió hoặc bảng mưa. Bản đồ địa hình cục bộ không được dùng thay dữ liệu khí tượng.', teacher_action='Hỏi cần dữ liệu nào để xác định mùa mưa.', student_action='Nêu lượng mưa theo tháng, địa điểm và thời kỳ quan sát.')
        put(4, teacher_action='Đặt tình huống lập kế hoạch mùa vụ cần thêm thông tin nào.', student_action='Liệt kê dữ liệu cần thu thập, không tự điền số liệu chưa có.')
    elif number == 17:
        objectives('Nêu bối cảnh khái quát Anh thế kỷ XVIII.', 'Giải thích vai trò nhà máy và động lực hơi nước.', 'Phân biệt thay đổi sản xuất với tác động xã hội trong các ý đã học.')
        put(2, bullets=['Anh là nơi khởi đầu Cách mạng công nghiệp vào thế kỷ XVIII.', 'Sản xuất bằng máy phát triển trong các nhà máy.', 'Dịch chuyển lao động và tổ chức sản xuất góp phần vào quá trình.'], speaker_notes='Trình bày khái quát theo nguồn tham khảo bổ sung OpenStax. Không gán số bài SGK, không dùng một danh sách nguyên nhân đơn lẻ như lời giải đầy đủ.', teacher_action='Phân biệt điều kiện với phát minh và hệ quả.', student_action='Sắp các ý vào ba nhóm.')
        put(3, bullets=['Máy hơi nước được cải tiến và sử dụng trong sản xuất.', 'Nhà máy tập trung máy móc và lao động.', 'Động lực hơi nước mở rộng sang giao thông.'], speaker_notes='Máy hơi nước không phải phát minh duy nhất và không lập tức thay hết sức nước, gió hay sức người. Không quy toàn bộ quá trình cho một người hoặc một năm.', teacher_action='Vẽ chuỗi khái quát nhà máy – máy móc – giao thông.', student_action='Giải thích quan hệ, không học một mốc bịa.')
        put(4, bullets=['Năng suất và lượng hàng hóa tăng.', 'Tổ chức lao động và đời sống đô thị thay đổi.', 'Nhiều công nhân phải làm việc dài giờ, điều kiện khó khăn.'], speaker_notes='So sánh thành tựu sản xuất với chi phí xã hội của quá trình. Không yêu cầu chốt lợi ích hay thiệt hại tuyệt đối cho mọi nhóm người.', teacher_action='Yêu cầu nêu một thay đổi sản xuất và một vấn đề lao động.', student_action='Lập luận từ thông tin trong bài.')
        put(5, bullets=['Phân biệt điều kiện, quá trình và hệ quả.', 'Nhớ phạm vi: Anh, thế kỷ XVIII và sự phát triển nhà máy.', 'Đánh giá thay đổi kinh tế cùng tác động xã hội.'], speaker_notes='Các nhận định bổ sung dựa trên nguồn tham khảo ghi trong Notes, không phải trích nguyên văn nguồn qa-facts hay xác nhận SGK lớp 8.', teacher_action='Cho lập sơ đồ ba nhánh.', student_action='Xếp lại các ý và giải thích căn cứ.')
    elif number == 18:
        objectives('Phân biệt hai biện pháp qua nghĩa và ngữ cảnh.', 'Giải thích nét tương đồng trong ví dụ tự tạo.', 'Viết câu có hình ảnh và giải thích cách diễn đạt.')
        put(3, bullets=['Ẩn dụ diễn đạt sự vật bằng tên/cách mô tả khác dựa trên tương đồng.', 'Ví dụ tự tạo: Một giọng nói ấm áp vang lên.', 'Giải thích sự chuyển nghĩa trong ngữ cảnh.'], speaker_notes='Trong ví dụ, ấm áp được chuyển từ cảm giác nhiệt sang ấn tượng dễ chịu của giọng nói. Đây là cách diễn giải biên tập, không phải đáp án chính thức của SGK. Không định nghĩa bằng khuôn A + là + B.', teacher_action='Hỏi vì sao ấm áp ở đây không phải số đo nhiệt độ.', student_action='Giải thích nghĩa trong câu, không chỉ tìm từ nối.')
        put(4, teacher_action='Đối chiếu nhanh như gió với giọng nói ấm áp.', student_action='Giải thích tương đồng và sự chuyển nghĩa; từ nối chỉ là gợi ý.')
        put(5, bullets=['Xét nghĩa, ngữ cảnh và nét tương đồng.', 'Từ nối giúp nhận diện một số cách so sánh.', 'Không phân loại mọi câu chỉ bằng có/không có từ là hoặc như.', 'Viết hai câu tự tạo và giải thích hình ảnh.'], speaker_notes='Hoạt động cuối: viết một câu so sánh và một câu có chuyển nghĩa theo tương đồng, giải thích cách hiểu. Không gán các ví dụ tự tạo cho tác giả hoặc SGK.', teacher_action='Tóm tắt kiến thức và giao hai câu tự tạo.', student_action='Viết câu và giải thích căn cứ phân loại.')
    elif number == 19:
        put(2, bullets=['Động từ thường: I/you/we/they + dạng cơ bản.', 'He/she/it: thường thêm s; watch → watches.', 'Phụ âm + y: study → studies; play → plays.', 'Một số dạng riêng: go → goes; have → has.'], speaker_notes='Phạm vi động từ thường. Không nói mọi động từ đuôi o đều thêm es; ví dụ video → videos. Với be: I am, you/we/they are, he/she/it is.', teacher_action='Cho đổi work, watch, study, play, have theo she.', student_action='Viết works, watches, studies, plays, has.')
        put(3, bullets=['Động từ thường: S + do/does not + dạng cơ bản.', 'Câu hỏi Yes/No: Do/Does + S + dạng cơ bản?', 'He/she/it dùng does; các nhóm còn lại dùng do.', 'Be dùng am/is/are theo mẫu riêng.'])
        put(5, bullets=['Hiện tại đơn diễn tả thói quen và sự thật chung.', 'Phân biệt động từ thường với be.', 'Sau do/does dùng dạng cơ bản của động từ thường.', 'Bài tự tạo: đổi She goes thành phủ định và câu hỏi.'], speaker_notes='Đáp án: She does not go. Does she go? Không áp khuôn do/does cho be; câu hỏi chủ ngữ who có mẫu khác, nằm ngoài bài này.', teacher_action='Cho hai phép chuyển câu trong Notes.', student_action='Giải thích vì sao go không còn es.')
    elif number == 20:
        put(1, speaker_notes='Vẽ hình chữ nhật trên bảng, đánh dấu bốn góc vuông và hai cặp cạnh đối bằng nhau. Không nói có hình ảnh nhúng sẵn nếu slide chỉ có chữ.', student_action='Quan sát hình giáo viên vẽ trên bảng.')
        put(4, speaker_notes='Bài tự tạo 1: dài 7 cm, rộng 5 cm, chu vi (7 + 5) × 2 = 24 cm. Bài 2: dài 12 m, rộng 8 m, chu vi (12 + 8) × 2 = 40 m. Kiểm tra bằng cộng bốn cạnh. Chu vi là độ dài đường bao; diện tích là độ lớn phần mặt phẳng, đơn vị bình phương.')
        put(5, speaker_notes='Tóm tắt kiến thức: cùng đơn vị đo, cộng dài với rộng rồi nhân hai. Bài tự tạo: dài 6 cm, rộng 4 cm, chu vi 20 cm. Không giao một trang SGK chưa xác định.')

    # Bind references to the authored copy and remove inherited literal proofs:
    # even unchanged facts now occur in an edited, expanded teaching sequence.
    reference = SOURCES[number]
    data['editorial_review']['original_outline_warnings'] = data['blueprint']['warnings']
    data['blueprint']['warnings'] = [
        'Bộ mẫu QA có 5 slide; không được coi là giáo án đầy đủ cho thời lượng nhập.',
        'Nguồn đầu vào là dữ kiện tổng hợp. Bản biên tập có tham khảo bổ sung trong Notes, chưa xác nhận phù hợp SGK/chương trình.',
        'Rà soát bởi Codex AI; không phải phê duyệt chuyên môn của giáo viên hoặc kiểm tra hiển thị PowerPoint Desktop.',
    ]
    data['editorial_review']['changes'].append({'slide': None, 'reason': 'Replace inherited outline warnings, including unsupported textbook/curriculum and simulation instructions; preserve originals only in audit metadata.'})
    for slide in slides:
        slide['source_proof'] = None
        slide['speaker_notes'] += '\n\nTham khảo bổ sung do Codex đối chiếu 24/11/2026: ' + reference[0] + '\n' + '\n'.join(reference[1:])
    data['editorial_review'].update(
        reviewer_kind='ai', source_accessed_by_ai=True, teacher_approved=False,
        office_tested_by_agent=False, second_pass='2026-11-24',
        scope='20 miniature QA lessons, 5 content slides each; not complete curriculum or raw-model qualification',
        finding=FINDINGS[number], reference={'title': reference[0], 'urls': list(reference[1:])},
    )
