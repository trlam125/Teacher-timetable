"""Source recognition, evidence decisions and local PDF discovery (no desktop UI)."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "tmp/ai-studio-qa"
ARTIFACT.mkdir(parents=True, exist_ok=True)
pdf = ARTIFACT / "book-without-bookmarks.pdf"
writer = PdfWriter()
for number in range(1, 9):
    lines = []
    if number == 1:
        lines = ["CONTENTS", "Lesson 1: Electric current ....... 93", "Lesson 2: Resistance ............ 108"]
    elif number in (3, 6):
        lines = ["Lesson 1: Electric current" if number == 3 else "Lesson 2: Resistance",
                 "Selected chapter text about Ohm law, current, voltage and resistance."]
    else:
        lines = [f"Reading page {number}: background information for this lesson."]
    sheet = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    sheet[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 12 Tf 50 700 Td " + " 0 -20 Td ".join(f"({line}) Tj" for line in lines) + " ET").encode())
    sheet[NameObject("/Contents")] = writer._add_object(stream)
writer.write(pdf)

checks = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url) if "/api/ai-slides/" in request.url else None)
    page.goto("http://127.0.0.1:8766/ai-studio")
    page.locator("#new-deck").click()
    page.locator("#document-file").set_input_files(pdf)
    expect(page.locator("#document-name")).to_contain_text("8 trang PDF")
    before = len(requests)
    page.locator("#discover-lessons").click()
    expect(page.locator("#studio-message")).to_contain_text("Đã tìm 2 tiêu đề")
    assert len(requests) == before, "Local indexing must not upload the book"
    page.locator("#book-toc").select_option("0")
    expect(page.locator("#page-first")).to_have_value("3")
    expect(page.locator("#page-last")).to_have_value("5")
    expect(page.locator("#source-list")).to_be_empty()
    checks.append("bookmark-free PDF discovery stays local, skips TOC numbers and selects physical pages 3–5")

    page.locator("#new-deck").click()
    page.locator("[name=input_mode][value=document]").check()
    page.locator("#document-file").set_input_files({"name": "lesson.txt", "mimeType": "text/plain", "buffer":
        "Môn: Vật lí\nLớp 9\nBài 12: Định luật Ôm\nThời lượng: 45 phút\nỞ nhiệt độ không đổi, I = U/R.".encode()})
    expect(page.locator("#source-list")).to_contain_text("lesson.txt")
    page.locator("#recognize-source").click()
    expect(page.locator("#studio-message")).to_contain_text("đồng ý")
    expect(page.locator("[name=subject]")).to_have_value("")
    checks.append("selected-source recognition requires consent")
    page.locator("details").filter(has=page.locator("#pasted-source")).locator("summary").click()
    page.locator("#pasted-source").fill("Nguồn tham khảo ghi I = U*R.")
    page.locator("#add-paste").click()
    page.locator("[name=slide_count]").fill("5")
    page.locator("#cloud-consent").check()
    page.get_by_role("button", name="Tạo dàn ý bằng AI", exact=True).click()
    expect(page.locator("#deck-status")).to_contain_text("Cần rà soát nguồn")
    expect(page.locator("#source-review")).to_be_visible()
    expect(page.locator("#continue-deck")).not_to_be_visible()
    assert not any(url.endswith("/plan") for url in requests)
    checks.append("document mode fills explicit empty metadata and blocks AI until source review")
    fieldset = page.locator("#source-conflicts fieldset").filter(has=page.get_by_text("Công thức I", exact=True))
    fieldset.locator("label").filter(has_text="I = U/R").locator("input").check()
    page.locator("#source-review-form button").click()
    expect(page.locator("#continue-deck")).to_be_visible()
    page.reload()
    expect(page.locator("#source-conflicts input:checked")).to_have_count(1)
    page.locator("#continue-deck").click()
    expect(page.locator("#deck-status")).to_contain_text("Đã có dàn ý")
    checks.append("evidence choice persists across reload and unblocks planning")
    page.locator("#edit-input").click()
    page.locator("[name=lesson_title]").fill("Tên riêng giáo viên muốn giữ")
    page.locator("#cloud-consent").check()
    page.locator("#recognize-source").click()
    expect(page.locator("[name=lesson_title]")).to_have_value("Tên riêng giáo viên muốn giữ")
    page.locator("#source-recognition article").filter(has_text="Tên bài:").locator("button").click()
    expect(page.locator("#studio-message")).to_contain_text("đang khóa")
    expect(page.locator("[name=lesson_title]")).to_have_value("Tên riêng giáo viên muốn giữ")
    checks.append("recognition preserves typed and locked teacher metadata")
    page.locator("#source-list details").first.locator("summary").click()
    page.locator("#source-list textarea").first.fill("Môn: Vật lí\nLớp 9\nBài 12: Định luật Ôm\nI = U/R. Đã sửa nguồn.")
    expect(page.locator("#cloud-consent")).not_to_be_checked()
    expect(page.locator("#source-recognition")).not_to_be_visible()
    page.locator("#cloud-consent").check()
    page.locator("#save-draft").click()
    expect(page.locator("#deck-status")).to_contain_text("Cần rà soát nguồn")
    expect(page.locator("#source-conflicts input:checked")).to_have_count(0)
    checks.append("editing source clears stale recognition, consent and prior decisions")
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(ARTIFACT / "source-review-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not errors, errors
    checks.append("source review fits mobile and runs without JavaScript errors")
    browser.close()

(ARTIFACT / "source-review-headless-report.json").write_text(json.dumps({"checks": checks, "page_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"passed": len(checks), "checks": checks}, ensure_ascii=False))
