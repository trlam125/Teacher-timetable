"""Exercise the offline review desk with disposable synthetic data, no AI/Office."""
import json
from pathlib import Path
import sys
import tempfile
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from test_ai_slides_review import review_fixture
from tools.review_ai_slides_v4 import validate_report

OUT = ROOT / 'tmp/ai-studio-qa'
OUT.mkdir(parents=True, exist_ok=True)
checks, errors, network = [], [], []
with tempfile.TemporaryDirectory(prefix='review-browser-', dir=ROOT / 'tmp') as temp:
    folder = Path(temp).resolve()
    assert folder.is_relative_to(ROOT / 'tmp')
    output, _ = review_fixture(folder)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        def no_http(route):
            if route.request.url.startswith(('http:', 'https:')):
                network.append(route.request.url)
                route.abort('blockedbyclient')
            else: route.continue_()
        context.route('**/*', no_http)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto((output / 'index.html').as_uri())
        expect(page.locator('#title')).to_contain_text('<script>không thực thi</script>')
        expect(page.locator('#progress')).to_contain_text('0/1')
        with page.expect_download() as pending: page.locator('#export-review').click()
        blank = output / 'blank.json'
        pending.value.save_as(blank)
        result = validate_report(output / 'manifest.json', blank)
        assert not result['model_content_review_complete'] and result['content_accepted_edited'] == 0
        checks.append('empty reports remain unreviewed and source markup is displayed as text')
        page.locator('#reviewer-name').fill('Người ghi QA giả — không phải giáo viên duyệt thật')
        page.locator('#qualified-reviewer').check()
        for field, value in [('knowledge', 30), ('evidence', 20), ('pedagogy', 20), ('vietnamese', 10), ('resources', 10), ('structure', 10)]:
            page.locator(f'[data-score={field}]').fill(str(value))
        for select in page.locator('#hard-fails select').all(): select.select_option('clear')
        page.locator('#content-read').check()
        page.locator('#verdict').select_option('accept')
        expect(page.locator('#progress')).to_contain_text('1/1')
        page.locator('#variant').select_option('raw')
        expect(page.locator('#progress')).to_contain_text('0/1')
        expect(page.locator('[data-score=knowledge]')).to_have_value('')
        checks.append('edited acceptance never supplies raw-model scores or approval')
        page.locator('#variant').select_option('edited')
        page.locator('#office-version').fill('Synthetic browser QA, not an Office result')
        for select in page.locator('#desktop-checks select').all(): select.select_option('pass')
        with page.expect_download() as pending: page.locator('#export-review').click()
        filled = output / 'filled.json'
        pending.value.save_as(filled)
        result = validate_report(output / 'manifest.json', filled)
        assert result['content_accepted_edited'] == 1 and result['content_accepted_raw'] == 0
        assert not result['edited_desktop_review_complete']  # One fixture cannot report testing all twenty exports.
        page.reload()
        expect(page.locator('[data-score=knowledge]')).to_have_value('30')
        expect(page.locator('#office-version')).to_have_value('Synthetic browser QA, not an Office result')
        checks.append('scores and declared Desktop checks persist and export with exact file hashes; one fixture cannot satisfy twenty')
        bad = json.loads(filled.read_text(encoding='utf-8'))
        bad['packet_id'] = '0' * 64
        page.locator('#import-review').set_input_files({'name': 'wrong.json', 'mimeType': 'application/json', 'buffer': json.dumps(bad).encode()})
        expect(page.locator('#message')).to_have_attribute('data-error', 'true')
        expect(page.locator('[data-score=knowledge]')).to_have_value('30')
        page.locator('#import-review').set_input_files(str(filled))
        expect(page.locator('#message')).to_contain_text('Đã mở đúng')
        checks.append('wrong packet is rejected without replacing progress and valid backup restores')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.screenshot(path=str(OUT / 'human-review-mobile.png'), full_page=True)
        assert not errors and not network, (errors, network)
        checks.append('offline review desk fits mobile and makes no HTTP request or uncaught script error')
        browser.close()
(OUT / 'human-review-headless-report.json').write_text(json.dumps({'checks': checks, 'browser_errors': errors, 'network': network, 'synthetic_only': True}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(checks), 'human_approval_created': False}))
