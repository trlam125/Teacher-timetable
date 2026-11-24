"""Bind Codex's editorial judgments to the actual 20 raw/edited sample files.

No inference, deployment, approval flag or human review state is changed.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.ai_slides_review.editorial_v4 import SOURCES, RAW_SCORES, FINDINGS
from tools.review_ai_slides_v4 import RUBRIC, technical_evidence


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def audit(raw, edited, previous_packet=None):
    baseline = {}
    if previous_packet is not None:
        packet = json.loads(previous_packet.read_text(encoding='utf-8'))
        for record in packet['records']:
            if record['variant'] == 'raw':
                baseline[record['case']] = record['assets'][record['deck_path']]
    expected = {f'case-{n:02d}-deck.json' for n in range(1, 21)}
    for folder in (raw, edited):
        if {p.name for p in folder.glob('case-*-deck.json')} != expected:
            raise ValueError('All 20 raw and edited samples are required')
    rendered = json.loads((edited / 'render-report.json').read_text(encoding='utf-8'))
    if rendered.get('complete_decks') != 20 or not rendered.get('fully_passed') or rendered.get('inference_calls') != 0:
        raise ValueError('The edited set has not completed its technical export checks')
    exports = {item['case']: item for item in rendered.get('decks', [])}
    records = []
    for number in range(1, 21):
        filename = f'case-{number:02d}-deck.json'
        raw_file, edited_file = raw / filename, edited / filename
        original = json.loads(raw_file.read_text(encoding='utf-8'))
        changed = json.loads(edited_file.read_text(encoding='utf-8'))
        if baseline and baseline.get(number) != digest(raw_file):
            raise ValueError('A raw benchmark changed after its earlier review packet')
        if original['profile'] != changed['profile']:
            raise ValueError('Editorial copies must preserve the supplied profile and source text')
        review = changed.get('editorial_review', {})
        if review.get('reviewer_kind') != 'ai' or review.get('teacher_approved') is not False or review.get('office_tested_by_agent') is not False:
            raise ValueError('AI editorial review cannot become teacher or Office approval')
        text = json.dumps(changed['manifest'], ensure_ascii=False)
        if re.search('[\u3400-\u9fff\uac00-\ud7af]', text):
            raise ValueError('Unexpected CJK/Hangul remains in an edited Vietnamese sample')
        if any(slide.get('source_proof') is not None for slide in changed['manifest']['slides']):
            raise ValueError('Authored copies must not inherit literal-source verification')
        exported = exports.get(edited_file.stem, {})
        if exported.get('source_sha256') != digest(edited_file) or exported.get('pptx_sha256') != digest(edited_file.with_suffix('.pptx')):
            raise ValueError('Exported PowerPoint does not match the latest edited content; render again')
        raw_scores = dict(zip(RUBRIC, RAW_SCORES[number]))
        # Different teaching depth and resource scope remain visible; no "100%"
        # result or automated acceptance is inferred from these subjective scores.
        edited_values = [27, 16, 14, 9, 8 if number in (2, 4) else 5, 8]
        if number in (1, 5, 12, 15):
            edited_values[2] = 15
        if number in (16, 17, 18):
            edited_values[0] = 25
            edited_values[1] = 14
        edited_scores = dict(zip(RUBRIC, edited_values))
        for scores in (raw_scores, edited_scores):
            if set(scores) != set(RUBRIC) or any(type(v) is not int or not 0 <= v <= RUBRIC[k] for k, v in scores.items()):
                raise ValueError('Invalid editorial rubric')
        technical = technical_evidence(changed, edited_file.with_suffix('.pptx'))
        if not technical['json_schema_valid'] or not technical['pptx_zip_xml_valid']:
            raise ValueError('Invalid edited JSON/PowerPoint package')
        reference = SOURCES[number]
        records.append({
            'case': number, 'title': changed['profile']['lesson_title'],
            'raw_sha256': digest(raw_file), 'edited_sha256': digest(edited_file),
            'pptx_sha256': digest(edited_file.with_suffix('.pptx')),
            'reviewed_fields': ['objectives', 'title', 'bullets', 'speaker_notes', 'teacher_action', 'student_action', 'quiz', 'resource_id', 'chart_data'],
            'raw_observation': FINDINGS[number], 'raw_scores': raw_scores, 'edited_scores': edited_scores,
            'raw_observed_hard_fails': ['invented_reference'] if number in (7, 17) else [],
            'hard_fail_list_is_exhaustive': False,
            'score_rationale': {
                'knowledge': 'Phán đoán AI về các mệnh đề đã đọc và điều kiện áp dụng, không đo độ chính xác.',
                'evidence': 'Nguồn ban đầu ngắn/tổng hợp; bản sửa thêm tham khảo, chưa xác nhận SGK/chương trình Việt Nam.',
                'pedagogy': 'Bộ nhỏ 5 slide; hoạt động và câu hỏi đã sửa, chưa quan sát tiết dạy thực tế.',
                'vietnamese': 'Đọc lại chữ và thuật ngữ; vẫn là nhận xét AI.',
                'resources': 'Không ép gắn học liệu ngoài phạm vi; hai mô phỏng cục bộ đối chiếu được điều khiển.',
                'structure': '5 slide nội dung có Notes; không nhận là giáo án đầy đủ cho thời lượng đã nhập.',
            },
            'reference': {'title': reference[0], 'urls': list(reference[1:]), 'accessed_by': 'Codex AI', 'accessed_date': '2026-11-24'},
            'editorial_changes': review['changes'], 'technical': technical,
        })
    return {
        'schema_version': 1, 'review_date': '2026-11-24', 'reviewer_kind': 'ai',
        'evidence_type': 'codex_editorial_judgment_not_independent_teacher_review',
        'rubric': RUBRIC, 'passing_threshold': None, 'inference_calls': 0,
        'teacher_approved': False, 'office_tested_by_agent': False,
        'raw_baseline_compared': len(baseline) == 20,
        'raw_model_qualified': False, 'deployment_approval_changed': False,
        'sample_scope': '20 miniature QA lessons / 100 content slides; not 20 complete lessons',
        'records': records,
    }


def markdown(report):
    lines = ['# Rà soát nội dung V4 do Codex thực hiện — 24/11/2026', '',
        'Đã đọc và biên tập 20 bộ mẫu, 100 slide nội dung, gồm mục tiêu, Notes, hoạt động, quiz và học liệu. '
        'Điểm dưới đây là nhận xét chủ quan của AI theo rubric 100 điểm, không phải tỷ lệ chính xác, '
        'không có ngưỡng đỗ tự đặt và không phải phiếu duyệt của giáo viên. '
        'Không lấy điểm bản sửa để đánh giá model thô.', '',
        'Mỗi bộ chỉ có 5 slide nội dung để QA. Đây chưa phải 20 giáo án hoàn chỉnh cho thời lượng nhập. '
        'Bản sửa bỏ bằng chứng trích nguyên văn kế thừa; các bài strict đã mở rộng sẽ hiện cảnh báo cần rà soát. '
        'Nguồn bổ sung ghi trong Notes, không thay nguồn người dùng đã nhập.', '',
        'Rubric: kiến thức 30 / bằng chứng 20 / sư phạm 20 / tiếng Việt 10 / học liệu 10 / cấu trúc 10. '
        'JSON đi kèm giữ điểm từng tiêu chí, lý do, SHA-256 và kiểm tra cấu trúc.', '',
        '| Ca | Bài | AI gốc | Bản sửa | Phát hiện và sửa chính |', '|---|---|---:|---:|---|']
    for item in report['records']:
        lines.append(f"| {item['case']} | {item['title']} | {sum(item['raw_scores'].values())} | {sum(item['edited_scores'].values())} | {item['raw_observation']} |")
    lines += ['', '## Nguồn đối chiếu và phạm vi', '']
    for item in report['records']:
        ref = item['reference']
        links = ', '.join(f'[{ref["title"]}]({url})' for url in ref['urls'])
        lines.append(f"- Bài {item['case']} — {item['title']}: {links}. Đối chiếu khái niệm/công thức trong phạm vi bài; ví dụ và hoạt động là biên tập tự tạo.")
    lines += ['', '## Kết luận sử dụng', '',
        'Đã hoàn tất lượt rà soát AI thay cho việc yêu cầu người dùng chấm 20 bộ trong lượt này. '
        '20 bản sửa đã được xuất lại bằng Chromium ẩn; đây là ảnh HTML và kiểm tra OOXML, không phải PowerPoint renderer. '
        'Ba tệp motion trước đó được người dùng báo chạy đúng trong PowerPoint Desktop; không gán kết quả đó cho 20 tệp mới.', '',
        'Bộ AI gốc có lỗi rõ ràng, gồm tham chiếu SGK tự bịa ở ca 7/17. Model hiện tại chưa đủ bằng chứng để phê duyệt nội dung tự động. '
        'Giữ AI_SLIDES_CONTENT_QA_APPROVED=false. Không chặn việc dùng preview có rà soát và không thay website/DB chính.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-packet', type=Path)
    args = parser.parse_args()
    folder = ROOT / 'tmp/ai-studio-qa'
    report = audit(folder / 'v4-benchmark', folder / 'v4-reviewed', args.previous_packet)
    (folder / 'v4-editorial-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'docs/ai-pptx/V4_EDITORIAL_AUDIT.md').write_text(markdown(report), encoding='utf-8')
    print(json.dumps({'reviewed_cases': len(report['records']), 'raw_baseline_compared': report['raw_baseline_compared'], 'teacher_approved': False, 'raw_model_qualified': False}))


if __name__ == '__main__':
    main()
