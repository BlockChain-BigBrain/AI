"""Real HTTP storage round trip with SQLite or an explicitly supplied test MySQL DB."""
import json
import os
from pathlib import Path
import subprocess
import time
import requests

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/'layer2/artifacts'

def main():
    database=os.environ.get('TEST_DATABASE_URL','')
    kind='mysql' if database else 'sqlite'
    runtime=ROOT/'.runtime-tests'/f'storage-{kind}-{time.time_ns()}'
    runtime.mkdir(parents=True)
    env={**os.environ,'DATABASE_URL':database,'TRACK_AI_RUNTIME':str(runtime),'PORT':'3200',
         'TRACK_AI_URL':'http://127.0.0.1:8199','TRACK_AI_API_KEY':'isolated-test-only'}
    base='http://127.0.0.1:3200'
    summary={'status':'running','database':kind}
    log=(runtime/'server.log').open('w',encoding='utf-8')
    p=subprocess.Popen([str(ROOT/'.tools/node/node.exe'),'--import','./backend/node_modules/tsx/dist/loader.mjs','backend/src/server.ts'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def get(path):
        r=requests.get(base+path,timeout=10);r.raise_for_status();return r.json()
    def post(path,body):
        r=requests.post(base+path,json=body,timeout=10);r.raise_for_status();return r.json()
    try:
        for _ in range(60):
            if p.poll() is not None:raise RuntimeError('Backend startup failed; see isolated runtime log')
            try:
                if requests.get(base+'/',timeout=1).ok:break
            except requests.RequestException:pass
            time.sleep(.5)
        r=requests.post(base+'/api/tracks',files={'file':('storage-check.wav',b'invalid-audio')},timeout=10)
        assert r.status_code==202,r.text
        tid=r.json()['trackId']
        for _ in range(40):
            track=get('/api/tracks/'+tid)
            if track['state']=='FAILED':break
            time.sleep(.25)
        assert track['state']=='FAILED'
        url='/api/tracks/'+tid
        first=post(url+'/provenance',{'manifest':{'title':'한글 저장 검증','version':1}})
        second=post(url+'/provenance',{'manifest':{'title':'한글 저장 검증','version':2}})
        assert first['manifestHash']!=second['manifestHash']
        assert get(url+'/provenance')['manifest']['version']==2
        post(url+'/contributors',{'contributors':[{'walletAddress':'test-wallet-a','shareBps':6000},{'walletAddress':'test-wallet-b','shareBps':4000}]})
        assert len(get(url+'/contributors')['contributors'])==2
        duplicate=requests.post(base+url+'/contributors',json={'contributors':[{'walletAddress':'same','shareBps':5000},{'walletAddress':'same','shareBps':5000}]},timeout=10)
        assert duplicate.status_code==422
        assert len(get(url+'/contributors')['contributors'])==2
        rejected=requests.post(base+url+'/contributors',json={'contributors':[{'walletAddress':'test','shareBps':1}]},timeout=10)
        assert rejected.status_code==422
        assert len(get(url+'/contributors')['contributors'])==2
        quote=post(url+'/settlement-quote',{'grossAmount':'10000','feeBps':1000})
        assert quote['netAmount']=='9000'
        assert sorted(x['amount'] for x in quote['payouts'])==['3600','5400']
        post(url+'/review',{'status':'NEEDS_INFO','note':'로컬 운영 시험'})
        assert get(url)['review']['status']=='NEEDS_INFO'
        get('/api/reviews/pending')
        summary={'status':'passed','database':kind,'checks':['upload_failed_state_persisted','unicode_provenance_roundtrip',
                 'provenance_upsert','contributor_rows','duplicate_wallet_rejected','invalid_share_preserves_existing_rows','settlement_quote','review_roundtrip','pending_review_query'],
                 'scope':'Isolated storage HTTP test. AI intentionally unavailable; not a successful AI E2E test.','runtime':str(runtime)}
    except Exception as exc:
        summary={'status':'failed','database':kind,'error':str(exc),'runtime':str(runtime)}
        raise
    finally:
        if p.poll() is None:p.terminate();p.wait(timeout=30)
        log.close()
        (ART/f'{kind}_storage_http_validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
