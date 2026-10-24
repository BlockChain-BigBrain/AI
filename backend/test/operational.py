"""Real Node -> FastAPI -> CLAP -> SQLite operations checks, isolated runtime."""
import concurrent.futures
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import requests

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/'layer2/artifacts'
RUNTIME=ROOT/'.runtime-tests'/time.strftime('%Y%m%d_%H%M%S')
NODE=ROOT/'.tools/node/node.exe'
BASE='http://127.0.0.1:3100'
AI='http://127.0.0.1:8100'

def wait_ready(url, process, timeout=240):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError(f'Server exited: {process.returncode}')
        try:
            r=requests.get(url,timeout=4)
            if r.ok:return r.json()
        except requests.RequestException:pass
        time.sleep(1)
    raise TimeoutError(f'Not ready: {url}')

def upload(path, expected=None):
    started=time.monotonic()
    with path.open('rb') as f:r=requests.post(BASE+'/api/tracks',files={'file':(path.name,f)},timeout=120)
    assert r.status_code==202,r.text
    accepted=r.json()
    while time.monotonic()-started<1800:
        r=requests.get(BASE+accepted['statusUrl'],timeout=10);r.raise_for_status();track=r.json()
        if track['state'] in {'VERIFIED','FAILED'}:
            if expected=='FAILED':assert track['state']=='FAILED',track
            else:
                assert track['state']=='VERIFIED',track
                if expected:assert track['decision']==expected,track
            return {'file':path.name,'track_id':accepted['trackId'],'state':track['state'],
                    'decision':track['decision'],'wall_seconds':round(time.monotonic()-started,3),
                    'processing_seconds':(track.get('result') or {}).get('processingSeconds'),
                    'query_windows':(track.get('result') or {}).get('queryWindowCount')}
        time.sleep(.5)
    raise TimeoutError(path.name)

def main():
    RUNTIME.mkdir(parents=True)
    api_runtime=RUNTIME/'api';node_runtime=RUNTIME/'node'
    key=secrets.token_urlsafe(32)
    env=os.environ.copy();env['TRACK_AI_API_KEY']=key
    api_env={**env,'TRACK_AI_RUNTIME':str(api_runtime),'TRACK_AI_PORT':'8100','TRACK_AI_SCOPE':'all'}
    node_env={**env,'TRACK_AI_RUNTIME':str(node_runtime),'TRACK_AI_URL':AI,'PORT':'3100','DATABASE_URL':''}
    creation=getattr(subprocess,'CREATE_NO_WINDOW',0)
    logs=[];processes=[]
    def start_node():
        log=(RUNTIME/f'node_{len(logs)}.log').open('w',encoding='utf-8');logs.append(log)
        p=subprocess.Popen([str(NODE),'--import','./backend/node_modules/tsx/dist/loader.mjs','backend/src/server.ts'],cwd=ROOT,env=node_env,stdout=log,stderr=subprocess.STDOUT,creationflags=creation)
        processes.append(p);return p
    def start_api():
        log=(RUNTIME/f'api_{len(logs)}.log').open('w',encoding='utf-8');logs.append(log)
        p=subprocess.Popen([sys.executable,'api/server.py'],cwd=ROOT,env=api_env,stdout=log,stderr=subprocess.STDOUT,creationflags=creation)
        processes.append(p);return p
    summary={'status':'running','runtime':str(RUNTIME)}
    try:
        api=start_api()
        health=wait_ready(AI+'/health',api)
        assert health['referenceTracks']==1000,health
        node=start_node();wait_ready(BASE+'/health',node)
        assert requests.get(BASE+'/',timeout=10).status_code==200
        original=next((ROOT/'original_music').glob('*.mp3'))
        results=[upload(original,'BLOCK')]
        from imageio_ffmpeg import get_ffmpeg_exe
        controls=sorted((ROOT/'music').glob('*.mp3'))[:3]
        long_files=[]
        for i,source in enumerate(controls):
            dest=RUNTIME/f'normal_180s_{i}.wav'
            subprocess.run([get_ffmpeg_exe(),'-v','error','-nostdin','-stream_loop','-1','-i',str(source),'-t','180','-ac','1','-ar','22050',str(dest)],check=True)
            long_files.append(dest)
            results.append(upload(dest))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results.extend(pool.map(upload,long_files[:2]))
        malformed=RUNTIME/'malformed.wav';malformed.write_bytes(b'not an audio file')
        results.append(upload(malformed,'FAILED'))
        bad=requests.post(BASE+'/api/tracks',files={'file':('unsupported.txt',b'test')},timeout=10)
        assert bad.status_code==422,bad.text
        headers={'X-Internal-API-Key':key}
        data={'trackId':'ops-idempotency','requestId':'ops-idempotency'}
        with original.open('rb') as f:r=requests.post(AI+'/verify',data=data,files={'file':(original.name,f)},headers=headers,timeout=120)
        assert r.status_code==202,r.text
        with original.open('rb') as f:r2=requests.post(AI+'/verify',data=data,files={'file':(original.name,f)},headers=headers,timeout=120)
        assert r2.status_code==202 and r.json()['jobId']==r2.json()['jobId']
        with original.open('rb') as f:conflict=requests.post(AI+'/verify',data={**data,'trackId':'different'},files={'file':(original.name,f)},headers=headers,timeout=120)
        assert conflict.status_code==409,conflict.text
        unauthorized=requests.post(AI+'/verify',data=data,files={'file':('x.wav',b'x')},timeout=10)
        assert unauthorized.status_code==401,unauthorized.text
        # Confirm durable rows directly, rather than treating HTTP success as persistence.
        with sqlite3.connect(node_runtime/'tracks.sqlite3') as db:
            for item in results:
                row=db.execute('SELECT state,decision FROM tracks WHERE id=?',(item['track_id'],)).fetchone()
                assert row==(item['state'],item['decision'])
            db.execute("INSERT INTO tracks(id,original_name,state,created_at,updated_at) VALUES('restart-fixture','fixture','ANALYZING',datetime('now'),datetime('now'))")
        node.terminate();node.wait(timeout=30)
        node=start_node();wait_ready(BASE+'/health',node)
        persisted=requests.get(BASE+'/api/tracks/'+results[0]['track_id'],timeout=10).json()
        assert persisted['decision']=='BLOCK'
        interrupted=requests.get(BASE+'/api/tracks/restart-fixture',timeout=10).json()
        assert interrupted['state']=='FAILED' and interrupted['error']=='BACKEND_RESTARTED'
        ai_job_id=persisted['aiJobId']
        with sqlite3.connect(api_runtime/'jobs.sqlite3') as db:
            db.execute("INSERT INTO jobs VALUES ('api-restart-fixture','fixture','fixture','PENDING',NULL,NULL,'api-restart-fixture')")
        api.terminate();api.wait(timeout=30)
        api=start_api();wait_ready(AI+'/health',api)
        saved_job=requests.get(AI+'/verify/'+ai_job_id,headers=headers,timeout=10).json()
        assert saved_job['state']=='SUCCEEDED'
        interrupted_api=requests.get(AI+'/verify/api-restart-fixture',headers=headers,timeout=10).json()
        assert interrupted_api['state']=='FAILED' and interrupted_api['error']=='SERVER_RESTARTED'
        time.sleep(2)
        assert not list((node_runtime/'uploads').glob('*'))
        assert not list(api_runtime.glob('*.upload.*'))
        browser={'status':'not_run'}
        if (ROOT/'.tools/python').is_dir():
            sys.path.insert(0,str(ROOT/'.tools/python'))
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser_process=pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
                page=browser_process.new_page(viewport={'width':1280,'height':1000})
                page.goto(BASE,wait_until='networkidle')
                page.locator('#file').set_input_files(str(original))
                page.locator('#submit').click()
                page.locator('#decision').filter(has_text='BLOCK').wait_for(timeout=120000)
                page.screenshot(path=str(ART/'upload_e2e_desktop.png'),full_page=True)
                trackid=page.locator('#trackid').inner_text()
                page.reload();page.locator('#lookup-id').fill(trackid);page.locator('#lookup button').click()
                page.locator('#decision').filter(has_text='BLOCK').wait_for(timeout=30000)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(ART/'upload_e2e_mobile.png'),full_page=True)
                browser_process.close();browser={'status':'passed','upload_decision':'BLOCK','reload_lookup':'passed','mobile_overflow':'none'}
        time.sleep(1)
        assert not list((node_runtime/'uploads').glob('*'))
        assert not list(api_runtime.glob('*.upload.*'))
        latency=[r['wall_seconds'] for r in results if r['file'].startswith('normal_180s')]
        summary={'status':'passed','reference_tracks':1000,'score_version':health['scoreVersion'],'samples':results,
                 'three_minute_latency':{'n':len(latency),'p50_seconds':float(np.percentile(latency,50)),
                                        'p95_seconds':float(np.percentile(latency,95)),'note':'Five requests from three distinct 180s controls, including two concurrent requests; not a production SLA'},
                 'checks':{'sqlite_persistence':'passed','node_restart_persistence':'passed','interrupted_job_recovery':'passed',
                           'api_restart_persistence':'passed','api_interrupted_job_recovery':'passed',
                           'concurrent_uploads':'passed (two 180s nonduplicate controls)','malformed_audio':'FAILED as expected',
                           'unsupported_extension':'rejected','idempotency':'passed','request_conflict':'409',
                           'unauthorized':'401','temporary_upload_cleanup':'passed'},'browser':browser,
                 'team_mysql_connection':'not_tested: connection settings not provided','runtime':str(RUNTIME)}
    except Exception as exc:
        summary={'status':'failed','error':str(exc),'runtime':str(RUNTIME)}
        raise
    finally:
        (ART/'operational_test_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        sys.path.insert(0,str(ROOT/'layer2'))
        from write_run_summary import main as update_summary
        update_summary()
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=30)
                except subprocess.TimeoutExpired:p.kill()
        for log in logs:log.close()
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
