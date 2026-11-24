"""Render/export saved real AI benchmark decks via loopback UI, without inference."""
import json
import argparse
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory', choices=['v4-benchmark', 'v4-reviewed'], default='v4-benchmark')
args = parser.parse_args()
OUT = ROOT / 'tmp/ai-studio-qa' / args.directory
report = {'inference_calls': 0, 'render_engine': 'HTML preview, not Office renderer', 'decks': []}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1100}, accept_downloads=True)
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith('http://127.0.0.1:8766/') or not route.request.url.startswith(('http:', 'https:')) else route.abort('blockedbyclient'))
    page = context.new_page()
    errors, inference = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: inference.append(request.url) if request.method == 'POST' and request.url.rsplit('/', 1)[-1] in {'plan', 'author', 'propose', 'inspect-sources'} else None)
    page.goto('http://127.0.0.1:8766/ai-studio')
    csrf = page.locator('meta[name=csrf-token]').get_attribute('content')
    for target in sorted(OUT.glob('case-*-deck.json')):
        saved = json.loads(target.read_text(encoding='utf-8'))
        # Presentation-only QA setting, independent of the saved AI content.
        subject = saved['profile']['subject']
        grade = int(re.search(r'\d+', saved['profile']['grade'])[0])
        saved['profile']['theme'] = 'geography' if subject == 'Địa lí' else 'history' if subject in {'Lịch sử', 'Ngữ văn'} else 'primary' if grade <= 5 else 'science'
        seed = page.request.post('http://127.0.0.1:8766/fixtures/deck', data=saved,
                                 headers={'X-CSRF-Token': csrf, 'Origin': 'http://127.0.0.1:8766'})
        assert seed.status == 200, seed.text()
        identity = seed.json()['id']
        page.evaluate("id => localStorage.setItem('studio-current-1', id)", identity)
        page.reload()
        expect(page.locator('#deck-title')).to_have_text(saved['profile']['lesson_title'])
        item = {'case': target.stem, 'slides': len(saved['manifest']['slides']), 'render_theme': saved['profile']['theme'], 'preview_overflow': [], 'status': 'passed'}
        page.locator('#slide-preview').screenshot(path=str(OUT / (target.stem + '-cover.png')))
        for index in range(item['slides']):
            page.locator('#slide-list button').nth(index).click()
            overflow = page.locator('#slide-preview .scene-text').evaluate_all('(nodes) => nodes.filter(n => n.scrollHeight > n.clientHeight + 2 || n.scrollWidth > n.clientWidth + 2).map(n => n.dataset.objectId)')
            if overflow:
                item['preview_overflow'].append({'slide': index + 1, 'objects': overflow})
        if page.locator('#content-review-ack').is_visible():
            page.locator('#content-review-ack').check()
        try:
            with page.expect_download(timeout=20000) as pending:
                page.locator('#export-pptx').click()
            pptx = OUT / (target.stem + '.pptx')
            pending.value.save_as(pptx)
            with zipfile.ZipFile(pptx) as archive:
                slides = [name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)]
                for name in archive.namelist():
                    if name.endswith(('.xml', '.rels')):
                        ET.fromstring(archive.read(name))
                item['pptx_pages'] = len(slides)
                item['notes'] = len([name for name in archive.namelist() if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml', name)])
                assert item['notes'] == len(slides)
        except Exception as error:
            item.update(status='failed-export', message=page.locator('#studio-message').inner_text(), exception=type(error).__name__)
        if item['preview_overflow']:
            item['status'] = 'needs-layout-review'
        report['decks'].append(item)
        (OUT / 'render-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(item, ensure_ascii=True), flush=True)
    assert not errors and not inference, (errors, inference)
    report['browser_errors'] = errors
    report['complete_decks'] = len(report['decks'])
    report['fully_passed'] = all(item['status'] == 'passed' for item in report['decks'])
    (OUT / 'render-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    browser.close()
