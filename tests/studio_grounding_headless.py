"""Extractive source mode, proof UI, manual edits and AI proposals in headless Chromium."""
import json
import re
import zipfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/ai-studio-qa'
OUT.mkdir(parents=True, exist_ok=True)
text = "\n".join([
    "Ở nhiệt độ không đổi, I = U/R.",
    "U đo bằng V, R đo bằng Ω, I đo bằng A.",
    "Khi U = 6 V và R = 3 Ω, cường độ dòng điện là I = 2 A.",
    "Khi điện trở không đổi, cường độ dòng điện tỉ lệ thuận với hiệu điện thế.",
    "Khi hiệu điện thế không đổi, cường độ dòng điện tỉ lệ nghịch với điện trở.",
    "Kết quả tính cần ghi đúng đơn vị của đại lượng cần tìm.",
])
checks = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto('http://127.0.0.1:8766/ai-studio')
    page.wait_for_load_state('networkidle')
    page.locator('#new-deck').click()
    page.locator('[name=subject]').fill('Vật lí')
    page.locator('[name=grade]').fill('Lớp 9')
    page.locator('[name=lesson_title]').fill('Định luật Ôm — trích đoạn')
    page.locator('[name=slide_count]').fill('5')
    page.locator('[name=grounding]').select_option('strict')
    expect(page.locator('#grounding-help')).to_be_visible()
    page.locator('#document-file').set_input_files({'name': 'nguon-om.txt', 'mimeType': 'text/plain', 'buffer': text.encode()})
    expect(page.locator('#source-count')).to_contain_text('1 đoạn nguồn')
    page.locator('#cloud-consent').check()
    page.get_by_role('button', name='Tạo dàn ý bằng AI', exact=True).click()
    expect(page.locator('#deck-status')).to_contain_text('Đã có dàn ý')
    page.locator('#continue-deck').click()
    expect(page.locator('#export-pptx')).to_be_visible()
    expect(page.locator('#slide-evidence')).to_contain_text('Đã đối chiếu trích đoạn')
    expect(page.locator('#slide-evidence')).to_contain_text('nguon-om.txt')
    checks.append('strict plan and author assemble excerpts and display source evidence')
    deck_id = page.evaluate("localStorage.getItem('studio-current-1')")
    deck = page.request.get('http://127.0.0.1:8766/api/ai-slides/decks/' + deck_id).json()
    assert all(row['verified'] for row in deck['grounding_report'])
    for slide in deck['manifest']['slides']:
        assert all(bullet in text for bullet in slide['bullets'])
        assert all(quote in text for quote in slide['speaker_notes'].split('\n\n'))
        assert slide['resource_id'] is None and slide['chart_data'] is None
    checks.append('every generated bullet and knowledge note is an exact substring of the selected source')
    page.locator('#slide-list button').nth(3).click()
    expect(page.locator('#quiz-question')).to_have_value(re.compile('Điền đúng nguyên văn'))
    assert '_____' in page.locator('#quiz-question').input_value()
    with page.expect_download() as pending:
        page.locator('#export-pptx').click()
    pending.value.save_as(OUT / 'grounded-headless.pptx')
    with zipfile.ZipFile(OUT / 'grounded-headless.pptx') as archive:
        slides = [name for name in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)]
        expected_slides = len(deck['manifest']['slides']) + sum(len(slide['options']) for slide in deck['manifest']['slides'] if slide['kind'] == 'quiz')
        assert len(slides) == expected_slides
        assert any(b'<p:timing' in archive.read(name) for name in slides)
    checks.append('cloze quiz and native PPTX download include working feedback structure')
    page.locator('#slide-list button').nth(0).click()
    page.locator('#slide-notes').fill('Kiến thức do giáo viên bổ sung ngoài tài liệu.')
    page.locator('#slide-form button').click()
    expect(page.locator('#slide-evidence')).to_contain_text('cần đối chiếu lại')
    expect(page.locator('#content-review')).to_contain_text('chỉnh tay')
    page.locator('#export-pptx').click()
    expect(page.locator('#studio-message')).to_contain_text('rà soát')
    checks.append('manual changes remove source proof and require export review')
    page.locator('#undo-deck').click()
    expect(page.locator('#slide-evidence')).to_contain_text('Đã đối chiếu trích đoạn')
    page.locator('#edit-instruction').fill('Đổi hoạt động lớp thành đọc trích đoạn')
    page.locator('#ai-edit-form button').click()
    expect(page.locator('#edit-proposal')).to_be_visible()
    expect(page.locator('#edit-proposal')).to_contain_text('Hoạt động giáo viên')
    expect(page.locator('#edit-proposal')).to_contain_text('Hoạt động học sinh')
    page.locator('#edit-proposal button').click()
    expect(page.locator('#slide-evidence')).to_contain_text('Đã đối chiếu trích đoạn')
    page.reload()
    expect(page.locator('#slide-evidence')).to_contain_text('Đã đối chiếu trích đoạn')
    checks.append('undo restores proof and exact stored AI proposal retains proof after explicit apply')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(OUT / 'grounding-evidence-mobile.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert not errors, errors
    checks.append('mobile source evidence fits without uncaught JavaScript errors')
    browser.close()
(OUT / 'grounding-headless-report.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(checks), 'checks': checks}, ensure_ascii=True))
