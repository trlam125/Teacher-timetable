"""V4 additions on the loopback fixture: links, inspection, books, source expansion, guide."""
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from uuid import uuid4
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/ai-studio-qa'
GUIDE = ROOT / 'app/static/ai-slides/guide'
GUIDE.mkdir(parents=True, exist_ok=True)
checks = []

pdf = OUT / 'two-lessons-one-page.pdf'
writer = PdfWriter()
sheet = writer.add_blank_page(width=595, height=842)
font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
sheet[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
stream = DecodedStreamObject()
lines = ['Lesson 1: Resistance', 'Resistance relates voltage and current under specified conditions.',
         'Use the same temperature and compare the measurements in the first activity.',
         'Lesson 2: Electric power', 'Electric power is a different topic and must not leak into lesson one.',
         'Read the units and discuss this second lesson separately from resistance.']
stream.set_data(('BT /F1 12 Tf 45 720 Td ' + ' 0 -24 Td '.join(f'({line}) Tj' for line in lines) + ' ET').encode())
sheet[NameObject('/Contents')] = writer._add_object(stream)
writer.write(pdf)


def fill_profile(page, title):
    page.locator('[name=subject]').fill('Khoa học')
    page.locator('[name=grade]').fill('Lớp 6')
    page.locator('[name=lesson_title]').fill(title)
    page.locator('[name=slide_count]').fill('5')


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
    page.add_init_script("""window.voiceStarts = 0; window.SpeechRecognition = class {
      start() { window.voiceStarts++; queueMicrotask(() => { const item = [{ transcript: 'Tập trung vào ví dụ gần gũi và đơn vị đo.' }]; item.isFinal = true; this.onresult?.({ results: [item] }); this.onend?.(); }); }
      stop() { this.onend?.(); } abort() { this.onend?.(); }
    };""")
    errors, calls = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: calls.append(request.url) if request.method == 'POST' and request.url.rsplit('/', 1)[-1] in {'plan', 'author', 'inspect-sources', 'propose'} else None)
    page.goto('http://127.0.0.1:8766/ai-studio')
    page.wait_for_load_state('networkidle')
    page.locator('#new-deck').click()
    page.locator('#cloud-consent').check()
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('[name=subject]')).to_be_focused()
    assert not calls
    checks.append('missing required metadata is focused before any draft or inference request')
    fill_profile(page, 'Bài học mẫu kiểm thử V4')
    page.locator('details').filter(has=page.locator('#voice-transcript')).locator('summary').click()
    page.locator('#voice-start').click()
    assert page.evaluate('window.voiceStarts') == 0
    page.locator('#voice-consent').check()
    page.locator('#voice-start').click()
    expect(page.locator('#voice-transcript')).to_have_value('Tập trung vào ví dụ gần gũi và đơn vị đo.')
    page.locator('#voice-apply').click()
    expect(page.locator('[name=must_include]')).to_have_value(re.compile('ví dụ gần gũi'))
    assert not calls
    page.locator('details').filter(has=page.locator('#voice-transcript')).locator('summary').click()
    checks.append('voice adapter requires consent and explicit transcript apply, tested with a mock microphone')
    page.locator('#create-pane').screenshot(path=str(GUIDE / 'input.png'))
    page.locator('#cloud-consent').check()
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('#export-pptx')).to_be_visible()
    page.locator('.studio-editor').screenshot(path=str(GUIDE / 'editor.png'))
    before = len(calls)
    page.locator('#manual-resource-editor summary').click()
    page.locator('#resource-link-title').fill('Video đã chọn để dạy')
    page.locator('#resource-link-url').fill('https://youtu.be/abcdefgh_12?t=2')
    page.locator('#slide-form button').click()
    expect(page.locator('#content-review')).to_contain_text('Liên kết do giáo viên')
    page.reload()
    expect(page.locator('#resource-link-url')).to_have_value('https://www.youtube.com/watch?v=abcdefgh_12')
    page.locator('#content-review-ack').check()
    with page.expect_download() as pending:
        page.locator('#export-pptx').click()
    target = OUT / 'v4-teacher-link.pptx'
    pending.value.save_as(target)
    with zipfile.ZipFile(target) as archive:
        assert 'https://www.youtube.com/watch?v=abcdefgh_12' in archive.read('ppt/slides/_rels/slide1.xml.rels').decode()
        assert 'chưa xác minh' in archive.read('ppt/notesSlides/notesSlide1.xml').decode()
    assert len(calls) == before
    checks.append('manual teacher link saves/reloads/exports with unverified credit and no AI')
    with page.expect_download() as pending:
        page.locator('#export-offline').click()
    offline = OUT / 'v4-offline.zip'
    pending.value.save_as(offline)
    extracted = OUT / ('offline-' + uuid4().hex)
    assert extracted.resolve().is_relative_to(OUT.resolve())
    with zipfile.ZipFile(offline) as archive:
        assert all(not Path(name).is_absolute() and '..' not in Path(name).parts for name in archive.namelist())
        assert all(name in archive.namelist() for name in ['lesson.pptx', 'notes.txt', 'lesson.json', 'THIRD_PARTY_NOTICES.txt', 'index.html'])
        archive.extractall(extracted)
    offline_page = browser.new_page()
    offline_page.goto((extracted / 'simulations/vietnam-map.html').as_uri())
    offline_page.locator('#map-route-toggle').check()
    expect(offline_page.locator('#region-description')).to_contain_text('Tuyến minh họa')
    offline_page.locator('#map-regions button').last.click()
    expect(offline_page.locator('#region-description')).to_contain_text('Mekong')
    offline_page.close()
    checks.append('offline ZIP includes editable PPTX/notes/local simulations and map works from a file URL')

    page.locator('#new-deck').click()
    page.locator('#document-file').set_input_files(str(target))
    expect(page.locator('#source-list textarea')).to_have_value(re.compile('Bài học mẫu'))
    expect(page.locator('#studio-message')).to_contain_text('Chỉ nhập chữ')
    checks.append('existing PPTX text imports locally with explicit loss of unsupported elements')
    unsafe = OUT / 'v4-inert-macro-marker.pptx'
    reordered = OUT / 'v4-reordered.pptx'
    with zipfile.ZipFile(target) as original, zipfile.ZipFile(unsafe, 'w') as bad, zipfile.ZipFile(reordered, 'w') as changed:
        slide_files = sorted([name for name in original.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)], key=lambda name: int(re.search(r'slide(\d+)', name)[1]))
        last_title = ET.fromstring(original.read(slide_files[-1])).find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}t').text
        for name in original.namelist():
            content = original.read(name)
            bad.writestr(name, content)
            if name == 'ppt/presentation.xml':
                root = ET.fromstring(content)
                ids = root.find('{http://schemas.openxmlformats.org/presentationml/2006/main}sldIdLst')
                ids[:] = list(reversed(list(ids)))
                content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            changed.writestr(name, content)
        bad.writestr('ppt/vbaProject.bin', b'inert marker only, no executable macro')
    prior = page.locator('#source-list textarea').input_value()
    page.locator('#document-file').set_input_files(str(unsafe))
    expect(page.locator('#studio-message')).to_contain_text('macro')
    assert page.locator('#source-list textarea').input_value() == prior
    checks.append('macro-bearing PPTX is rejected without changing existing source text')
    page.locator('#document-file').set_input_files(str(reordered))
    expect(page.locator('#source-list textarea').last).to_have_value(re.compile('^Slide gốc 1\n' + re.escape(last_title)))
    checks.append('PPTX import follows presentation relationships after reordering rather than slide filenames')
    page.locator('#document-file').set_input_files(str(target))
    expect(page.locator('#studio-message')).to_contain_text('Chỉ nhập chữ')
    page.locator('#pptx-import-mode').select_option('style')
    expect(page.locator('#style-reference')).to_be_visible()
    expect(page.locator('#style-reference')).to_contain_text('không nhập nội dung')
    page.locator('#style-reference button').click()
    assert page.locator('[name=theme]').input_value() in {'science', 'primary', 'geography', 'history'}
    checks.append('PPTX style reference reads palette and applies a suggested existing theme only after teacher action')

    page.locator('#new-deck').click()
    page.locator('#document-file').set_input_files({'name': 'nguon-chua-co-tieu-de.txt', 'mimeType': 'text/plain', 'buffer': 'Nước chuyển trạng thái khi được cung cấp hoặc mất đi năng lượng. Giáo viên hướng dẫn học sinh quan sát ví dụ phù hợp.'.encode()})
    page.locator('#cloud-consent').check()
    page.locator('#recognize-source-ai').click()
    expect(page.locator('[name=subject]')).to_have_value('Khoa học')
    expect(page.locator('[name=grade]')).to_have_value('Lớp 6')
    expect(page.locator('[name=lesson_title]')).to_have_value('Bài học từ nguồn đã chọn')
    page.locator('#save-draft').click()
    expect(page.locator('#source-intelligence')).to_be_visible()
    checks.append('document mode can use one AI inspection before required metadata is filled and preserves its evidence')

    page.locator('#new-deck').click()
    fill_profile(page, 'Đối chiếu sự sôi')
    page.locator('#document-file').set_input_files({'name': 'nguon-a.txt', 'mimeType': 'text/plain', 'buffer': 'Ở áp suất không đổi, nhiệt độ nước không đổi trong quá trình sôi.'.encode()})
    page.locator('details').filter(has=page.locator('#pasted-source')).locator('summary').click()
    page.locator('#pasted-source').fill('Ở áp suất không đổi, nhiệt độ nước tăng liên tục trong quá trình sôi.')
    page.locator('#add-paste').click()
    page.locator('#cloud-consent').check()
    page.locator('#save-draft').click()
    before = len(calls)
    page.locator('#inspect-sources').click()
    expect(page.locator('#source-intelligence')).to_be_visible()
    expect(page.locator('#source-review')).to_contain_text('AI gợi ý kiểm tra')
    assert len(calls) == before + 1
    page.locator('#source-review').screenshot(path=str(GUIDE / 'source-review.png'))
    page.locator('#source-review input[type=radio]').last.check()
    page.locator('#source-review-form button').click()
    page.reload()
    expect(page.locator('#source-review input[type=radio]').last).to_be_checked()
    checks.append('optional AI inspection uses one saved step and semantic choice survives reload')

    page.locator('#new-deck').click()
    fill_profile(page, 'Mở rộng theo nguồn đã chọn')
    page.locator('[name=grounding]').select_option('verified_expansion')
    text = 'Ở nhiệt độ không đổi, cường độ dòng điện tỉ lệ thuận với hiệu điện thế. Hiệu điện thế và cường độ dòng điện cần ghi đúng đơn vị. Đối chiếu kết quả với điều kiện đo trong bài.'
    page.locator('#document-file').set_input_files({'name': 'nguon-chinh.txt', 'mimeType': 'text/plain', 'buffer': text.encode()})
    page.locator('details').filter(has=page.locator('#pasted-source')).locator('summary').click()
    page.locator('#pasted-source').fill('Tài liệu tham khảo bổ sung hướng dẫn đọc và so sánh bảng số liệu. Ghi rõ đơn vị và điều kiện khi trình bày ví dụ. Giáo viên kiểm tra phạm vi trước khi dùng để mở rộng.')
    page.locator('#add-paste').click()
    page.locator('#cloud-consent').check()
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('#export-pptx')).to_be_visible()
    deck_id = page.evaluate("localStorage.getItem('studio-current-1')")
    deck = page.request.get('http://127.0.0.1:8766/api/ai-slides/decks/' + deck_id).json()
    assert all(item['verified'] for item in deck['grounding_report'])
    assert any(item['code'] == 'SUPPLEMENTARY_SOURCE' for item in deck['review'])
    checks.append('source expansion keeps checked quotations and marks supplementary sources')

    page.locator('#new-deck').click()
    page.locator('#document-file').set_input_files(str(pdf))
    page.locator('#discover-lessons').click()
    expect(page.locator('#book-toc option')).to_have_count(3)
    page.locator('#book-toc').select_option('0')
    page.locator('#extract-pages').click()
    expect(page.locator('#source-list textarea')).to_have_value(re.compile('Resistance'))
    assert 'Electric power' not in page.locator('#source-list textarea').input_value()
    page.locator('#save-book').click()
    expect(page.locator('#studio-message')).to_contain_text('Đã lưu sách trên thiết bị')
    page.reload()
    page.locator('#show-books').click()
    page.get_by_role('button', name='two-lessons-one-page.pdf', exact=True).click()
    expect(page.locator('#book-toc option')).to_have_count(3)
    page.locator('#extract-pages').click()
    assert 'Electric power' not in page.locator('#source-list textarea').input_value()
    checks.append('same-page lesson boundaries and saved book index/scope persist across reload')
    page.locator('#show-books').click()
    expect(page.get_by_role('button', name='Liên kết lại tệp', exact=True)).to_be_enabled()
    page.locator('#book-list input[type=file]').set_input_files(str(pdf))
    expect(page.locator('#studio-message')).to_contain_text('liên kết lại')
    checks.append('relink verifies file fingerprint and restores book scope')

    page.locator('#new-deck').click()
    page.locator('[name=subject]').fill('Khoa học')
    page.locator('[name=grade]').fill('Lớp 6')
    page.locator('[name=slide_count]').fill('5')
    page.locator('#document-file').set_input_files(str(pdf))
    page.locator('#discover-lessons').click()
    expect(page.locator('#batch-lessons option')).to_have_count(2)
    page.locator('#batch-panel summary').click()
    page.locator('#batch-lessons').select_option(['0', '1'])
    page.locator('#prepare-batch').click()
    expect(page.locator('#batch-preview textarea')).to_have_count(2)
    page.locator('#batch-reviewed').check()
    page.locator('#cloud-consent').check()
    author_calls = []
    def limit_second(route):
        author_calls.append(route.request.url)
        if len(author_calls) == 2:
            route.fulfill(status=429, content_type='application/json', body=json.dumps({'code': 'AI_QUOTA_EXHAUSTED', 'message': 'Hết lượt QA tạm thời'}))
        else:
            route.continue_()
    page.route('**/api/ai-slides/decks/*/author', limit_second)
    page.locator('#start-batch').click()
    expect(page.locator('#batch-progress')).to_contain_text('1/2')
    expect(page.locator('#studio-message')).to_contain_text('Hết lượt QA')
    before = len(calls)
    page.reload()
    expect(page.locator('#batch-progress')).to_contain_text('1/2')
    assert len(calls) == before
    page.locator('#resume-batch').click()
    expect(page.locator('#batch-progress')).to_contain_text('2/2')
    assert len(author_calls) == 3
    saved_queue = page.evaluate("JSON.parse(localStorage.getItem('studio-batch-1'))")
    assert all(set(item) == {'id', 'title', 'completed'} for item in saved_queue['items'])
    page.unroute('**/api/ai-slides/decks/*/author', limit_second)
    checks.append('book batch saves sequentially, stops on quota, reload makes no AI call and explicit resume skips completed decks')

    page.goto('http://127.0.0.1:8766/ai-studio/simulations/vietnam-map')
    page.locator('#map-route-toggle').check()
    expect(page.locator('#region-description')).to_contain_text('Tuyến minh họa')
    page.locator('#map-regions button').last.click()
    expect(page.locator('#region-description')).to_contain_text('Mekong')
    checks.append('illustrative geography route and region details remain interactive')

    page.goto('http://127.0.0.1:8766/ai-studio')
    page.locator('#show-usage').click()
    expect(page.locator('#usage-summary')).to_contain_text('Bài giảng đã lưu')
    expect(page.locator('#usage-summary dd')).to_have_count(4)
    checks.append('admin usage shows aggregate deck/step/error counts and UTC quota')

    page.goto('http://127.0.0.1:8766/ai-studio/guide')
    expect(page.get_by_role('heading', level=1)).to_contain_text('PowerPoint')
    page.locator('img').evaluate_all("(items) => items.forEach(i => i.loading = 'eager')")
    page.wait_for_function('Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)')
    assert page.locator('img').evaluate_all('(items) => items.every(i => i.complete && i.naturalWidth > 0)')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(OUT / 'v4-guide-mobile.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert not errors, errors
    checks.append('teacher guide uses real fixture screenshots and fits mobile without JS errors')
    browser.close()
(OUT / 'v4-headless-report.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(checks), 'checks': checks}, ensure_ascii=True))
