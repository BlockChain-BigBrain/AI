"""Durable local workflow: full evaluation -> calibration/analysis -> real operations tests."""
import json
import os
import subprocess
import sys
import time
import traceback
import ctypes
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ART=ROOT/'layer2/artifacts'
STATUS=ART/'mentoring_workflow_status.json'

def status(stage,state='running',**details):
    data={'state':state,'stage':stage,'updated_utc':datetime.now(timezone.utc).isoformat(),
          'manager_pid':os.getpid(),**details}
    temporary=STATUS.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(STATUS)

def main():
    if STATUS.is_file():
        previous=json.loads(STATUS.read_text(encoding='utf-8'))
        old_pid=previous.get('manager_pid')
        if os.name=='nt' and previous.get('state')=='running' and old_pid and old_pid!=os.getpid():
            handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,int(old_pid))
            if handle:
                code=ctypes.c_ulong()
                ctypes.windll.kernel32.GetExitCodeProcess(handle,ctypes.byref(code))
                ctypes.windll.kernel32.CloseHandle(handle)
                if code.value==259:raise RuntimeError('A workflow manager is already running; refusing a duplicate expensive run.')
    env={**os.environ,'PYTHONUNBUFFERED':'1','PYTHONIOENCODING':'utf-8'}
    started=time.monotonic()
    stages=[('full_evaluation',[sys.executable,'-u','layer2/evaluate_top3_aggregation.py','--include-reperformed','--full-synthetic']),
            ('calibration_and_failure_analysis',[sys.executable,'-u','layer2/analyze_full_evaluation.py']),
            ('real_upload_and_operations_tests',[sys.executable,'-u','backend/test/operational.py']),
            ('team_react_auth_prisma_mysql_e2e',[sys.executable,'-u','backend/test/team_stack.py','--live-ai'])]
    try:
        for stage,command in stages:
            log_path=ART/f'workflow_{stage}.log'
            with log_path.open('w',encoding='utf-8') as log:
                child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                while child.poll() is None:
                    status(stage,child_pid=child.pid,log=str(log_path),elapsed_seconds=round(time.monotonic()-started))
                    time.sleep(10)
                if child.returncode:raise RuntimeError(f'{stage} exited {child.returncode}; see {log_path}')
        status('local_work_complete','completed_local',elapsed_seconds=round(time.monotonic()-started),
               remaining_external_dependencies=['Production MySQL and Google OAuth environment settings not supplied; isolated team-stack tested',
                                                'Production HTTPS API URL for GitHub Pages not supplied',
                                                'Expert listening review of hard normal candidates remains pending'])
        print('Completed local evaluation, calibration, failure analysis and operations tests',flush=True)
    except Exception as exc:
        status('workflow_error','failed',error=str(exc))
        traceback.print_exc()
        raise

if __name__=='__main__':main()
