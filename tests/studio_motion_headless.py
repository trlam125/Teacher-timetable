"""Exercise the actual export buttons with native QA flag enabled in harness."""
import json
from pathlib import Path
import zipfile
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tmp/ai-studio-qa';checks=[]

def timing(path):
 with zipfile.ZipFile(path) as z:
  xml=z.read('ppt/slides/slide1.xml').decode()
  return '<p:timing' in xml,'<p:transition' in xml

with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(accept_downloads=True)
 page.set_default_timeout(10000)
 page.goto('http://127.0.0.1:8766/ai-studio');page.wait_for_load_state('networkidle')
 page.locator('#new-deck').click()
 page.locator('[name=subject]').fill('Vật lí');page.locator('[name=grade]').fill('Lớp 9')
 title='QA hiệu ứng từ nút xuất'
 page.locator('[name=lesson_title]').fill(title);page.locator('[name=slide_count]').fill('5')
 page.locator('#cloud-consent').check();page.get_by_role('button',name='Tạo dàn ý bằng AI',exact=True).click()
 expect(page.locator('#deck-status')).to_contain_text('Đã có dàn ý')
 page.locator('#continue-deck').click()
 expect(page.locator('#export-pptx')).to_contain_text('có hiệu ứng')
 with page.expect_download() as pending:page.locator('#export-pptx').click()
 pending.value.save_as(OUT/'ui-native-motion.pptx')
 assert timing(OUT/'ui-native-motion.pptx')==(True,True)
 checks.append('native export button writes object timing and transitions after QA flag enabled')
 with page.expect_download() as pending:page.locator('#export-basic').click()
 pending.value.save_as(OUT/'ui-basic-choice.pptx')
 assert timing(OUT/'ui-basic-choice.pptx')==(False,False)
 checks.append('explicit basic export choice has no object timing or transitions')
 page.emulate_media(reduced_motion='reduce');page.reload()
 expect(page.locator('#export-pptx')).not_to_contain_text('có hiệu ứng')
 expect(page.locator('#motion-notice')).to_contain_text('giảm chuyển động')
 with page.expect_download() as pending:page.locator('#export-pptx').click()
 pending.value.save_as(OUT/'ui-reduced-motion.pptx')
 assert timing(OUT/'ui-reduced-motion.pptx')==(False,False)
 checks.append('reduced-motion preference disables native motion in actual download')
 context=browser.new_context(accept_downloads=True)
 failing=context.new_page()
 failing.route('**/motion-*.js',lambda route:route.abort())
 failing.goto('http://127.0.0.1:8766/ai-studio');failing.wait_for_load_state('networkidle')
 failing.locator('#deck-list button').filter(has_text=title).click()
 failing.locator('#export-pptx').click()
 expect(failing.locator('#studio-message')).to_contain_text('không hiệu ứng')
 expect(failing.locator('#motion-notice')).to_be_visible()
 with failing.expect_download() as pending:failing.locator('#export-basic').click()
 pending.value.save_as(OUT/'ui-motion-fallback.pptx')
 assert timing(OUT/'ui-motion-fallback.pptx')==(False,False)
 checks.append('native engine failure explains the issue and explicit basic download still works')
 browser.close()
report={'passed':len(checks),'checks':checks,'provider':'test-only fixture','desktop':'user-reported manual QA in separate three packs'}
(OUT/'motion-headless-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
