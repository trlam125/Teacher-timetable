"""Opt-in live benchmark of literal-source selection; no database or browser control."""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def run(args):
    from dotenv import dotenv_values
    local = dotenv_values(ROOT / '.env')
    for key in ('AI_SLIDES_OPENROUTER_API_KEY', 'AI_SLIDES_PRIMARY_MODEL', 'AI_SLIDES_FALLBACK_MODELS', 'AI_SLIDES_AI_STEP_TIMEOUT_SECONDS'):
        if local.get(key):
            os.environ[key] = local[key]
    from app.services.ai_slides import provider
    from app.services.ai_slides.grounding import VERSION, assemble_batch, assemble_plan, proof_valid, source_units
    from app.services.ai_slides.schemas import Blueprint, GroundedBatch, GroundedPlan, Profile
    from app.services.ai_slides.state import validate_content
    model = await provider.eligible_model()
    fixtures = json.loads((ROOT / 'tests/fixtures/ai_slides_grounding.json').read_text(encoding='utf-8'))
    out = ROOT / 'tmp/ai-studio-qa/grounding-live'
    out.mkdir(parents=True, exist_ok=True)
    report = {'model': model, 'phase': args.phase, 'cases': [], 'scope': 'literal provenance and constraints, not pedagogical acceptance'}
    report_path = out / (args.phase + '-report.json')
    if args.cases and report_path.exists():
        previous = json.loads(report_path.read_text(encoding='utf-8'))
        report['cases'] = [item for item in previous['cases'] if item['id'] not in args.cases]
        report['previous_attempts'] = previous.get('previous_attempts', []) + [item for item in previous['cases'] if item['id'] in args.cases]
    for case in fixtures:
        if args.cases and case['id'] not in args.cases:
            continue
        profile = Profile.model_validate({**{key: value for key, value in case.items() if key not in {'id', 'text'}},
            'input_mode': 'document', 'grounding': 'strict', 'slide_count': 5, 'consent': True, 'training_consent': True,
            'locked_fields': ['lesson_title', 'subject', 'grade', 'duration_minutes'],
            'sources': [{'id': case['id'], 'name': 'Nguồn tổng hợp QA ' + case['id'], 'page': 1, 'text': case['text']}]}).model_dump()
        units = source_units(profile)
        signature = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        payload = {'task': args.phase, 'profile': {**profile, 'sources': [{key: source.get(key) for key in ('id', 'name', 'page', 'role')} for source in profile['sources']]},
                   'prompt_version': provider.PROMPT_VERSION, 'grounding_contract': {'version': VERSION, 'units': units}, 'source_decisions': []}
        item = {'id': case['id']}
        started = time.monotonic()
        try:
            if args.phase == 'plan':
                raw, usage = await provider.generate(model, GroundedPlan, payload)
                plan = assemble_plan(raw, profile, units)
                validate_content(plan, profile)
                artifact = {'profile': profile, 'signature': signature, 'blueprint': plan.model_dump(), 'usage': usage}
                (out / (case['id'] + '-plan.json')).write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
                item.update(status='passed', kinds=[slide.kind for slide in plan.slides], warnings=plan.warnings)
            else:
                assert case['id'] in args.reviewed, 'Each synthetic plan must be explicitly reviewed for the benchmark'
                saved = json.loads((out / (case['id'] + '-plan.json')).read_text(encoding='utf-8'))
                assert saved['signature'] == signature, 'Source changed after plan review'
                plan = Blueprint.model_validate(saved['blueprint'])
                payload['blueprint'] = deepcopy(saved['blueprint'])
                payload['blueprint']['warnings'] = []
                payload['author_scope'] = {'slides_in_response': len(plan.slides), 'response_total_seconds': sum(slide.duration_seconds for slide in plan.slides)}
                raw, usage = await provider.generate(model, GroundedBatch, payload)
                batch = assemble_batch(raw, profile, saved['blueprint'], units)
                validate_content(batch, profile, saved['blueprint'])
                slides = [slide.model_dump() for slide in batch.slides]
                assert all(proof_valid(slide, profile) for slide in slides)
                assert all(bullet in case['text'] for slide in slides for bullet in slide['bullets'])
                assert all(quote in case['text'] for slide in slides for quote in slide['speaker_notes'].split('\n\n') if quote)
                assert all(slide['resource_id'] is None and slide['chart_data'] is None for slide in slides)
                artifact = {**saved, 'manifest': batch.model_dump(), 'author_usage': usage}
                (out / (case['id'] + '-deck.json')).write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
                item.update(status='passed', slides=len(slides), proven_slides=len(slides),
                            literal_bullets=sum(len(slide['bullets']) for slide in slides), literal_note_segments=sum(len(slide['speaker_notes'].split('\n\n')) if slide['speaker_notes'] else 0 for slide in slides))
        except provider.StudioError as error:
            item.update(status='failed', code=error.code, message=error.message)
        item['seconds'] = round(time.monotonic() - started, 2)
        report['cases'].append(item)
        print(json.dumps(item, ensure_ascii=True), flush=True)
    (out / (args.phase + '-report.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return int(any(item['status'] != 'passed' for item in report['cases']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Allow real free-provider requests with synthetic source text')
    parser.add_argument('--phase', choices=('plan', 'author'), required=True)
    parser.add_argument('--reviewed', nargs='*', default=[])
    parser.add_argument('--cases', nargs='*', default=[])
    args = parser.parse_args()
    if not args.live:
        parser.error('Real provider calls require explicit --live')
    raise SystemExit(asyncio.run(run(args)))
