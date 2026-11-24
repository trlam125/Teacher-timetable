"""Two-phase, bounded live V4 benchmark. Plans require explicit review before authoring."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(args):
    from app.services.ai_slides import provider
    from app.services.ai_slides.schemas import Blueprint, GroundedPlan, GroundedBatch, Profile, SlideBatch
    from app.services.ai_slides.grounding import VERSION, source_units, assemble_plan, assemble_batch, proof_valid
    from app.services.ai_slides.state import validate_content
    if args.model:
        os.environ['AI_SLIDES_PRIMARY_MODEL'] = args.model
        os.environ['AI_SLIDES_FALLBACK_MODELS'] = ''
    model = await provider.eligible_model()
    assert Path(args.output_name).name == args.output_name and re.fullmatch(r'[a-z0-9-]+', args.output_name)
    out = ROOT / 'tmp/ai-studio-qa' / args.output_name
    out.mkdir(parents=True, exist_ok=True)
    # Only public synthetic benchmark responses are retained; production calls
    # never use this transport and no headers/key or request body are recorded.
    active_case = None
    original_client = provider.httpx.AsyncClient
    class BenchmarkClient(original_client):
        async def post(self, *call_args, **kwargs):
            response = await super().post(*call_args, **kwargs)
            if active_case is not None and response.status_code == 200:
                data = response.json()
                choice = (data.get('choices') or [{}])[0]
                content = (choice.get('message') or {}).get('content')
                (out / f'raw-case-{active_case:02d}-{args.phase}.json').write_text(json.dumps({'content': content, 'finish_reason': choice.get('finish_reason')}, ensure_ascii=False, indent=2), encoding='utf-8')
            return response
    provider.httpx.AsyncClient = BenchmarkClient
    cases = json.loads((ROOT / 'tests/fixtures/ai_slides_benchmark.json').read_text(encoding='utf-8'))
    report = {'model': model, 'phase': args.phase, 'synthetic_sources': True, 'cases': [],
              'teacher_pedagogy_approval': False, 'application_db_used': False}
    report_name = args.phase + ('-recheck-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime()) if args.only else '') + '-report.json'
    transient = 0
    for number, case in enumerate(cases[:args.limit], 1):
        if args.only and number not in args.only:
            continue
        active_case = number
        strict = number in {1, 5, 12, 15}
        profile = Profile.model_validate({'subject': case['subject'], 'grade': case['grade'], 'lesson_title': case['title'],
            'duration_minutes': 25, 'slide_count': 5, 'input_mode': ['manual', 'document', 'hybrid'][(number - 1) % 3],
            'level': ['foundation', 'standard', 'advanced'][(number - 1) % 3],
            'grounding': 'strict' if strict else 'balanced', 'consent': True, 'training_consent': True,
            'locked_fields': ['subject', 'grade', 'lesson_title', 'duration_minutes'],
            'sources': [{'id': 'qa-facts', 'name': 'Dữ liệu tổng hợp QA — không phải SGK', 'page': 1, 'text': case['facts']}]}).model_dump()
        signature = hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        payload = {'task': args.phase, 'profile': deepcopy(profile), 'prompt_version': provider.PROMPT_VERSION, 'source_decisions': []}
        units = source_units(profile) if strict else None
        if strict:
            payload['grounding_contract'] = {'version': VERSION, 'units': units}
            payload['profile']['sources'] = [{key: source.get(key) for key in ('id', 'name', 'page', 'role')} for source in profile['sources']]
        row = {'case': number, 'title': case['title'], 'grounding': profile['grounding']}
        started = time.monotonic()
        try:
            if args.phase == 'plan':
                raw, usage = await provider.generate(model, GroundedPlan if strict else Blueprint, payload)
                result = assemble_plan(raw, profile, units) if strict else raw
                validate_content(result, profile, generated=True)
                artifact = {'profile': profile, 'signature': signature, 'model': model, 'blueprint': result.model_dump(), 'plan_usage': usage}
                target = out / f'case-{number:02d}-plan.json'
                row.update(status='passed-structure', warnings=result.warnings)
            else:
                assert number in args.reviewed, 'Review each saved plan explicitly before authoring'
                saved = json.loads((out / f'case-{number:02d}-plan.json').read_text(encoding='utf-8'))
                assert saved['signature'] == signature and saved['model'] == model, 'Profile/model changed since review'
                plan = Blueprint.model_validate(saved['blueprint'])
                payload['blueprint'] = deepcopy(saved['blueprint'])
                payload['blueprint']['warnings'] = []  # Only after the explicit --reviewed gate above.
                payload['author_scope'] = {'slides_in_response': 5, 'response_total_seconds': 1500}
                raw, usage = await provider.generate(model, GroundedBatch if strict else SlideBatch, payload)
                result = assemble_batch(raw, profile, saved['blueprint'], units) if strict else raw
                validate_content(result, profile, saved['blueprint'], generated=True)
                assert [slide.duration_seconds for slide in result.slides] == [slide.duration_seconds for slide in plan.slides]
                if strict:
                    assert all(proof_valid(slide.model_dump(), profile) for slide in result.slides)
                artifact = {**saved, 'manifest': result.model_dump(), 'author_usage': usage}
                target = out / f'case-{number:02d}-deck.json'
                row.update(status='passed-structure-needs-content-review', slides=len(result.slides))
            target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
            transient = 0
        except provider.StudioError as error:
            row.update(status='failed', code=error.code, provider_status=error.provider_status, message=error.message)
            transient += error.code in {'AI_TIMEOUT', 'AI_NETWORK_ERROR', 'AI_MODEL_UNAVAILABLE'}
        row['seconds'] = round(time.monotonic() - started, 2)
        report['cases'].append(row)
        (out / report_name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(row, ensure_ascii=True), flush=True)
        if row.get('code') in {'AI_QUOTA_EXHAUSTED', 'AI_AUTH_ERROR', 'AI_DATA_POLICY'} or transient >= 2:
            print('Stopped: provider availability/quota; no automatic retry.', flush=True)
            break
        await asyncio.sleep(3)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--phase', choices=['plan', 'author'], required=True)
    parser.add_argument('--model')
    parser.add_argument('--output-name', default='v4-benchmark')
    parser.add_argument('--limit', type=int, choices=range(1, 21), default=20)
    parser.add_argument('--reviewed', type=int, nargs='*', default=[])
    parser.add_argument('--only', type=int, nargs='*')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    asyncio.run(run(args))
