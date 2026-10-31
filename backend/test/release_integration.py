"""Latest upstream Backend -> real AI -> isolated MySQL evidence round trip.

Uses explicitly named workspace worktree and disposable local services only.
No production settings, Google login or blockchain transactions are touched.
"""
from pathlib import Path
import argparse,hashlib,json,os,secrets,shutil,socket,subprocess,sys,time
import requests

ROOT=Path(__file__).resolve().parents[2]
NODE=ROOT/'.tools/node-v22.23.4-win-x64/node.exe'
MYSQL=ROOT/'.tools/mysql-8.4.13-winx64'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--backend',type=Path,default=ROOT/'.runtime-tests/release-20261024/Backend');args=parser.parse_args()
    backend=args.backend.resolve();assert backend.is_relative_to(ROOT)
    for port in (3310,8124):
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.3):pass
        except OSError:continue
        raise RuntimeError(f'Release integration port {port} is occupied; no existing service stopped.')
    runtime=ROOT/'.runtime-tests'/f'release-live-{time.time_ns()}';runtime.mkdir(parents=True)
    uploads=runtime/'uploads';uploads.mkdir();source=ROOT/'layer2/test_data/five_family_ai/001__long_auto_edit.wav'
    shutil.copyfile(source,uploads/'precision.wav');digest=hashlib.sha256(source.read_bytes()).hexdigest()
    database='track_ai_release_'+str(time.time_ns());key=secrets.token_urlsafe(32)
    env={**os.environ,'PATH':str(NODE.parent)+';'+os.environ.get('PATH',''),
        'DATABASE_URL':f'mysql://root@127.0.0.1:3310/{database}',
        'JWT_ACCESS_SECRET':secrets.token_hex(64),'JWT_REFRESH_SECRET':secrets.token_hex(64),
        'TRACK_AI_API_KEY':key,'TRACK_AI_SCOPE':'ai_labeled','TRACK_AI_PORT':'8124','TRACK_AI_RUNTIME':str(runtime/'ai'),
        'AI_PROVIDER_MODE':'http','AI_API_URL':'http://127.0.0.1:8124','VERIFICATION_TIMEOUT_MS':'180000',
        'UPLOAD_DIR':str(uploads),'NODE_ENV':'development','EXPECTED_AUDIO_HASH':digest}
    processes=[];logs=[];summary={'status':'running'};mysql=None
    creation=getattr(subprocess,'CREATE_NO_WINDOW',0)
    def launch(command,cwd,name,executable=None):
        log=(runtime/(name+'.log')).open('w',encoding='utf-8');logs.append(log)
        p=subprocess.Popen(command,cwd=cwd,env=env,executable=executable,stdout=log,stderr=subprocess.STDOUT,creationflags=creation)
        processes.append(p);return p
    def run(command,cwd,name,executable=None,input=None):
        with (runtime/(name+'.log')).open('w',encoding='utf-8') as log:
            subprocess.run(command,cwd=cwd,env=env,executable=executable,input=input,text=True,stdout=log,stderr=subprocess.STDOUT,check=True,creationflags=creation)
    common=['--basedir=.',f'--datadir={os.path.relpath(runtime/"mysql-data",MYSQL).replace(chr(92),"/")}', '--innodb-buffer-pool-size=64M','--innodb-redo-log-capacity=64M']
    try:
        run(['mysqld','--no-defaults','--initialize-insecure',*common],MYSQL,'mysql-init',str(MYSQL/'bin/mysqld.exe'))
        mysql=launch(['mysqld','--no-defaults','--console',*common,'--bind-address=127.0.0.1','--port=3310','--mysqlx=0','--skip-log-bin'],MYSQL,'mysql',str(MYSQL/'bin/mysqld.exe'))
        for _ in range(180):
            if mysql.poll() is not None:raise RuntimeError('Owned MySQL exited.')
            try:
                with socket.create_connection(('127.0.0.1',3310),timeout=.2):break
            except OSError:time.sleep(.5)
        run(['mysql','--no-defaults','--host=127.0.0.1','--port=3310','--user=root'],MYSQL,'create-database',str(MYSQL/'bin/mysql.exe'),f'CREATE DATABASE {database} CHARACTER SET utf8mb4;')
        run([str(NODE),'node_modules/prisma/build/index.js','migrate','deploy'],backend,'migrations')
        api=launch([sys.executable,'api/server.py'],ROOT,'ai')
        for _ in range(300):
            if api.poll() is not None:raise RuntimeError('Owned AI exited.')
            try:
                if requests.get('http://127.0.0.1:8124/health',timeout=2).ok:break
            except requests.RequestException:pass
            time.sleep(.5)
        code=r'''
const assert=require('node:assert/strict');
const {PrismaClient}=require('@prisma/client');
const {RightsRepository}=require('./dist/repositories/rights.repository');
const {VerificationService}=require('./dist/services/verification.service');
const {HttpAiVerificationProvider,aiRequiresReview}=require('./dist/providers/http-ai.provider');
const {TrackFiles}=require('./dist/utils/trackFiles');
(async()=>{
 const db=new PrismaClient();
 try {
  const owner=await db.user.create({data:{email:'release-owner@example.test',name:'Release owner',provider:'LOCAL'}});
  const other=await db.user.create({data:{email:'release-other@example.test',name:'Release other',provider:'LOCAL'}});
  const track=await db.track.create({data:{title:'Precision long edit test',ownerId:owner.id,audioPath:'/uploads/precision.wav',mimeType:'audio/wav',audioHash:process.env.EXPECTED_AUDIO_HASH}});
  const repo=new RightsRepository(db),provider=new HttpAiVerificationProvider(process.env.AI_API_URL,process.env.TRACK_AI_API_KEY,new TrackFiles(process.env.UPLOAD_DIR),200);
  const service=new VerificationService(repo,provider,180000);
  const result=await service.request(track.id,owner.id);
  assert.equal(result.status,'VERIFIED');assert.equal(result.source,'AI');
  assert.ok(['WARN','HOLD'].includes(result.evidence.decision));assert.equal(aiRequiresReview(result.evidence),true);
  assert.equal(result.evidence.audioHash,process.env.EXPECTED_AUDIO_HASH);assert.equal(result.evidence.referenceTracks,34);
  const candidate=result.evidence.similarTracks.find(c=>c.trackId==='alex-morgan-arabic-islam-islamic-music-545530');
  assert.ok(candidate);assert.equal(candidate.matchedSegments.length,3);
  await assert.rejects(service.request(track.id,other.id,true),{statusCode:403});
  const unavailable=new VerificationService(repo,{source:'AI',verify:async()=>{throw Error('intentional unavailable-provider fixture');}},500);
  const failed=await unavailable.request(track.id,owner.id,true);
  assert.equal(failed.status,'REJECTED');assert.equal(failed.errorCode,'AI_ANALYSIS_FAILED');assert.equal(failed.evidence,null);
  console.log(JSON.stringify({status:'passed',decision:result.evidence.decision,scoreVersion:result.evidence.scoreVersion,
   storedSegments:candidate.matchedSegments.length,verificationRows:await db.verification.count(),
   realAiSuccess:true,explicitFailureFixture:true,reviewGatePreserved:true,ownerCheck:true}));
 } finally {await db.$disconnect();}
})().catch(e=>{console.error(e.name+': '+e.message);process.exitCode=1;});
'''
        run([str(NODE),'-e',code],backend,'provider-roundtrip')
        evidence=json.loads((runtime/'provider-roundtrip.log').read_text(encoding='utf-8').strip().splitlines()[-1])
        summary={**evidence,'scope':'latest upstream Backend HTTP provider + real calibrated AI + fresh isolated MySQL',
            'runtime':str(runtime),'production_database':'not_accessed','owned_services_stopped':True}
    except Exception as exc:
        summary={'status':'failed','error_type':type(exc).__name__,'runtime':str(runtime)};raise
    finally:
        for p in reversed(processes):
            if p is mysql:continue
            if p.poll() is None:p.terminate();p.wait(timeout=30)
        if mysql and mysql.poll() is None:
            subprocess.run(['mysqladmin','--no-defaults','--host=127.0.0.1','--port=3310','--user=root','shutdown'],executable=str(MYSQL/'bin/mysqladmin.exe'),cwd=MYSQL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,creationflags=creation)
            mysql.wait(timeout=30)
        for log in logs:log.close()
        (ROOT/'layer2/artifacts/release_integration_validation.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
