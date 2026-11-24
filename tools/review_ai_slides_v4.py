"""Build an offline V4 review desk, or validate a human report against its files."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RUBRIC = {'knowledge': 30, 'evidence': 20, 'pedagogy': 20, 'vietnamese': 10, 'resources': 10, 'structure': 10}
HARD_FAILS = ('invented_reference', 'locked_input_changed', 'central_formula_wrong')
DESKTOP = ('opens', 'objects', 'transition', 'links', 'notes', 'editable')


def technical_evidence(deck, pptx):
    sys.path.insert(0, str(ROOT))
    from app.services.ai_slides.schemas import Profile, Blueprint, Manifest
    from app.services.ai_slides.review import content_review
    result = {'json_schema_valid': False, 'pptx_zip_xml_valid': False, 'pptx_pages': 0, 'notes': 0,
              'findings': content_review(deck['manifest'], deck['profile'])}
    try:
        Profile.model_validate(deck['profile'])
        Blueprint.model_validate(deck['blueprint'])
        Manifest.model_validate(deck['manifest'])
        result['json_schema_valid'] = True
    except (ValueError, KeyError):
        pass
    try:
        with zipfile.ZipFile(pptx) as archive:
            names = archive.namelist()
            pages = [name for name in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)]
            notes = [name for name in names if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml', name)]
            if not {'[Content_Types].xml', 'ppt/presentation.xml'}.issubset(names) or len(pages) < len(deck['manifest']['slides']) or len(notes) != len(pages):
                raise ValueError('Incomplete exported package')
            for name in archive.namelist():
                if name.endswith(('.xml', '.rels')):
                    ET.fromstring(archive.read(name))
            result.update(pptx_zip_xml_valid=True,
                          pptx_pages=len(pages), notes=len(notes))
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError):
        pass
    return result


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def build_packet(raw, edited, output):
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for variant, directory in [('raw', raw), ('edited', edited)]:
        for file in sorted(directory.glob('case-*-deck.json')):
            case = int(re.fullmatch(r'case-(\d+)-deck.json', file.name)[1])
            deck = json.loads(file.read_text(encoding='utf-8'))
            pptx = file.with_suffix('.pptx')
            if not pptx.is_file():
                raise ValueError(f'Missing exported PowerPoint for {variant}/{case}')
            destination = output / 'assets' / variant
            destination.mkdir(parents=True, exist_ok=True)
            assets = {}
            for source in [file, pptx, *sorted(directory.glob(file.stem + '-slide-*.png'))]:
                target = destination / source.name
                shutil.copyfile(source, target)
                assets[target.relative_to(output).as_posix()] = digest(target)
            profile = deck['profile']
            records.append({'id': f'{variant}:{case:02d}', 'case': case, 'variant': variant,
                            'title': profile['lesson_title'], 'subject': profile['subject'], 'grade': profile['grade'],
                            'model': deck.get('model'), 'deck_path': (destination / file.name).relative_to(output).as_posix(),
                            'pptx_path': (destination / pptx.name).relative_to(output).as_posix(),
                            'assets': assets, 'profile': profile, 'slides': deck['manifest']['slides'],
                            'technical': technical_evidence(deck, pptx),
                            'editorial_changes': deck.get('editorial_review', {}).get('changes', [])})
    packet_id = sha256(json.dumps({'rubric': RUBRIC, 'records': records}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    manifest = {'schema_version': 1, 'packet_id': packet_id, 'rubric': RUBRIC,
                'raw_and_edited_are_separate': True, 'office_rendered': False, 'records': records}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    template = (ROOT / 'tools/ai_slides_review/index.html').read_text(encoding='utf-8')
    safe_json = json.dumps(manifest, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    (output / 'index.html').write_text(template.replace('REVIEW_PACKET_JSON', safe_json), encoding='utf-8')
    for name in ('review.js', 'review.css'):
        shutil.copyfile(ROOT / 'tools/ai_slides_review' / name, output / name)
    # Preserve relative documentation links in the offline packet as well.
    for name in ('HUMAN_REVIEW.md', 'V4_BENCHMARK_REVIEW.md', 'V4_EDITORIAL_AUDIT.md'):
        source = ROOT / 'docs/ai-pptx' / name
        if source.is_file():
            shutil.copyfile(source, output / name)
    return manifest


def _validate_record(record, expected):
    if not isinstance(record, dict) or record.get('asset_hashes') != expected['assets']:
        raise ValueError('Review refers to different files')
    scores = record.get('scores')
    if not isinstance(scores, dict) or set(scores) != set(RUBRIC):
        raise ValueError('Invalid rubric fields')
    for key, value in scores.items():
        if value is not None and (type(value) is not int or not 0 <= value <= RUBRIC[key]):
            raise ValueError('Rubric score outside range')
    hard = record.get('hard_fails')
    if not isinstance(hard, dict) or set(hard) != set(HARD_FAILS) or any(value not in ('pending', 'clear', 'fail') for value in hard.values()):
        raise ValueError('Invalid hard-fail review')
    desktop = record.get('desktop')
    if not isinstance(desktop, dict) or set(desktop.get('checks', {})) != set(DESKTOP) or any(value not in ('pending', 'pass', 'fail') for value in desktop['checks'].values()):
        raise ValueError('Invalid desktop checklist')
    if not isinstance(desktop.get('version'), str) or len(desktop['version']) > 120:
        raise ValueError('Invalid Office version')
    if record.get('verdict') not in ('pending', 'revise', 'accept') or type(record.get('content_read')) is not bool:
        raise ValueError('Invalid review conclusion')
    if not isinstance(record.get('notes'), str) or len(record['notes']) > 8000:
        raise ValueError('Invalid review notes')
    content = record['content_read'] and record['verdict'] == 'accept' and all(value is not None for value in scores.values()) and all(value == 'clear' for value in hard.values())
    office = bool(desktop['version'].strip()) and all(value == 'pass' for value in desktop['checks'].values())
    return {'id': expected['id'], 'total': sum(scores.values()) if all(value is not None for value in scores.values()) else None,
            'content_accepted': content, 'desktop_pass_reported': office,
            'hard_fail_reported': any(value == 'fail' for value in hard.values())}


def validate_report(manifest_path, report_path):
    packet = json.loads(manifest_path.read_text(encoding='utf-8'))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if packet.get('schema_version') != 1 or packet.get('rubric') != RUBRIC:
        raise ValueError('Unknown packet protocol or rubric')
    if report.get('schema_version') != 1 or report.get('packet_id') != packet.get('packet_id'):
        raise ValueError('Wrong packet or report schema')
    reviewer = report.get('reviewer')
    if not isinstance(reviewer, dict) or not isinstance(reviewer.get('name'), str) or len(reviewer['name']) > 120 or type(reviewer.get('qualified_reviewer')) is not bool:
        raise ValueError('Invalid reviewer identity')
    expected = {record['id']: record for record in packet['records']}
    identity = {'rubric': RUBRIC, 'records': packet['records']}
    if sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != packet['packet_id'] or len(expected) != len(packet['records']):
        raise ValueError('Packet manifest identity changed')
    for record in expected.values():
        if record.get('deck_path') not in record['assets'] or record.get('pptx_path') not in record['assets']:
            raise ValueError('Missing core file hashes')
        for relative, checksum in record['assets'].items():
            path = (manifest_path.parent / relative).resolve()
            if not path.is_relative_to(manifest_path.parent.resolve()) or not path.is_file() or digest(path) != checksum:
                raise ValueError('Packet asset changed or escaped its directory')
        source = json.loads((manifest_path.parent / record['deck_path']).read_text(encoding='utf-8'))
        if record['profile'] != source['profile'] or record['slides'] != source['manifest']['slides']:
            raise ValueError('Displayed content differs from the bound source file')
    entries = report.get('records')
    if not isinstance(entries, dict) or set(entries) != set(expected):
        raise ValueError('Missing or unknown review entries')
    results = [_validate_record(entries[key], value) for key, value in expected.items()]
    has_identity = bool(reviewer['name'].strip()) and reviewer['qualified_reviewer']
    raw = [item for item in results if item['id'].startswith('raw:')]
    edited = [item for item in results if item['id'].startswith('edited:')]
    return {'schema_version': 1, 'packet_id': packet['packet_id'], 'evidence_type': 'human_self_report_not_independently_authenticated',
            'reviewer_identity_declared': has_identity, 'content_accepted_raw': sum(item['content_accepted'] for item in raw),
            'content_accepted_edited': sum(item['content_accepted'] for item in edited),
            'desktop_passes_edited': sum(item['desktop_pass_reported'] for item in edited),
            'model_content_review_complete': has_identity and len(raw) == 20 and all(item['content_accepted'] for item in raw)
                and all(expected[item['id']]['technical']['json_schema_valid'] and expected[item['id']]['technical']['pptx_zip_xml_valid'] for item in raw),
            'edited_desktop_review_complete': has_identity and len(edited) == 20 and all(item['desktop_pass_reported'] for item in edited),
            'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'tmp/ai-studio-qa/v4-review-desk')
    parser.add_argument('--report', type=Path, help='Validate exported human JSON; never changes deployment approval flags.')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        parser.error('Output must be inside the workspace')
    if args.report:
        print(json.dumps(validate_report(output / 'manifest.json', args.report), ensure_ascii=True))
    else:
        for name in ('v4-benchmark', 'v4-reviewed'):
            if len(list((ROOT / 'tmp/ai-studio-qa' / name).glob('case-*-deck.json'))) != 20:
                parser.error('Build requires all 20 raw and 20 edited decks')
        packet = build_packet(ROOT / 'tmp/ai-studio-qa/v4-benchmark', ROOT / 'tmp/ai-studio-qa/v4-reviewed', output)
        print(json.dumps({'review_desk': str(output / 'index.html'), 'records': len(packet['records']), 'packet_id': packet['packet_id'], 'teacher_approved': False}))


if __name__ == '__main__':
    main()
