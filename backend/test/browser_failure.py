"""Exercise the real upload screen and durable FAILED state while AI is unavailable."""
import json
import sqlite3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.tools/python'))
from playwright.sync_api import sync_playwright

def main():
    runtime=ROOT/'.runtime-tests/browser-failure';runtime.mkdir(parents=True,exist_ok=True)
    sample=runtime/'invalid.wav';sample.write_bytes(b'not valid audio')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1280,'height':1000})
        page.goto('http://127.0.0.1:3000/',wait_until='networkidle')
        page.locator('#file').set_input_files(str(sample));page.locator('#submit').click()
        page.locator('#message').filter(has_text='분석 실패').wait_for(timeout=45000)
        assert page.locator('#result').is_hidden()
        assert page.locator('#submit').is_enabled()
        trackid=page.locator('#lookup-id').input_value()
        with sqlite3.connect(ROOT/'backend/runtime/tracks.sqlite3') as db:
            assert db.execute('SELECT state FROM tracks WHERE id=?',(trackid,)).fetchone()==('FAILED',)
        page.screenshot(path=str(ROOT/'layer2/artifacts/upload_failure_desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(ROOT/'layer2/artifacts/upload_failure_mobile.png'),full_page=True)
        browser.close()
    result={'status':'passed','scope':'Real browser -> Node -> unavailable AI error -> SQLite FAILED; success path remains queued after full evaluation',
            'failed_job_persisted':True,'failure_not_shown_as_pass':True,'retry_button_enabled':True,'mobile_horizontal_overflow':False}
    (ROOT/'layer2/artifacts/browser_failure_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
