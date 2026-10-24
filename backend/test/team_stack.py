"""Actual team React/auth/Prisma/MySQL flow; optional real calibrated AI service."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import requests

ROOT=Path(__file__).resolve().parents[2]
TEAM=ROOT/'integrations'
ART=ROOT/'layer2/artifacts'
NODE=ROOT/'.tools/node-v22.23.4-win-x64/node.exe'
MYSQL=ROOT/'.tools/mysql-8.4.13-winx64'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live-ai',action='store_true');parser.add_argument('--ai-scope',action='store_true');parser.add_argument('--precision-rescue',action='store_true');args=parser.parse_args()
    if args.precision_rescue and not (args.live_ai and args.ai_scope):parser.error('--precision-rescue requires --live-ai --ai-scope')
    runtime=ROOT/'.runtime-tests'/f'team-stack-{time.time_ns()}';runtime.mkdir(parents=True)
    frontend_port=8444 if args.live_ai else 8443
    frontend=f'http://localhost:{frontend_port}/Frontend/'
    backend='http://localhost:4300'
    # Refuse before launching anything: connecting to an older test DB while
    # the new server is starting would invalidate isolation and ownership.
    for port in ([3308,4300,frontend_port,8100] if args.live_ai else [3308,4300,frontend_port]):
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.3):pass
        except OSError:continue
        raise RuntimeError(f'Test port {port} is already occupied; existing service was not changed.')
    key=secrets.token_urlsafe(32)
    env={**os.environ,'DATABASE_URL':'mysql://root@127.0.0.1:3308/track_ai_team_test',
         'JWT_ACCESS_SECRET':secrets.token_hex(64),'JWT_REFRESH_SECRET':secrets.token_hex(64),
         'NODE_ENV':'development','COOKIE_SECURE':'false','FRONTEND_URL':frontend,
         'GOOGLE_CALLBACK_URL':backend+'/api/v1/auth/callback/google','PORT':'4300',
         'UPLOAD_DIR':str(runtime/'uploads'),'TRACK_AI_API_KEY':key,
         'TRACK_AI_URL':'http://127.0.0.1:8100' if args.live_ai else 'http://127.0.0.1:8199',
         'PATH':str(NODE.parent)+';'+os.environ.get('PATH','')}
    processes=[];logs=[];engine=None;summary={'status':'running'};persisted_thresholds=None
    score_version='clap-top20+tonal-local-v1+expanded-square-v1' if args.ai_scope and (ART/'ai_improvement_policy.json').exists() else 'clap-top5+tonal-local-v1'
    if args.ai_scope and (ART/'ai_precision_policy.json').exists():score_version+='+'+'secondary-clap-cqt-fragments-v1'
    creation=getattr(subprocess,'CREATE_NO_WINDOW',0)
    def launch(command,cwd,child_env=env,name='server'):
        log=(runtime/f'{name}.log').open('w',encoding='utf-8');logs.append(log)
        p=subprocess.Popen(command,cwd=cwd,env=child_env,stdout=log,stderr=subprocess.STDOUT,creationflags=creation)
        processes.append(p);return p
    def wait_http(url,p):
        for _ in range(240):
            if p.poll() is not None:raise RuntimeError(f'Server exited: {url}; inspect {runtime}')
            try:
                if requests.get(url,timeout=2).ok:return
            except requests.RequestException:pass
            time.sleep(.5)
        raise TimeoutError(url)
    def run(command,cwd,child_env=env,name='command'):
        log=(runtime/f'{name}.log').open('w',encoding='utf-8');logs.append(log)
        subprocess.run(command,cwd=cwd,env=child_env,stdout=log,stderr=subprocess.STDOUT,check=True,creationflags=creation)
    try:
        common=['--basedir=.',f'--datadir={os.path.relpath(runtime/"mysql-data",MYSQL).replace(chr(92),"/")}', '--innodb-buffer-pool-size=64M','--innodb-redo-log-capacity=64M']
        log=(runtime/'mysql-init.log').open('w',encoding='utf-8');logs.append(log)
        subprocess.run(['mysqld','--no-defaults','--initialize-insecure',*common],executable=str(MYSQL/'bin/mysqld.exe'),cwd=MYSQL,stdout=log,stderr=subprocess.STDOUT,check=True,creationflags=creation)
        log=(runtime/'mysql.log').open('w',encoding='utf-8');logs.append(log)
        engine=subprocess.Popen(['mysqld','--no-defaults','--console',*common,'--bind-address=127.0.0.1','--port=3308','--mysqlx=0','--skip-log-bin'],executable=str(MYSQL/'bin/mysqld.exe'),cwd=MYSQL,stdout=log,stderr=subprocess.STDOUT,creationflags=creation)
        for _ in range(90):
            if engine.poll() is not None:raise RuntimeError('MySQL startup failed')
            try:
                with socket.create_connection(('127.0.0.1',3308),timeout=1):break
            except OSError:time.sleep(.5)
        create_code="import mysql from './backend/node_modules/mysql2/promise.js'; const c=await mysql.createConnection('mysql://root@127.0.0.1:3308'); const [rows]=await c.query('SELECT @@datadir AS path'); if(!rows[0].path.includes("+json.dumps(runtime.name)+"))throw Error('Test DB directory mismatch'); await c.query('CREATE DATABASE track_ai_team_test CHARACTER SET utf8mb4'); await c.end();"
        run([str(NODE),'--input-type=module','-e',create_code],ROOT,name='create-database')
        run([str(NODE),'node_modules/prisma/build/index.js','migrate','deploy'],TEAM/'Backend',name='prisma-migrations')
        if args.live_ai:
            api_env={**env,'TRACK_AI_RUNTIME':str(runtime/'ai'),'TRACK_AI_PORT':'8100','TRACK_AI_SCOPE':'ai_labeled' if args.ai_scope else 'all'}
            api=launch([sys.executable,'api/server.py'],ROOT,api_env,'ai')
            wait_http('http://127.0.0.1:8100/health',api)
        server=launch([str(NODE),'dist/server.js'],TEAM/'Backend',name='team-backend')
        wait_http(backend+'/health',server)
        vite_env={**os.environ,'PORT':str(frontend_port),'VITE_API_BASE_URL':backend,'VITE_LOCAL_LOGIN':'true','PATH':env['PATH']}
        vite=launch([str(NODE),'node_modules/vite/bin/vite.js','--host','localhost','--port',str(frontend_port),'--strictPort'],TEAM/'Frontend',vite_env,'team-frontend')
        wait_http(frontend,vite)
        sys.path.insert(0,str(ROOT/'.tools/python'))
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1100})
            account={'email':f'team-{time.time_ns()}@example.test','password':secrets.token_urlsafe(24),'nickname':'연동 검증'}
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(frontend,wait_until='domcontentloaded',timeout=60000)
            panel=page.get_by_test_id('local-account')
            panel.get_by_role('button',name='로컬 계정 만들기',exact=True).click()
            panel.get_by_label('이메일',exact=True).fill(account['email'])
            panel.get_by_label('비밀번호',exact=True).fill(account['password'])
            panel.get_by_label('닉네임',exact=True).fill(account['nickname'])
            panel.get_by_role('button',name='로컬 가입 후 로그인',exact=True).click()
            page.get_by_role('button',name='로그아웃',exact=True).wait_for(timeout=30000)
            cookies=context.cookies(backend+'/api/v1/auth/refresh')
            assert any(c['httpOnly'] for c in cookies), 'Missing HttpOnly auth cookie'
            page.get_by_role('button',name='Upload',exact=True).click()
            expected_source=None
            if args.precision_rescue:
                source=ROOT/'layer2/test_data/five_family_ai/001__long_auto_edit.wav'
                manifest=json.loads((ROOT/'layer2/test_data/five_family_ai/manifest.json').read_text(encoding='utf-8'))
                expected_source=next(r['expected_track_id'] for r in manifest['rows'] if Path(r['file'])==source)
            elif args.live_ai and args.ai_scope:
                source=Path(json.loads((ART/'pixabay_provenance/ai_label_allowlist.json').read_text(encoding='utf-8'))['original_music'][0]['file'])
            else:
                source=next((ROOT/'original_music').glob('*.mp3')) if args.live_ai else runtime/'invalid.wav'
            if not args.live_ai:source.write_bytes(b'invalid audio')
            page.locator('#track-file').set_input_files(str(source))
            page.get_by_role('button',name='AI 검증 시작',exact=True).click()
            expected='WARN' if args.precision_rescue else 'BLOCK' if args.live_ai else '분석 실패'
            page.locator('[data-testid=verification-decision]').filter(has_text=expected).wait_for(timeout=180000)
            if args.live_ai and args.ai_scope:
                page.get_by_test_id('verification-panel').get_by_text('검색 기준: Pixabay AI 표시 확인군 34곡.',exact=False).wait_for()
            if args.precision_rescue:
                page.get_by_test_id('verification-panel').get_by_text(expected_source,exact=False).wait_for()
            assert page.get_by_text('온체인 등록 완료!',exact=True).count()==0
            track_id=page.evaluate('Number(sessionStorage.getItem("track-ai-last-upload"))')
            assert isinstance(track_id,int) and track_id>0
            storage=page.evaluate('({local:Object.keys(localStorage), session:Object.keys(sessionStorage)})')
            assert all('token' not in k.lower() for k in storage['local']+storage['session'])
            page.screenshot(path=str(ART/('team_upload_live_desktop.png' if args.live_ai else 'team_upload_failed_desktop.png')),full_page=True)
            page.reload(wait_until='domcontentloaded',timeout=60000)
            page.get_by_role('button',name='Upload',exact=True).click()
            page.locator('[data-testid=verification-decision]').filter(has_text=expected).wait_for(timeout=30000)
            if not args.live_ai:
                page.get_by_role('button',name='다시 분석',exact=True).click()
                page.locator('[data-testid=verification-decision]').filter(has_text='분석 실패').wait_for(timeout=30000)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
            page.screenshot(path=str(ART/('team_upload_live_mobile.png' if args.live_ai else 'team_upload_failed_mobile.png')),full_page=True)
            assert not errors,errors
            database_status='VERIFIED' if args.precision_rescue else 'REJECTED' if args.live_ai else 'FAILED'
            result_check='assert.equal(v.resultJson.decision,'+json.dumps(expected)+');assert.ok(v.aiJobId);' if args.live_ai else 'assert.equal(v.decision,null);'
            if args.precision_rescue:
                result_check+='const s=v.resultJson.similarTracks.find(s=>s.trackId==='+json.dumps(expected_source)+');assert.ok(s);assert.equal(s.matchedSegments.length,3);assert.equal(v.riskStatus,"WARN");'
            check_code=f"const{{PrismaClient}}=require('@prisma/client');const assert=require('node:assert/strict');(async()=>{{const db=new PrismaClient();const v=await db.verification.findFirst({{where:{{trackId:{track_id}}},orderBy:{{id:'desc'}}}});assert.equal(v.status,'{database_status}');assert.equal(v.source,'AI');assert.equal(await db.track.count(),1);assert.equal(await db.verification.count({{where:{{trackId:{track_id}}}}}),{1 if args.live_ai else 2});{result_check}await db.$disconnect();}})().catch(e=>{{console.error(e.name);process.exitCode=1;}});"
            run([str(NODE),'-e',check_code],TEAM/'Backend',name='verify-prisma-rows')
            parallel_validation=None
            if args.precision_rescue:
                from concurrent.futures import ThreadPoolExecutor
                def parallel_job(index):
                    started=time.perf_counter()
                    with source.open('rb') as audio:
                        accepted=requests.post('http://127.0.0.1:8100/verify',headers={'X-Internal-API-Key':key},
                            data={'trackId':f'parallel-{index}','requestId':f'parallel-{index}-{time.time_ns()}'},
                            files={'file':(source.name,audio,'audio/wav')},timeout=30)
                    accepted.raise_for_status();job=accepted.json()['jobId']
                    for _ in range(360):
                        response=requests.get('http://127.0.0.1:8100/verify/'+job,headers={'X-Internal-API-Key':key},timeout=10)
                        response.raise_for_status();payload=response.json()
                        if payload['state']=='FAILED':raise AssertionError('Parallel precision analysis failed.')
                        if payload['state']=='SUCCEEDED':
                            result=payload['result'];assert result['decision']=='WARN'
                            candidate=next(c for c in result['similarTracks'] if c['trackId']==expected_source)
                            assert len(candidate['matchedSegments'])==3
                            return {'decision':result['decision'],'elapsed_seconds':round(time.perf_counter()-started,3),'processing_seconds':result['processingSeconds']}
                        time.sleep(.5)
                    raise TimeoutError('Parallel precision queue did not drain.')
                with ThreadPoolExecutor(max_workers=2) as pool:parallel_validation=list(pool.map(parallel_job,range(2)))
            if args.live_ai:
                version_check="const{PrismaClient}=require('@prisma/client');(async()=>{const p=new PrismaClient();const v=await p.verification.findFirst({orderBy:{id:'desc'}});if(v.resultJson.scoreVersion!=="+json.dumps(score_version)+")throw Error('Wrong score version');await p.$disconnect()})().catch(()=>process.exitCode=1)"
                run([str(NODE),'-e',version_check],TEAM/'Backend',name='verify-tonal-version')
                if args.ai_scope:
                    run([str(NODE),'-e',"const{PrismaClient}=require('@prisma/client');(async()=>{const p=new PrismaClient();const v=await p.verification.findFirst({orderBy:{id:'desc'}});if(v.resultJson.evaluationScope!=='ai_labeled'||v.resultJson.referenceTracks!==34||v.resultJson.pureAiCreationVerified!==false)throw Error('Wrong AI scope evidence');await p.$disconnect()})().catch(()=>process.exitCode=1)"],TEAM/'Backend',name='verify-ai-scope')
                    improved=ART/'ai_improvement_policy.json'
                    if (ART/'ai_precision_policy.json').exists():improved=ART/'ai_precision_policy.json'
                    if improved.exists():
                        policy=json.loads(improved.read_text(encoding='utf-8'))
                        checks=f"const{{PrismaClient}}=require('@prisma/client');(async()=>{{const p=new PrismaClient();const v=await p.verification.findFirst({{orderBy:{{id:'desc'}}}});const t=v.resultJson.thresholds;if(!Number.isFinite(t.warn)||!Number.isFinite(t.hold)||Math.abs(t.warn-{policy['warn_threshold']})>1e-12||Math.abs(t.hold-{policy['hold_threshold']})>1e-12)throw Error('Wrong calibrated thresholds persisted');console.log(JSON.stringify(t));await p.$disconnect()}})().catch(e=>{{console.error(e.message);process.exitCode=1}})"
                        run([str(NODE),'-e',checks],TEAM/'Backend',name='verify-improved-thresholds')
                        persisted_thresholds=json.loads((runtime/'verify-improved-thresholds.log').read_text(encoding='utf-8').strip())
            # A different authenticated account must not inspect or retry the owner's job.
            other=pw.request.new_context()
            account2={**account,'email':f'other-{time.time_ns()}@example.test'}
            assert other.post(backend+'/api/v1/auth/signup',data=account2).status==201
            login=other.post(backend+'/api/v1/auth/login?target=frontend',data={k:account2[k] for k in ('email','password')})
            token=login.json()['result']['accessToken']
            for method,url in [('get',f'/api/tracks/{track_id}/verification'),('post',f'/api/tracks/{track_id}/verify'),('delete',f'/api/tracks/{track_id}')]:
                forbidden=getattr(other,method)(backend+url,headers={'Authorization':'Bearer '+token});assert forbidden.status==403
            other.dispose()
            page.get_by_role('button',name='로그아웃',exact=True).click()
            page.wait_for_function('sessionStorage.getItem("track-ai-last-upload") === null')
            revoked=context.request.post(backend+'/api/v1/auth/refresh?target=frontend',headers={'Origin':frontend.rstrip('/').split('/Frontend')[0]})
            assert revoked.status==401
            context.close();browser.close()
        summary={'status':'passed','scope':'actual team React + auth API + Prisma + isolated MySQL',
                 'ai_score_version':score_version if args.live_ai else None,
                 'evaluation_scope':'ai_labeled' if args.ai_scope else 'all',
                 'ai_scope':'actual calibrated FastAPI exact-duplicate BLOCK' if args.live_ai else 'AI unavailable: FAILED persisted and displayed; not a successful AI analysis',
                 'checks':['React local account signup/login','HttpOnly cookie restoration','authenticated multipart upload','Prisma/MySQL verification persistence',
                           'actual result displayed','refresh restores result','no tokens in web storage','no fabricated Mint completion',
                           'owner-only verification/retry/delete','desktop and mobile browser checks','logout clears cookie session and saved track lookup'],
                 'retry_test':'same track verified in failure-path test' if args.live_ai else 'passed; same track, two verification records',
                 'google_cloud_login':'not_exercised; existing auth tests passed, live client credentials not supplied',
                 'production_database':'not_accessed','production_push':'not_performed','runtime':str(runtime)}
        if args.live_ai and args.ai_scope and (ART/'ai_improvement_policy.json').exists():
            summary['active_policy_file']='ai_improvement_policy.json'
            if (ART/'ai_precision_policy.json').exists():summary['active_policy_file']='ai_precision_policy.json'
            summary['thresholds']=json.loads((ART/'ai_improvement_policy.json').read_text(encoding='utf-8'))
            summary['thresholds']={k:summary['thresholds'][k+'_threshold'] for k in ('warn','hold')}
            summary['persisted_thresholds']=persisted_thresholds
            summary['database_float_comparison_tolerance']=1e-12
            summary['checks'].append('improved WARN/HOLD thresholds persisted in actual MySQL result JSON')
        if args.precision_rescue:
            summary['ai_scope']='actual long-edit supplemental WARN with three reference/query fragments'
            summary['checks'].append('previously missed 120s edit recovered as WARN, three matching fragments persisted and displayed')
            summary['precision_rescue_e2e']=True
            summary['parallel_precision_api_jobs']=parallel_validation
    except Exception as exc:
        summary={'status':'failed','error':str(exc),'runtime':str(runtime)}
        raise
    finally:
        for p in reversed(processes):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=30)
                except subprocess.TimeoutExpired:p.kill()
        if engine and engine.poll() is None:
            subprocess.run(['mysqladmin','--no-defaults','--host=127.0.0.1','--port=3308','--user=root','shutdown'],executable=str(MYSQL/'bin/mysqladmin.exe'),cwd=MYSQL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,creationflags=creation)
            try:engine.wait(timeout=30)
            except subprocess.TimeoutExpired:engine.terminate()
        for log in logs:log.close()
        filename='team_live_ai_e2e_validation.json' if args.live_ai else 'team_frontend_integration_validation.json'
        (ART/filename).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        sys.path.insert(0,str(ROOT/'layer2'))
        from write_run_summary import main as update_summary
        update_summary()
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
