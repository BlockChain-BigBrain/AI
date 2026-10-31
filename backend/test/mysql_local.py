"""Run the HTTP storage checks against an isolated portable MySQL engine."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/'layer2/artifacts'

def main():
    base=ROOT/'.tools/mysql-8.4.13-winx64'
    data=ROOT/'.runtime-tests'/f'mysql-engine-{time.time_ns()}'
    data.mkdir(parents=True)
    # Keep argv ASCII: this Windows build reparses a Unicode argv[0] incorrectly.
    common=['--basedir=.',f'--datadir={os.path.relpath(data / "data", base).replace(chr(92), "/")}', '--innodb-buffer-pool-size=64M','--innodb-redo-log-capacity=64M']
    creation=getattr(subprocess,'CREATE_NO_WINDOW',0)
    engine=None
    summary={'status':'running','scope':'isolated local engine; not the team MySQL database'}
    with (data/'engine.log').open('w',encoding='utf-8') as log:
        try:
            subprocess.run(['mysqld','--no-defaults','--initialize-insecure',*common],executable=str(base/'bin/mysqld.exe'),cwd=base,stdout=log,stderr=subprocess.STDOUT,check=True,creationflags=creation)
            engine=subprocess.Popen(['mysqld','--no-defaults','--console',*common,'--bind-address=127.0.0.1','--port=3308','--mysqlx=0','--skip-log-bin'],executable=str(base/'bin/mysqld.exe'),cwd=base,stdout=log,stderr=subprocess.STDOUT,creationflags=creation)
            for _ in range(90):
                if engine.poll() is not None:raise RuntimeError('Isolated MySQL engine exited; see engine.log')
                try:
                    with socket.create_connection(('127.0.0.1',3308),timeout=1):break
                except OSError:time.sleep(1)
            node_code="import mysql from './backend/node_modules/mysql2/promise.js';const c=await mysql.createConnection('mysql://root@127.0.0.1:3308');await c.query('CREATE DATABASE track_ai_test CHARACTER SET utf8mb4');await c.end();"
            subprocess.run([str(ROOT/'.tools/node/node.exe'),'--input-type=module','-e',node_code],cwd=ROOT,check=True,stdout=log,stderr=subprocess.STDOUT,creationflags=creation)
            env={**os.environ,'TEST_DATABASE_URL':'mysql://root@127.0.0.1:3308/track_ai_test'}
            subprocess.run([sys.executable,'backend/test/storage_http.py'],cwd=ROOT,env=env,check=True,creationflags=creation)
            summary={'status':'passed','engine':'MySQL Community 8.4.13','scope':'isolated local MySQL, not team database',
                     'schema':'backend/schema.mysql.sql','checks':'Actual Node HTTP routes persisted and retrieved MySQL rows',
                     'system_service_installed':False,'test_engine_stopped_after_checks':True,'data_directory':str(data)}
        except Exception as exc:
            summary={'status':'failed','error':str(exc),'log':str(data/'engine.log')}
            raise
        finally:
            if engine and engine.poll() is None:
                subprocess.run(['mysqladmin','--no-defaults','--host=127.0.0.1','--port=3308','--user=root','shutdown'],executable=str(base/'bin/mysqladmin.exe'),cwd=base,stdout=log,stderr=subprocess.STDOUT,timeout=30,creationflags=creation)
                try:engine.wait(timeout=30)
                except subprocess.TimeoutExpired:engine.terminate()
            (ART/'mysql_integration_validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
