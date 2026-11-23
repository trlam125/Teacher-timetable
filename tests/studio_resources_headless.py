"""Manual vetted resources: details, persistence, native hyperlinks and attribution."""
import json
import zipfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/ai-studio-qa'
OUT.mkdir(parents=True, exist_ok=True)
catalog = json.loads((ROOT / 'app/static/ai-slides/resources.json').read_text(encoding='utf-8'))
checks = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
    errors, calls = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: calls.append(request.url) if request.method == 'POST' and request.url.rsplit('/', 1)[-1] in {'plan', 'author', 'propose'} else None)
    page.goto('http://127.0.0.1:8766/ai-studio')
    page.wait_for_load_state('networkidle')
    page.locator('#new-deck').click()
    page.locator('[name=subject]').fill('Khoa học')
    page.locator('[name=grade]').fill('Lớp 6')
    page.locator('[name=lesson_title]').fill('Kiểm thử học liệu PhET')
    page.locator('[name=slide_count]').fill('5')
    page.locator('#cloud-consent').check()
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('#export-pptx')).to_be_visible()
    assert len(calls) == 2
    checks.append('resource options come from the vetted shared catalog')
    for item in (item for item in catalog if item['group'] == 'PhET'):
        page.locator('#slide-resource').select_option(item['id'])
        details = page.locator('#resource-details')
        expect(details).to_contain_text(item['label'])
        expect(details).to_contain_text('Cần Internet')
        expect(details).to_contain_text('University of Colorado Boulder')
        expect(details.locator('a')).to_have_attribute('href', item['url'])
        expect(details.locator('a')).to_have_attribute('rel', 'noopener noreferrer')
        page.locator('#slide-form button').click()
        page.reload()
        expect(page.locator('#slide-resource')).to_have_value(item['id'])
        with page.expect_download() as pending:
            page.locator('#export-pptx').click()
        path = OUT / (item['id'] + '-ui.pptx')
        pending.value.save_as(path)
        with zipfile.ZipFile(path) as archive:
            relations = archive.read('ppt/slides/_rels/slide1.xml.rels').decode()
            notes = archive.read('ppt/notesSlides/notesSlide1.xml').decode()
            assert item['url'] in relations
            assert 'PhET' in notes and 'University of Colorado Boulder' in notes
            assert b'<p:transition' in archive.read('ppt/slides/slide1.xml')
        assert len(calls) == 2, 'Manual resource edits/downloads must not call AI'
        checks.append(item['id'] + ': credited preview, save/reload and native PPTX link')
    page.locator('#slide-resource').select_option('')
    expect(page.locator('#resource-details')).not_to_be_visible()
    page.locator('#slide-form button').click()
    page.reload()
    expect(page.locator('#slide-resource')).to_have_value('')
    checks.append('resource can be removed without regeneration')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('#slide-resource').select_option('phet-fractions-intro')
    page.screenshot(path=str(OUT / 'resources-mobile.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert not errors, errors
    checks.append('resource details fit mobile without JavaScript errors')
    browser.close()
(OUT / 'resources-headless-report.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(checks), 'checks': checks}, ensure_ascii=True))
