"""Bounded live free-model probe. Synthetic source only; never connects to app DB."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(args):
    from app.services.ai_slides import provider
    from app.services.ai_slides.schemas import Profile, IntelligenceResult
    from app.services.ai_slides.intelligence import checked_intelligence
    if args.model:
        os.environ['AI_SLIDES_PRIMARY_MODEL'] = args.model
        os.environ['AI_SLIDES_FALLBACK_MODELS'] = ''
    model = await provider.eligible_model()
    profile = Profile.model_validate({'subject': 'Khoa học', 'grade': 'Lớp 6', 'lesson_title': 'Sự sôi', 'slide_count': 5,
        'consent': True, 'training_consent': True, 'locked_fields': ['subject', 'grade', 'lesson_title'],
        'sources': [{'id': 'qa-a', 'name': 'Nguồn tổng hợp A', 'text': 'Ở áp suất không đổi, nhiệt độ nước không đổi trong suốt quá trình sôi.'},
                    {'id': 'qa-b', 'name': 'Nguồn tổng hợp B', 'role': 'reference', 'text': 'Ở áp suất không đổi, nhiệt độ nước tăng liên tục trong suốt quá trình sôi.'}]}).model_dump()
    if args.fixture == 'metadata':
        profile = Profile.model_validate({'subject': 'Chưa xác định', 'grade': 'Chưa xác định', 'lesson_title': 'Bản phân tích nguồn',
            'input_mode': 'document', 'slide_count': 5, 'consent': True, 'training_consent': True, 'locked_fields': [],
            'sources': [{'id': 'source-qa', 'name': 'Văn bản tổng hợp QA', 'text': 'Môn: Khoa học. Lớp: 6. Bài: Sự chuyển thể của nước. Thời lượng: 45 phút. Nước bốc hơi và ngưng tụ. Giáo viên hướng dẫn học sinh quan sát ví dụ phù hợp.'}]}).model_dump()
    started = time.monotonic()
    report = {'model': model, 'prompt_version': provider.PROMPT_VERSION, 'fixture': args.fixture, 'requests': 1, 'synthetic_only': True, 'application_db_used': False}
    try:
        result, usage = await provider.generate(model, IntelligenceResult, {'task': 'inspect', 'profile': profile,
            'instruction': 'Chỉ trả gợi ý metadata và mâu thuẫn giữa các đoạn đã chọn. Quote phải NGUYÊN VĂN đúng nguồn. Không có thì trả danh sách rỗng. Không sửa thông tin khóa.'})
        result = checked_intelligence(result, profile)
        report.update(status='passed-schema-and-quotes', result=result, usage=usage)
    except provider.StudioError as error:
        report.update(status='failed', code=error.code, provider_status=error.provider_status, message=error.message)
    report['seconds'] = round(time.monotonic() - started, 2)
    target = ROOT / 'tmp/ai-studio-qa' / args.output
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'result'}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--model')
    parser.add_argument('--fixture', choices=['conflict', 'metadata'], default='conflict')
    parser.add_argument('--output', default='v4-model-probe.json')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)
    asyncio.run(main(args))
