"""Headless browser checks against studio_preview_server.py, using test fixtures."""
import json
import zipfile
import time
import urllib.request
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
artifacts = root / "tmp/ai-studio-qa"
artifacts.mkdir(parents=True, exist_ok=True)
deadline = time.monotonic() + 60
while True:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8766/ai-studio", timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.5)
writer = PdfWriter()
for number in range(1, 151):
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data((
        f"BT /F1 12 Tf 50 700 Td (Lesson page {number}. Electric current follows Ohm law at constant temperature.) Tj "
        "0 -20 Td (Voltage is measured in volts. Resistance is measured in ohms. Confirm the lesson before teaching.) Tj ET"
    ).encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
writer.add_outline_item(title="Lesson 1", page_number=0)
writer.add_outline_item(title="Lesson 2", page_number=34)
writer.write(artifacts / "book-150-pages.pdf")
scan = PdfWriter()
scan.add_blank_page(width=595, height=842)
scan.write(artifacts / "scan.pdf")
(artifacts / "source.txt").write_text("Tai lieu kiem thu. I = U/R khi nhiet do khong doi.", encoding="utf-8")
with zipfile.ZipFile(artifacts / "source.docx", "w") as archive:
    archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    archive.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Docx test paragraph</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table test cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')

results = []
errors = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8766/ai-studio")
    page.wait_for_load_state("networkidle")
    expect(page.locator("#deck-list")).not_to_contain_text("Đang tải")
    page.screenshot(path=str(artifacts / "studio-desktop.png"), full_page=True)
    page.locator("#new-deck").click()
    page.locator('input[name=input_mode][value=manual]').check()
    page.locator('[name=subject]').fill("Vật lí")
    page.locator('[name=grade]').fill("Lớp 9")
    page.locator('[name=lesson_title]').fill("Định luật Ôm")
    page.locator('[name=slide_count]').fill("5")
    page.locator("#cloud-consent").check()
    page.get_by_role("button", name="Tạo dàn ý bằng AI", exact=True).click()
    expect(page.locator("#deck-status")).to_contain_text("Đã có dàn ý")
    results.append("manual outline and persisted draft")
    page.locator("#continue-deck").click()
    expect(page.locator("#export-pptx")).to_be_visible()
    page.reload()
    expect(page.locator("#deck-status")).to_contain_text("Sẵn sàng tải")
    results.append("authoring and reload resume")
    page.locator("#show-deck-log").click()
    expect(page.locator("#deck-log")).to_contain_text("author:0")
    expect(page.locator("#deck-log")).to_contain_text("fixture/test:free")
    results.append("owned processing log with model, step and version")
    with page.expect_download() as pending:
        page.locator("#export-pptx").click()
    pending.value.save_as(artifacts / "browser-export.pptx")
    with zipfile.ZipFile(artifacts / "browser-export.pptx") as archive:
        assert "ppt/slides/slide1.xml" in archive.namelist()
        assert "Định luật Ôm" in archive.read("ppt/slides/slide1.xml").decode()
    results.append("browser-generated editable PPTX download")
    page.locator("#slide-title").fill("Tiêu đề được sửa")
    page.locator("#slide-form").get_by_role("button", name="Lưu slide", exact=True).click()
    expect(page.locator("#slide-preview")).to_contain_text("Tiêu đề được sửa")
    page.reload()
    expect(page.locator("#slide-preview")).to_contain_text("Tiêu đề được sửa")
    page.locator("#undo-deck").click()
    expect(page.locator("#slide-preview")).not_to_contain_text("Tiêu đề được sửa")
    results.append("manual slide edit, reload and persisted undo")
    page.locator("#edit-instruction").fill("Thêm ví dụ gần gũi")
    page.locator("#ai-edit-form button").click()
    expect(page.locator("#edit-proposal")).to_be_visible()
    page.locator("#edit-proposal button").click()
    expect(page.locator("#slide-preview")).to_contain_text("Ví dụ đã được sửa")
    results.append("scoped AI proposal, preview and explicit apply")
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(artifacts / "studio-editor.png"), full_page=True)
    page.locator("#new-deck").click()
    page.locator('input[name=input_mode][value=manual]').check()
    page.locator('[name=subject]').fill("Vật lí")
    page.locator('[name=grade]').fill("Lớp 9")
    page.locator('[name=lesson_title]').fill("Bài kiểm tra 15 slide")
    page.locator('[name=slide_count]').fill("15")
    page.locator("#cloud-consent").check()
    page.get_by_role("button", name="Tạo dàn ý bằng AI", exact=True).click()
    expect(page.locator("#deck-status")).to_contain_text("Đã có dàn ý")
    page.locator("#continue-deck").click()
    expect(page.locator("#export-pptx")).to_be_visible()
    expect(page.locator("#slide-list button")).to_have_count(15)
    expect(page.locator("#deck-status")).to_contain_text("Phiên bản 5")
    page.locator("#show-deck-log").click()
    expect(page.locator("#deck-log")).to_contain_text("author:10")
    page.reload()
    expect(page.locator("#slide-list button")).to_have_count(15)
    results.append("15-slide automatic authoring in three saved batches and reload")
    page.locator("#new-deck").click()
    page.locator("#document-file").set_input_files(artifacts / "book-150-pages.pdf")
    expect(page.locator("#document-name")).to_contain_text("150 trang PDF", timeout=20000)
    page.locator("#book-toc").select_option("1")
    expect(page.locator("#page-first")).to_have_value("35")
    page.locator("#page-last").fill("36")
    page.locator("#extract-pages").click()
    expect(page.locator("#source-count")).to_contain_text("2 đoạn nguồn", timeout=15000)
    assert "Lesson page 35" in page.locator("#source-list textarea").nth(0).input_value()
    assert "Lesson page 36" in page.locator("#source-list textarea").nth(1).input_value()
    results.append("150-page PDF, bookmark resolution and exact selected-page extraction")
    page.locator("#save-book").click()
    expect(page.locator("#studio-message")).to_contain_text("Đã lưu sách")
    page.reload()
    page.locator("#show-books").click()
    expect(page.locator("#book-list")).to_contain_text("book-150-pages.pdf")
    results.append("local book cache survives reload")
    page.locator("#document-file").set_input_files(artifacts / "source.docx")
    expect(page.locator("#source-list")).to_contain_text("source.docx", timeout=15000)
    docx_text = page.locator("#source-list textarea").last.input_value()
    assert "Docx test paragraph" in docx_text and "Table test cell" in docx_text
    page.locator("#document-file").set_input_files(artifacts / "source.txt")
    expect(page.locator("#source-list")).to_contain_text("source.txt")
    results.append("DOCX paragraphs, DOCX table text and UTF-8 TXT")
    page.locator("#document-file").set_input_files(artifacts / "scan.pdf")
    expect(page.locator("#document-name")).to_contain_text("scan.pdf")
    page.locator("#extract-pages").click()
    expect(page.locator("#studio-message")).to_contain_text("scan", timeout=15000)
    results.append("scan rejected without hallucinated text")
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(artifacts / "studio-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    results.append("390px mobile without horizontal overflow")
    page.goto("http://127.0.0.1:8766/ai-studio/simulations/ohm")
    expect(page.locator("#simulation-output")).to_contain_text("0.600 A")
    page.locator("#voltage").fill("12")
    expect(page.locator("#simulation-output")).to_contain_text("1.200 A")
    page.goto("http://127.0.0.1:8766/ai-studio/simulations/pendulum")
    expect(page.locator("#simulation-output")).to_contain_text("2.01 s")
    page.goto("http://127.0.0.1:8766/ai-studio/simulations/vietnam-map")
    page.get_by_role("button", name="Tây Nguyên", exact=True).click()
    expect(page.locator("#region-description")).to_contain_text("cao nguyên")
    results.append("Ohm equation, small-angle pendulum period and geographic selection")
    assert not errors, errors
    results.append("no uncaught browser JavaScript errors")
    browser.close()
report = {"passed": len(results), "checks": results, "page_errors": errors, "provider": "test-only fixture"}
(artifacts / "headless-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
