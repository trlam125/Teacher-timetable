"""Real local Vietnamese OCR on synthetic images and a raster-only PDF."""
import base64
import json
import re
import unicodedata
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/ai-studio-qa'
checks, measurements = [], []


def cer(expected, actual):
    normalize = lambda text: re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip()
    expected, actual = normalize(expected), normalize(actual)
    row = list(range(len(actual) + 1))
    for i, left in enumerate(expected, 1):
        next_row = [i]
        for j, right in enumerate(actual, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (left != right)))
        row = next_row
    return round(row[-1] / max(1, len(expected)), 4)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1200, 'height': 650})
    page = context.new_page()
    text = 'Vòng tuần hoàn nước\nNước bốc hơi và ngưng tụ.\nMưa đưa nước về mặt đất.\nGiáo viên kiểm tra trước khi dạy.'
    formula = 'Định luật Ôm\nI = U / R\nU = 6 V, R = 3 Ω\nI = 2 A'
    for name, value in [('ocr-clean-vietnamese', text), ('ocr-formula', formula)]:
        page.set_content('<div id="sheet" style="font:44px/1.8 Arial;background:white;color:black;padding:40px;width:1100px;height:470px;white-space:pre-wrap"></div>')
        page.locator('#sheet').evaluate('(node, text) => node.textContent = text', value)
        page.locator('#sheet').screenshot(path=str(OUT / (name + '.png')))
    encoded = base64.b64encode((OUT / 'ocr-clean-vietnamese.png').read_bytes()).decode()
    page.set_content(f'<html><style>body{{margin:0}}img{{width:1180px}}</style><img src="data:image/png;base64,{encoded}"></html>')
    page.pdf(path=str(OUT / 'ocr-scan.pdf'), width='1180px', height='550px', print_background=True)
    page.goto('http://127.0.0.1:8766/ai-studio')
    page.wait_for_load_state('networkidle')
    page.locator('#new-deck').click()
    page.locator('#ocr-panel summary').click()
    errors, uploads = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    context.on('request', lambda request: uploads.append(request.url) if request.method == 'POST' else None)
    for name, expected_text in [('ocr-clean-vietnamese', text), ('ocr-formula', formula)]:
        page.locator('#ocr-image').set_input_files(str(OUT / (name + '.png')))
        page.locator('#ocr-image-start').click()
        expect(page.locator('#ocr-text')).not_to_have_value('', timeout=120000)
        expect(page.locator('#ocr-add')).to_be_enabled(timeout=120000)
        actual = page.locator('#ocr-text').input_value()
        measurements.append({'fixture': name, 'cer': cer(expected_text, actual), 'recognized': actual})
        expect(page.locator('#ocr-reviewed')).not_to_be_checked()
        page.locator('#ocr-add').click()
        expect(page.locator('#studio-message')).to_contain_text('xác nhận')
        if name == 'ocr-clean-vietnamese':
            assert measurements[-1]['cer'] <= 0.15, measurements[-1]
            page.locator('#ocr-text').fill(expected_text)
            page.locator('#ocr-reviewed').check()
            page.locator('#ocr-add').click()
            expect(page.locator('#source-list')).to_contain_text('OCR')
            expect(page.locator('#cloud-consent')).not_to_be_checked()
    checks.append('real Vietnamese image OCR measured against known text; manual review required before use')
    checks.append('formula OCR result measured separately, editable and never treated as ground truth')
    page.locator('#document-file').set_input_files(str(OUT / 'ocr-scan.pdf'))
    page.locator('#ocr-pdf-start').click()
    expect(page.locator('#ocr-text')).not_to_have_value('', timeout=120000)
    expect(page.locator('#ocr-add')).to_be_enabled(timeout=120000)
    actual = page.locator('#ocr-text').input_value()
    measurements.append({'fixture': 'raster-only-pdf', 'cer': cer(text, actual), 'recognized': actual})
    assert measurements[-1]['cer'] <= 0.15, measurements[-1]
    checks.append('one raster PDF page is rendered and recognized locally with measured text quality')
    page.locator('#ocr-image-start').click()
    page.locator('#ocr-cancel').click()
    expect(page.locator('#studio-message')).to_contain_text('Đã dừng OCR', timeout=15000)
    expect(page.locator('#ocr-add')).to_be_enabled()
    checks.append('explicit cancel stops OCR without attaching partial text or leaving controls locked')
    assert not errors and not uploads, (errors, uploads)
    checks.append('OCR assets are self-hosted, no source image/text upload or uncaught JavaScript error')
    page.screenshot(path=str(OUT / 'ocr-review-ui.png'), full_page=True)
    browser.close()
(OUT / 'ocr-headless-report.json').write_text(json.dumps({'checks': checks, 'measurements': measurements, 'page_errors': errors, 'uploads': uploads}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(checks), 'measurements': [{key: value for key, value in item.items() if key != 'recognized'} for item in measurements]}, ensure_ascii=True))
