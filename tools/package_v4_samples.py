"""Package exactly the source-reviewed QA samples, never env/provider payloads."""
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def package(folder):
    report_file = folder / 'v4-editorial-audit.json'
    audit = json.loads(report_file.read_text(encoding='utf-8'))
    if audit.get('reviewer_kind') != 'ai' or audit.get('teacher_approved') is not False or len(audit.get('records', [])) != 20:
        raise ValueError('A complete, explicitly AI-labelled editorial audit is required')
    target = folder / 'V4-20-bai-mau-da-ra-soat.zip'
    selected = []
    listing = io.StringIO(newline='')
    writer = csv.writer(listing)
    writer.writerow(['Tệp PowerPoint', 'Tên bài', 'Rà soát', 'Giáo viên phê duyệt'])
    for record in audit['records']:
        deck = folder / 'v4-reviewed' / f"case-{record['case']:02d}-deck.json"
        pptx = deck.with_suffix('.pptx')
        for path, checksum in [(deck, record['edited_sha256']), (pptx, record['pptx_sha256'])]:
            if sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError('Sample changed after editorial review; regenerate audit first')
        selected.extend([deck, pptx, deck.with_name(deck.stem + '-cover.png')])
        writer.writerow([pptx.name, record['title'], 'Codex AI + nguồn tham khảo trong Notes', 'Chưa'])
    readme = '''BỘ 20 BÀI MẪU V4 — ĐÃ RÀ SOÁT BỞI CODEX AI
24/11/2026. Mỗi bộ có 5 slide nội dung; quiz có thêm trang phản hồi.
Đã sửa nội dung, Notes, mục tiêu, hoạt động, câu hỏi và phạm vi học liệu.
Đọc V4_EDITORIAL_AUDIT.md để xem phát hiện, điểm rubric chủ quan và nguồn đối chiếu.
Đây là bản biên tập, không phải đầu ra AI nguyên trạng, giáo án đầy đủ hoặc phiếu duyệt chuyên môn của giáo viên.
HTML preview và OOXML đã kiểm tra; không nhận đã mở 20 tệp bằng PowerPoint Desktop.
Ba tệp motion của đợt trước được người dùng báo chạy đúng; kết quả đó không được gán cho 20 tệp mới.
Nguồn gốc là dữ kiện QA tự tổng hợp. Tham khảo bổ sung có trong Notes; bản sửa không kế thừa nhãn đối chiếu nguyên văn.
Không cần bạn chấm 20 bài để hoàn thành lượt rà soát AI này. Khi dùng để dạy, vẫn xem nội dung phù hợp lớp thực tế.
Không chứa API key, dữ liệu tài khoản hoặc tài liệu người dùng.
'''
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in selected:
            archive.write(path, path.name)
        archive.write(report_file, report_file.name)
        archive.write(ROOT / 'docs/ai-pptx/V4_EDITORIAL_AUDIT.md', 'V4_EDITORIAL_AUDIT.md')
        archive.write(folder / 'v4-reviewed/render-report.json', 'render-report.json')
        archive.writestr('README.txt', readme.encode('utf-8-sig'))
        archive.writestr('DANH-SACH.csv', listing.getvalue().encode('utf-8-sig'))
    return target


if __name__ == '__main__':
    target = package(ROOT / 'tmp/ai-studio-qa')
    print(json.dumps({'packet': str(target), 'bytes': target.stat().st_size, 'cases': 20, 'teacher_approved': False}))
