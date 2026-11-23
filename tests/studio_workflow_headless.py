"""One-action generation, review pauses and explicit resume against local fixture."""
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'tmp/ai-studio-qa'
OUT.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:8766'
checks = []


def fill(page, title, count=15):
    page.locator('#new-deck').click()
    page.locator('[name=subject]').fill('Vật lí')
    page.locator('[name=grade]').fill('Lớp 9')
    page.locator('[name=lesson_title]').fill(title)
    page.locator('[name=slide_count]').fill(str(count))
    page.locator('#cloud-consent').check()


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors, calls = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: calls.append((request.url.rsplit('/', 1)[-1], request.headers.get('idempotency-key')))
            if request.method == 'POST' and request.url.rsplit('/', 1)[-1] in {'plan', 'author'} else None)
    page.goto(BASE + '/ai-studio')
    page.wait_for_load_state('networkidle')
    fill(page, 'Tự động một nút')
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('#export-pptx')).to_be_visible()
    expect(page.locator('#slide-list button')).to_have_count(15)
    assert [kind for kind, _ in calls] == ['plan', 'author', 'author', 'author']
    assert len({key for _, key in calls}) == 4
    page.reload()
    expect(page.locator('#export-pptx')).to_be_visible()
    assert len(calls) == 4, 'Reload must not start extra inference'
    checks.append('one click saves 15 slides in three author batches; reload starts no inference')

    calls.clear()
    fill(page, 'Chỉ xem dàn ý', 5)
    page.get_by_role('button', name='Tạo dàn ý bằng AI', exact=True).click()
    expect(page.locator('#deck-status')).to_contain_text('Đã có dàn ý')
    expect(page.locator('#export-pptx')).not_to_be_visible()
    assert [kind for kind, _ in calls] == ['plan']
    checks.append('outline-only action retains the existing review-first path')

    calls.clear()
    def warn(route):
        response = route.fetch()
        data = response.json()
        data['status'] = 'needs_review'
        data['blueprint']['warnings'] = ['Cảnh báo fixture cần rà soát']
        route.fulfill(response=response, json=data)
    page.route('**/api/ai-slides/decks/*/plan', warn)
    fill(page, 'Tự động dừng để rà soát', 5)
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('#outline-review')).to_contain_text('Cảnh báo fixture')
    assert [kind for kind, _ in calls] == ['plan']
    page.locator('#outline-review button').click()
    expect(page.locator('#export-pptx')).to_be_visible()
    assert [kind for kind, _ in calls] == ['plan', 'author']
    page.unroute('**/api/ai-slides/decks/*/plan', warn)
    checks.append('automatic flow pauses on outline warning and authors only after explicit approval')

    calls.clear()
    authors = [0]
    def fail_second(route):
        authors[0] += 1
        if authors[0] == 2:
            route.fulfill(status=503, json={'code': 'AI_TIMEOUT', 'message': 'Timeout mô phỏng'})
        else:
            route.continue_()
    page.route('**/api/ai-slides/decks/*/author', fail_second)
    fill(page, 'Tiếp tục sau lỗi giữa bài')
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('#studio-message')).to_contain_text('AI_TIMEOUT')
    expect(page.locator('#slide-list button')).to_have_count(5)
    assert authors[0] == 2
    page.reload()
    expect(page.locator('#slide-list button')).to_have_count(5)
    assert authors[0] == 2
    page.locator('#continue-deck').click()
    expect(page.locator('#export-pptx')).to_be_visible()
    expect(page.locator('#slide-list button')).to_have_count(15)
    assert authors[0] == 4
    assert [kind for kind, _ in calls].count('plan') == 1
    page.unroute('**/api/ai-slides/decks/*/author', fail_second)
    checks.append('timeout preserves five saved slides, never retries automatically and resumes remaining batches')

    calls.clear()
    fill(page, 'Chặn nguồn trước tự động', 5)
    page.locator('details').filter(has=page.locator('#pasted-source')).locator('summary').click()
    page.locator('#pasted-source').fill('I = U/R.\nI = U*R.')
    page.locator('#add-paste').click()
    page.locator('#cloud-consent').check()
    page.get_by_role('button', name='Tạo PowerPoint bằng AI', exact=True).click()
    expect(page.locator('#source-review')).to_be_visible()
    assert calls == []
    checks.append('unresolved source conflict prevents all automatic inference')
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(OUT / 'automatic-generation-mobile.png'), full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert not errors, errors
    checks.append('automatic controls and review state fit mobile without JavaScript errors')
    browser.close()
(OUT / 'workflow-headless-report.json').write_text(json.dumps({'checks': checks, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': len(checks), 'checks': checks}, ensure_ascii=True))
