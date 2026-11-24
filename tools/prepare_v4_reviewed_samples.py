"""Editorial QA samples, kept separate from raw model benchmarks. Not teacher approval."""
from copy import deepcopy
import json
from pathlib import Path
from ai_slides_review.editorial_v4 import amend

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tmp/ai-studio-qa/v4-benchmark'
TARGET = ROOT / 'tmp/ai-studio-qa/v4-reviewed'
TARGET.mkdir(exist_ok=True)


def update(data, index, reason, *, bullets=None, notes=None, title=None):
    slide = data['manifest']['slides'][index - 1]
    if bullets is not None: slide['bullets'] = bullets
    if notes is not None: slide['speaker_notes'] = notes
    if title is not None:
        slide['title'] = title
        data['blueprint']['slides'][index - 1]['title'] = title
    slide['source_proof'] = None
    data['editorial_review']['changes'].append({'slide': index, 'reason': reason})


def replace(data, before, after):
    for slide in data['manifest']['slides']:
        for key in ('title', 'speaker_notes', 'teacher_action', 'student_action', 'question', 'explanation'):
            if before in slide.get(key, ''):
                slide[key] = slide[key].replace(before, after)
                slide['source_proof'] = None
        slide['bullets'] = [value.replace(before, after) for value in slide['bullets']]


for number in range(1, 21):
    data = deepcopy(json.loads((SOURCE / f'case-{number:02d}-deck.json').read_text(encoding='utf-8')))
    data['editorial_review'] = {'reviewer': 'Codex editorial QA, not an independent teacher', 'teacher_approved': False,
                                'raw_benchmark_preserved': True, 'normalization': 'Unused quiz fields cleared on non-quiz layouts; raw originals retained separately.', 'changes': []}
    for slide in data['manifest']['slides']:
        if slide['kind'] != 'quiz':
            slide.update(question='', options=[], correct_option=None, explanation='')
    if number == 2:
        replace(data, 'góc lặp', 'góc lệch')
        replace(data, 'hồi복', 'kéo về')
        update(data, 3, 'Correct the square-root graph and separate computed examples from measurements.',
               bullets=['T tỉ lệ thuận với √L khi g không đổi.', 'L tăng 4 lần thì T tăng 2 lần.', 'T theo L là đồ thị hàm căn bậc hai; T theo √L là đường thẳng qua gốc.'],
               notes='T = (2π/√g)√L. Phân biệt rõ trục ngang L và √L; không gọi đồ thị T(L) là parabol. Ví dụ tính với cùng g: khi L tăng bốn lần, chu kỳ tăng hai lần. Các giá trị tính bằng công thức là minh họa, không phải số liệu đo thực nghiệm.')
        update(data, 4, 'Only describe controls available in the pendulum demo.',
               notes='Mở mô phỏng con lắc; thay đổi L trong khoảng 0,2–3 m và biên độ 1–10°. Giá trị T hiển thị được tính theo mô hình góc nhỏ với g = 9,81 m/s². So sánh T khi thay L; đây là mô phỏng tính toán, không phải thiết bị đo thời gian thực nghiệm. Không suy ra có cảm biến hoặc đồng hồ đo tích hợp.')
    elif number == 3:
        update(data, 1, 'Density depends on conditions and is not a unique material identifier.',
               bullets=['Khối lượng riêng là khối lượng của một đơn vị thể tích.', 'ρ = m/V, với V > 0 và đơn vị phù hợp.', 'Ở điều kiện xác định, dùng ρ để mô tả và so sánh vật liệu.'],
               notes='Nêu công thức ρ = m/V và đơn vị SI kg/m³. Khi so sánh vật liệu cần xét điều kiện nhiệt độ, trạng thái và thành phần. Một giá trị khối lượng riêng riêng lẻ không đủ xác định chắc chắn tên vật liệu.')
        update(data, 3, 'Do not guess a material from density alone.', notes='Từ m = 2 kg, V = 0,001 m³ suy ra ρ = 2000 kg/m³ = 2 g/cm³. Kiểm tra đơn vị trước khi tính. Không khẳng định tên vật liệu từ số này khi chưa có bảng tra và điều kiện phù hợp.')
        update(data, 4, 'Mass comparison requires equal volumes.', notes='Ví dụ minh họa: 500 g/200 cm³ = 2,5 g/cm³; 2700 kg/m³ = 2,7 g/cm³. Khi nói mẫu có khối lượng lớn hơn mẫu nước bao nhiêu lần, phải so sánh cùng thể tích. Không đồng nhất khối lượng và khối lượng riêng.')
    elif number == 4:
        update(data, 2, 'Do not claim the single-resistor PhET sim exposes a series circuit.', notes='Mạch nối tiếp chỉ có một nhánh; I như nhau qua các điện trở, U toàn mạch là tổng các hiệu điện thế thành phần. Vẽ sơ đồ trên bảng. Học liệu PhET định luật Ôm chỉ minh họa quan hệ giữa một U, một R và I; không trực tiếp dựng hai điện trở nối tiếp.')
        update(data, 3, 'Use equivalent resistance with the available simulation.', notes='Với hai điện trở nối tiếp: U = IR₁ + IR₂ nên R tương đương = R₁ + R₂. Có thể tự tính R tương đương rồi dùng giá trị này trong mô phỏng một điện trở. Không mô tả mô phỏng có hai thanh điều khiển điện trở thành phần.')
        update(data, 4, 'Correct the actual PhET settings.', notes='Ví dụ minh họa: U = 12 V, R₁ = 2 Ω và R₂ = 3 Ω nối tiếp cho R tương đương = 5 Ω, I = 2,4 A; U₁ = 4,8 V, U₂ = 7,2 V. Trong PhET định luật Ôm, nhập U = 12 V và R = 5 Ω để so sánh I; các điện trở thành phần được tính riêng trên bảng.')
        update(data, 5, 'Keep the summary in the selected series-circuit scope.', title='Ôn tập mạch điện trở nối tiếp', bullets=['I như nhau qua các điện trở trong một nhánh nối tiếp.', 'R tương đương bằng tổng các điện trở thành phần.', 'Tính R trước, sau đó dùng I = U/R và kiểm tra đơn vị.'], notes='Tóm tắt quy trình với ví dụ đã cho. Bài tập bổ sung do giáo viên tự chọn hoặc tự tạo; không gán số trang SGK khi chưa có nguồn.')
    elif number == 6:
        update(data, 1, 'Use the same rectangle problem as the worked quadratic.', notes='Ví dụ tự tạo: hai cạnh kề của hình chữ nhật có tổng 5 m và diện tích 6 m². Gọi một cạnh là x, cạnh còn lại là 5 − x, với 0 < x < 5. Ta có x(5 − x) = 6, tương đương x² − 5x + 6 = 0. Cuối bài kiểm tra hai kích thước 2 m và 3 m; không dùng điều kiện hiệu hai cạnh bằng 5 m.')
        replace(data, ' / 2a', ' / (2a)')
        replace(data, '/2a', '/(2a)')
        update(data, 4, 'Correct the geometry interpretation and keep both roots checked.', notes='Xác định a = 1, b = −5, c = 6; Δ = 1. Hai nghiệm là 2 và 3, kiểm tra bằng phép thế. Trong bài hình chữ nhật mở đầu, hai cạnh là 2 m và 3 m: tổng 5 m, diện tích 6 m². Bài tập khác cần giải và kiểm tra riêng, không gán nghiệm của ví dụ này cho bài khác.')
    elif number == 7:
        update(data, 5, 'Remove an invented SGK page reference.', bullets=['Phần trăm là cách biểu diễn tỉ số với 100.', 'Đổi 25% = 25/100 = 0,25.', '25% của 80 bằng 20; luôn xác định đại lượng gốc.', 'Bài tập tự tạo: tính 30% của 200 và giải thích cách làm.'], notes='Ôn lại khái niệm, chuyển đổi và cách tìm giá trị phần trăm. Bài tập tự tạo có đáp án 30% × 200 = 60. Nếu dùng bài SGK, giáo viên bổ sung đúng tài liệu và số trang trước; không giữ trang 45 do AI tự nêu.')
    elif number == 8:
        replace(data, 'Áp dụng cho bất kỳ tập hợp số nào.', 'Áp dụng cho một tập hợp hữu hạn không rỗng.')
        replace(data, 'công thức đúng cho mọi tập hợp số thực', 'công thức áp dụng cho một tập hợp hữu hạn không rỗng, n > 0')
        data['editorial_review']['changes'].append({'slide': 2, 'reason': 'Make the n > 0 condition explicit.'})
    elif number == 9:
        replace(data, '토론', 'thảo luận')
        replace(data, 'canh tác kính nhà', 'canh tác nhà kính')
        data['editorial_review']['changes'].append({'slide': 2, 'reason': 'Remove unrelated Korean text and correct Vietnamese wording.'})
    elif number == 10:
        update(data, 2, 'Remove a fabricated biology term.', notes='Thành tế bào thực vật chủ yếu chứa cellulose, một polysaccharide. Màng sinh chất kiểm soát trao đổi chất, tế bào chất chứa các bào quan và là nơi diễn ra nhiều phản ứng, nhân chứa thông tin di truyền. Không dùng cụm từ vô nghĩa do AI sinh ra; giáo viên đối chiếu sơ đồ gốc trước khi dạy.')
        update(data, 3, 'Separate cell-wall support from turgor pressure.', bullets=['Thành tế bào bảo vệ, định hình và giúp tế bào chịu áp lực do nước.', 'Màng sinh chất kiểm soát trao đổi chất có chọn lọc.', 'Tế bào chất chứa các bào quan, diễn ra nhiều hoạt động chuyển hóa.', 'Nhân chứa thông tin di truyền và điều khiển nhiều hoạt động của tế bào.'], notes='Dùng mức mô tả phù hợp lớp học. Không đồng nhất sức trương nước với thành tế bào. Không suy ra mọi hoạt động hô hấp hoặc tổng hợp protein diễn ra trong phần dịch tế bào chất; cần phân biệt các bào quan khi giải thích sâu hơn.')
        update(data, 4, 'Do not invent curriculum limits or universal cell shapes.', bullets=['Đối chiếu các cấu tạo điển hình đã nêu trong nguồn.', 'Tế bào thực vật có thành tế bào; tế bào động vật không có thành tế bào.', 'Hình dạng tế bào khác nhau theo chức năng.', 'Không phải mọi tế bào thực vật đều có lục lạp.'], notes='Dùng sơ đồ đã được kiểm tra để so sánh. Không khẳng định toàn bộ tế bào thực vật đều hình chữ nhật hoặc suy đoán chương trình lớp học chỉ cho phép một đặc điểm. Phạm vi mở rộng cần tài liệu phù hợp.')
    elif number == 11:
        replace(data, 'chau chấu', 'châu chấu')
        update(data, 4, 'Remove an unsupported universal 10-percent transfer claim.', bullets=['Cỏ → châu chấu → ếch → rắn là ví dụ minh họa trong nguồn.', 'Mũi tên đi từ thức ăn tới sinh vật ăn nó.', 'Chỉ một phần năng lượng được truyền sang bậc sau.', 'Tỷ lệ truyền thay đổi; nguồn này không cung cấp số liệu để tính.'], notes='Phân tích quan hệ ăn – bị ăn và chiều chuyển năng lượng. Không gán tỷ lệ cố định cho mọi chuỗi thức ăn. Nếu muốn làm bài số liệu, cần tài liệu hoặc dữ liệu minh họa được ghi rõ nguồn và điều kiện.')
        update(data, 5, 'Keep the summary qualitative.', bullets=['Chuỗi thức ăn thể hiện quan hệ dinh dưỡng.', 'Mũi tên từ thức ăn tới sinh vật ăn nó.', 'Phân biệt sinh vật sản xuất và các sinh vật tiêu thụ trong ví dụ.', 'Không suy ra tỷ lệ truyền năng lượng cố định từ sơ đồ này.'], notes='Ôn ví dụ trong nguồn và yêu cầu học sinh giải thích chiều mũi tên. Thảo luận sự phụ thuộc giữa các loài; không coi quy tắc phần trăm là số đo của ví dụ đã cho.')
    elif number == 13:
        replace(data, 'Hệ kín là điều kiện bắt buộc để định luật đúng.', 'Xét hệ kín để theo dõi khối lượng mà không thất thoát chất ra môi trường.')
        update(data, 4, 'Make the illustrative mass accounting unambiguous.', bullets=['Ví dụ tự tạo: 10 g chất phản ứng tạo 8 g chất rắn và một lượng khí.', 'Trong hệ kín, giữ và tính cả khí trong tổng sản phẩm.', 'Khối lượng khí: 10 − 8 = 2 g.', 'Trong hệ mở, cân riêng phần rắn có thể cho số đo giảm vì khí đã rời hệ.'], notes='Ghi rõ ví dụ minh họa, không mô tả là kết quả thực nghiệm. Bảo toàn khối lượng không ngừng đúng khi mở hệ; khi tính tổng phải xét cả lượng chất đi vào/ra. Bài này dùng hệ kín để việc theo dõi tổng khối lượng rõ ràng.')
    elif number == 14:
        update(data, 2, 'Correct universal-indicator interpretation and avoid inventing a lab procedure.', bullets=['Đối chiếu các giá trị pH minh họa với mốc trung tính.', 'Ở 25 °C: pH < 7 acid; pH = 7 trung tính; pH > 7 base.', 'Giấy chỉ thị cần đọc theo bảng màu đi kèm.', 'Không nếm hoặc chạm hóa chất để phân loại.'], notes='Dùng thẻ giá trị pH hoặc hình bảng màu được giáo viên kiểm tra. Không nói giấy chỉ thị phổ quát không đổi màu là trung tính. Thực hành hóa chất chỉ theo quy trình đã được nhà trường/giáo viên kiểm tra.')
        update(data, 3, 'Remove an absolute 0–14 bound and the strength/concentration conflation.', bullets=['pH dùng để mô tả tính acid/base của dung dịch.', 'Giữ điều kiện 25 °C khi dùng mốc trung tính pH = 7.', 'Khoảng 0–14 thường gặp không phải giới hạn tuyệt đối cho mọi dung dịch.', 'Không đồng nhất pH thấp với kết luận về độ mạnh của bản thân acid.'], notes='Tập trung vào phạm vi nguồn: phân loại acid, trung tính, base tại 25 °C. Không mở rộng công thức logarit hoặc ví dụ sinh học khi chưa có tài liệu phù hợp. pH còn phụ thuộc điều kiện và thành phần dung dịch; giáo viên kiểm tra khi cần giải thích sâu hơn.')
        update(data, 4, 'Use explicitly synthetic classification examples instead of uncited biological values.', bullets=['Ví dụ minh họa ở 25 °C: pH = 2; 7; 9; 12.', 'Phân loại: 2 là acid, 7 trung tính, 9 và 12 là base.', 'Giải thích cách so sánh từng giá trị với 7.', 'Không gán các số này cho một mẫu hóa chất thực tế chưa đo.'], notes='Cho học sinh phân loại bốn giá trị minh họa và nêu căn cứ. Không dùng các con số này như kết quả đo hoặc thông tin y sinh. Nhắc lại yêu cầu không nếm/chạm hóa chất.')
        update(data, 5, 'Summarize only the checked scope.', bullets=['Ở 25 °C: so sánh pH với 7 để phân loại.', 'Giữ điều kiện và phạm vi của dữ liệu.', 'Không nếm hoặc chạm hóa chất.', 'Dùng dụng cụ/chỉ thị phù hợp theo hướng dẫn được kiểm tra.'], notes='Ôn các giá trị minh họa và quy tắc an toàn trong nguồn. Giáo viên đối chiếu tài liệu trước khi thêm công thức, dữ liệu môi trường hoặc ví dụ sinh học.')
    elif number == 16:
        update(data, 2, 'Retain the qualified thermal contribution in the source.', bullets=['Lục địa và đại dương có sự thay đổi nhiệt độ khác nhau theo mùa.', 'Chênh lệch nhiệt góp phần hình thành chênh lệch khí áp và hoàn lưu gió.', 'Gió mùa đổi hướng theo mùa.', 'Địa hình và vị trí cũng ảnh hưởng lượng mưa từng nơi.'], notes='Giải thích cơ chế tổng quát, không coi một nguyên nhân đơn lẻ giải thích toàn bộ khí hậu từng vùng. Giữ cách diễn đạt góp phần trong nguồn; cần tài liệu bổ sung khi phân tích chi tiết.')
        update(data, 3, 'Remove a false nationwide rainy/dry-season mapping.', bullets=['Gió mùa đổi hướng theo mùa.', 'Đặc điểm gió và mưa thay đổi theo từng địa phương.', 'Không suy ra mọi nơi có cùng lượng mưa hoặc cùng mùa mưa.', 'Muốn so sánh Việt Nam theo vùng cần thêm bản đồ và dữ liệu khí tượng có nguồn.'], notes='Nguồn hiện có chỉ nêu cơ chế tổng quát. Không gán mùa đông là mùa khô cho toàn miền Trung hoặc toàn Việt Nam. Giáo viên cung cấp thêm dữ liệu địa phương trước khi yêu cầu so sánh hướng gió, tháng xuất hiện và lượng mưa.')
        update(data, 4, 'Keep applications conditional on local evidence.', bullets=['Gió mùa ảnh hưởng nguồn nước và sản xuất nông nghiệp.', 'Mưa thay đổi theo vị trí, địa hình và thời kỳ.', 'Đọc dữ liệu từng vùng trước khi kết luận mùa mưa/mùa khô.', 'Thảo luận cách thích nghi dựa trên thông tin địa phương đã kiểm tra.'], notes='Dùng câu hỏi thảo luận: cần những dữ liệu nào để lập kế hoạch mùa vụ ở nơi em sống? Không đưa lịch tháng hoặc kết luận khí hậu từng vùng khi đoạn nguồn chưa cung cấp. Ví dụ bổ sung cần ghi rõ nguồn và thời kỳ.')
        update(data, 5, 'Use the source-qualified general summary.', bullets=['Gió mùa là gió đổi hướng theo mùa.', 'Chênh lệch nhiệt lục địa – đại dương góp phần hình thành gió mùa.', 'Không phải mọi nơi có gió mùa đều có cùng lượng mưa.', 'Phân tích từng địa phương với nguồn dữ liệu phù hợp.'], notes='Học sinh nhắc lại khái niệm và giới hạn của kết luận. Giao nhiệm vụ tìm nguồn khí tượng địa phương có thời kỳ rõ ràng; chưa dùng số liệu chưa kiểm tra để dạy.')
        update(data, 1, 'Do not pre-teach the unsupported regional mapping in the introduction.', notes='Giới thiệu mục tiêu: hiểu gió mùa đổi hướng theo mùa, vai trò chênh lệch nhiệt lục địa – đại dương và sự khác nhau giữa các địa phương. Không khái quát đồng nhất mùa mưa/mùa khô của mọi vùng từ nguồn ngắn hiện tại.')
    elif number == 17:
        replace(data, 'Bài 15: ', '')
        replace(data, 'James Watt cải tiến máy hơi nước (1769) — động lực mới', 'Máy hơi nước được cải tiến, góp phần thúc đẩy cơ giới hóa')
        replace(data, 'tư sản nghiệp', 'tư sản công nghiệp')
        replace(data, 'Cử động tranh', 'Các cuộc đấu tranh')
        replace(data, 'tau hỏa', 'tàu hỏa')
        data['editorial_review']['changes'].append({'slide': 1, 'reason': 'Remove an invented textbook lesson number and unprovided exact date; correct wording. Additional historical detail still needs source review.'})
    elif number == 18:
        for before, after in [('hai hình tu', 'hai biện pháp tu từ'), ('Hai hình tu', 'Hai biện pháp tu từ'), ('hình tu', 'biện pháp tu từ')]: replace(data, before, after)
        update(data, 1, 'Use a clear comparison example from the source.', bullets=['So sánh và ẩn dụ là hai biện pháp tu từ.', 'Chúng có thể làm cách diễn đạt gợi hình, gợi cảm.'], notes='Dùng câu tự tạo trong nguồn: Bạn ấy nhanh như gió. Học sinh chỉ ra hai đối tượng được đối chiếu và từ như. Không chỉ dựa vào một từ nối để phân loại mọi câu.')
        update(data, 2, 'Do not list unrelated prepositions as comparison markers.', bullets=['So sánh đối chiếu các sự vật có nét tương đồng.', 'Thường gặp cách diễn đạt như, tựa, giống như.', 'Ví dụ tự tạo: Bạn ấy nhanh như gió.'], notes='Giải thích sự đối chiếu giữa tốc độ của bạn và gió trong ví dụ. Từ nối là dấu hiệu gợi ý, cần xét cả nghĩa và cấu trúc; không liệt kê bên hoặc qua như dấu hiệu mặc định của phép so sánh.')
        update(data, 3, 'Remove the false universal A-is-B definition of metaphor.', bullets=['Ẩn dụ gọi tên sự vật bằng tên sự vật khác dựa trên nét tương đồng.', 'Cần giải thích sự chuyển nghĩa trong ngữ cảnh.', 'Không có một khuôn A + là + B áp dụng cho mọi ẩn dụ.'], notes='Ví dụ tự tạo để giáo viên xem lại: Một giọng nói ấm áp vang lên. Từ ấm áp vốn gắn với cảm giác nhiệt được chuyển sang miêu tả ấn tượng của giọng nói. Không định nghĩa ẩn dụ chỉ bằng việc có hoặc không có từ là.')
        update(data, 4, 'Compare meanings instead of an absolute keyword rule.', bullets=['So sánh: đối chiếu các đối tượng có nét tương đồng.', 'Ẩn dụ: gọi tên hoặc diễn đạt bằng sự chuyển nghĩa dựa trên tương đồng.', 'Xét ngữ cảnh và ý nghĩa; từ nối chỉ là một dấu hiệu.', 'Giải thích căn cứ phân loại bằng câu cụ thể.'], notes='Dùng ví dụ so sánh trong nguồn và ví dụ chuyển nghĩa đã được giáo viên xem lại. Tránh kết luận mọi câu có là là ẩn dụ, hoặc chỉ cần không có như là đủ để xác định ẩn dụ.')
    elif number == 19:
        data['manifest']['slides'][2]['speaker_notes'] += ' Các mẫu do/does đang xét động từ thường; với be cần học mẫu am/is/are riêng.'
        data['editorial_review']['changes'].append({'slide': 3, 'reason': 'Scope do/does patterns to lexical verbs.'})
    elif number == 20:
        replace(data, '知识点', 'kiến thức')
        data['editorial_review']['changes'].append({'slide': 5, 'reason': 'Remove unrelated Chinese wording.'})
    amend(data, number)
    (TARGET / f'case-{number:02d}-deck.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'reviewed_samples': 20, 'directory': str(TARGET), 'raw_model_results_changed': False, 'teacher_approved': False}))
