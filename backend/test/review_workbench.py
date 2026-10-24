"""Browser check of the local listening workbench, not a musical review."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.tools/python'))
from playwright.sync_api import sync_playwright


def main():
    runtime = ROOT / '.runtime-tests' / f'review-browser-{time.time_ns()}'
    runtime.mkdir(parents=True)
    expected_count = json.loads((ROOT / 'layer2/artifacts/listening_review_preparation.json').read_text(encoding='utf-8'))['cases']
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        context = browser.new_context(viewport={'width': 1200, 'height': 900}, accept_downloads=True)
        page = context.new_page(); errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto((ROOT / 'review_workbench/index.html').as_uri(), wait_until='domcontentloaded')
        page.wait_for_function('document.querySelector("#q").readyState >= 1 && document.querySelector("#r").readyState >= 1')
        assert str(expected_count) in page.locator('#count').inner_text()
        page.screenshot(path=str(ROOT / 'layer2/artifacts/listening_review_desktop.png'), full_page=True)
        page.locator('#reviewer').fill('브라우저 동작 시험 · 음악적 판단 아님')
        page.locator('#label').select_option('uncertain')
        page.locator('#notes').fill('UI 저장·복원 확인용 임시 기록')
        page.locator('#save').click()
        page.locator('#next').click(); page.locator('#prev').click()
        assert page.locator('#label').input_value() == 'uncertain'
        assert page.locator('#notes').input_value() == 'UI 저장·복원 확인용 임시 기록'
        with page.expect_download() as downloaded: page.locator('#export').click()
        downloaded.value.save_as(str(runtime / 'review-test-export.json'))
        data = json.loads((runtime / 'review-test-export.json').read_text(encoding='utf-8'))
        assert len(data['items']) == expected_count and data['notLegalVerdicts']
        assert sum(r['humanReview']['label'] != 'pending' for r in data['items']) == 1
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        context.close(); browser.close()
    (ROOT / 'layer2/artifacts/listening_review_browser_validation.json').write_text(json.dumps({
        'status': 'passed', 'checks': ['two local audio metadata loaded', 'review save/restore', 'JSON export', 'mobile layout'],
        'human_listening': 'not_performed', 'test_records': 'isolated browser only, not applied to dataset'}, indent=2), encoding='utf-8')
    print('Listening workbench browser checks passed. No human labels applied.')


if __name__ == '__main__': main()
