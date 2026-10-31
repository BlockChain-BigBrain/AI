"""Prepare an isolated persistent local team DB, or serve the team stack until Ctrl+C.

No production configuration is read or changed. Secrets stay in ignored local files.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
TEAM = ROOT / 'integrations'
DATA = ROOT / '.runtime-tests/local-team'
NODE = ROOT / '.tools/node-v22.23.4-win-x64/node.exe'
MYSQL = ROOT / '.tools/mysql-8.4.13-winx64'
CREATION = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def dotenv(path):
    result = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true', help='Keep local servers running until Ctrl+C')
    parser.add_argument('--check', action='store_true', help='Start and check the full local stack, then stop owned processes')
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    settings = DATA / 'secrets.json'
    if not settings.exists():
        settings.write_text(json.dumps({name: secrets.token_hex(48) for name in
                            ('mysql_root', 'mysql_app', 'jwt_access', 'jwt_refresh')}) + '\n', encoding='utf-8')
    private = json.loads(settings.read_text(encoding='utf-8'))
    backend_config = TEAM / 'Backend/.env'
    if not backend_config.exists():
        values = dotenv(TEAM / 'Backend/.env.example')
        key = dotenv(ROOT / '.env').get('TRACK_AI_API_KEY')
        if not key:
            raise RuntimeError('Root .env must contain TRACK_AI_API_KEY; existing files were preserved.')
        values.update(DATABASE_URL=f"mysql://track_ai_local:{private['mysql_app']}@127.0.0.1:3307/track_ai_local",
                      JWT_ACCESS_SECRET=private['jwt_access'], JWT_REFRESH_SECRET=private['jwt_refresh'],
                      TRACK_AI_API_KEY=key, TRACK_AI_URL='http://127.0.0.1:8000',
                      PORT='3000', FRONTEND_URL='http://localhost:8443/Frontend/',
                      GOOGLE_CALLBACK_URL='http://localhost:3000/api/v1/auth/callback/google')
        backend_config.write_text(''.join(f'{k}={v}\n' for k, v in values.items()), encoding='utf-8')
    config = dotenv(backend_config)
    expected_url = f"mysql://track_ai_local:{private['mysql_app']}@127.0.0.1:3307/track_ai_local"
    if config.get('DATABASE_URL') != expected_url:
        raise RuntimeError('Backend .env uses a different database; refusing to change it or migrate it.')
    frontend_config = TEAM / 'Frontend/.env.local'
    if not frontend_config.exists():
        frontend_config.write_text('VITE_API_BASE_URL=http://localhost:3000\n', encoding='utf-8')
    if 'VITE_LOCAL_LOGIN' not in dotenv(frontend_config):
        with frontend_config.open('a', encoding='utf-8') as local_env:
            local_env.write('\nVITE_LOCAL_LOGIN=true\n')
    if dotenv(frontend_config).get('VITE_API_BASE_URL') != 'http://localhost:3000':
        raise RuntimeError('Frontend .env.local uses a different API; existing configuration preserved.')
    env = {**os.environ, **config, 'PATH': str(NODE.parent) + os.pathsep + os.environ.get('PATH', ''),
           'TRACK_AI_SCOPE': 'ai_labeled',
           'LOCAL_MYSQL_ROOT_PASSWORD': private['mysql_root'], 'LOCAL_MYSQL_APP_PASSWORD': private['mysql_app']}
    if (TEAM / 'Backend/src/providers/http-ai.provider.ts').is_file():
        env.update(AI_PROVIDER_MODE='http', AI_API_URL='http://127.0.0.1:8000', VERIFICATION_TIMEOUT_MS='180000')
    processes, logs = [], []
    engine = None

    def run(command, cwd, name, child_env=env, executable=None):
        with (DATA / f'{name}.log').open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=cwd, env=child_env, executable=executable,
                                    stdout=log, stderr=subprocess.STDOUT, creationflags=CREATION)
        if result.returncode:
            raise RuntimeError(f'{name} failed; inspect the local log privately: {DATA / (name + ".log")}')

    def launch(command, cwd, name, child_env=env, executable=None):
        log = (DATA / f'{name}.log').open('w', encoding='utf-8'); logs.append(log)
        p = subprocess.Popen(command, cwd=cwd, env=child_env, executable=executable,
                             stdout=log, stderr=subprocess.STDOUT, creationflags=CREATION)
        processes.append(p)
        return p

    def available(port):
        try:
            with socket.create_connection(('localhost', port), timeout=.4):
                return True
        except OSError:
            return False

    def wait_port(port, process):
        for _ in range(180):
            if process.poll() is not None:
                raise RuntimeError(f'Local server exited on port {port}; inspect {DATA}')
            if available(port):
                return
            time.sleep(.5)
        raise TimeoutError(f'Local port {port}')

    common = ['--basedir=.', '--datadir=' + os.path.relpath(DATA / 'mysql-data', MYSQL).replace('\\', '/'),
              '--innodb-buffer-pool-size=64M', '--innodb-redo-log-capacity=64M']
    try:
        required_ports = [3307, 3000, 8443, 8000] if args.serve or args.check else [3307]
        if any(available(port) for port in required_ports):
            raise RuntimeError('A required local port is already occupied; no existing process was stopped.')
        if not (DATA / 'mysql-data').exists():
            run(['mysqld', '--no-defaults', '--initialize-insecure', *common], MYSQL, 'mysql-init',
                executable=str(MYSQL / 'bin/mysqld.exe'))
        engine = launch(['mysqld', '--no-defaults', '--console', *common, '--bind-address=127.0.0.1',
                         '--port=3307', '--mysqlx=0', '--skip-log-bin'], MYSQL, 'mysql',
                        executable=str(MYSQL / 'bin/mysqld.exe'))
        wait_port(3307, engine)
        if not (DATA / 'provisioned.json').exists():
            run([str(NODE), '--input-type=module', '-e', """
import mysql from './backend/node_modules/mysql2/promise.js';
const c = await mysql.createConnection({host:'127.0.0.1',port:3307,user:'root'});
const app = process.env.LOCAL_MYSQL_APP_PASSWORD, root = process.env.LOCAL_MYSQL_ROOT_PASSWORD;
await c.query('CREATE DATABASE IF NOT EXISTS track_ai_local CHARACTER SET utf8mb4');
await c.query("CREATE USER IF NOT EXISTS 'track_ai_local'@'127.0.0.1' IDENTIFIED BY " + c.escape(app));
await c.query("GRANT ALL ON track_ai_local.* TO 'track_ai_local'@'127.0.0.1'");
await c.query("ALTER USER 'root'@'localhost' IDENTIFIED BY " + c.escape(root));
await c.end();
"""], ROOT, 'provision')
            (DATA / 'provisioned.json').write_text('{"local_only": true}\n', encoding='utf-8')
        run([str(NODE), 'node_modules/prisma/build/index.js', 'migrate', 'deploy'], TEAM / 'Backend', 'migrations')
        run([str(NODE), '--input-type=module', '-e', """
import mysql from './backend/node_modules/mysql2/promise.js';
const c = await mysql.createConnection(process.env.DATABASE_URL);
const [rows] = await c.query('SELECT COUNT(*) AS n FROM _prisma_migrations WHERE finished_at IS NOT NULL');
if (rows[0].n < 5) throw new Error('Missing migrations');
await c.end();
"""], ROOT, 'database-check')
        (DATA / 'validation.json').write_text(json.dumps({'status': 'passed', 'database': 'track_ai_local',
            'port': 3307, 'production_database': 'not_accessed', 'google_login': 'credentials_not_supplied'}) + '\n', encoding='utf-8')
        print('Local MySQL prepared and all team migrations checked. Existing configurations preserved.', flush=True)
        if args.serve or args.check:
            tonal_policy = ROOT / 'layer2/artifacts/ai_labeled_recalibration.json'
            if not tonal_policy.exists() or not json.loads(tonal_policy.read_text(encoding='utf-8'))['profiles']['ai_labeled_catalog'].get('enabled'):
                raise RuntimeError('AI-labelled scope calibration is not ready. Local configuration is preserved.')
            api = launch([sys.executable, 'api/server.py'], ROOT, 'ai', {**env, 'TRACK_AI_PORT': '8000',
                         'TRACK_AI_RUNTIME': str(DATA / 'ai')})
            wait_port(8000, api)
            backend = launch([str(NODE), 'dist/server.js'], TEAM / 'Backend', 'backend')
            wait_port(3000, backend)
            frontend = launch([str(NODE), 'node_modules/vite/bin/vite.js', '--host', 'localhost',
                               '--port', '8443', '--strictPort'], TEAM / 'Frontend', 'frontend',
                              {**env, 'PORT': '8443', 'VITE_API_BASE_URL': 'http://localhost:3000'})
            wait_port(8443, frontend)
            if args.check:
                with urlopen('http://127.0.0.1:8000/health', timeout=15) as response:
                    health = json.load(response)
                improved_path=ROOT/'layer2/artifacts/ai_improvement_policy.json'
                expected_version='clap-top20+tonal-local-v1+expanded-square-v1' if improved_path.exists() else 'clap-top5+tonal-local-v1'
                if (ROOT/'layer2/artifacts/ai_precision_policy.json').exists():expected_version+='+'+'secondary-clap-cqt-fragments-v1'
                assert health['scoreVersion'] == expected_version
                if improved_path.exists():
                    improved=json.loads(improved_path.read_text(encoding='utf-8'))
                    assert health['thresholds']=={'warn':improved['warn_threshold'],'hold':improved['hold_threshold']}
                assert health['evaluationScope'] == 'ai_labeled'
                for url in ('http://localhost:3000/health', 'http://localhost:8443/Frontend/'):
                    with urlopen(url, timeout=15) as response:
                        assert response.status == 200
                (ROOT / 'layer2/artifacts/local_stack_validation.json').write_text(json.dumps({
                    'status': 'passed', 'score_version': health['scoreVersion'],
                    'thresholds':health['thresholds'],'decision_policy_version':health['decisionPolicyVersion'],
                    'evaluation_scope': health['evaluationScope'], 'reference_tracks': health['referenceTracks'],
                    'local_frontend_backend_ai_mysql': True, 'owned_processes_stopped_after_check': True,
                    'production_database': 'not_accessed'}, indent=2), encoding='utf-8')
                print('Local frontend, backend, calibrated AI and persistent MySQL checks passed.', flush=True)
                return
            print('Open http://localhost:8443/Frontend/ ; Ctrl+C stops this local stack.', flush=True)
            while all(p.poll() is None for p in processes):
                time.sleep(1)
            raise RuntimeError('A local service stopped; inspect local logs.')
    except KeyboardInterrupt:
        print('Stopping owned local services; database and uploads are preserved.')
    finally:
        for process in reversed(processes):
            if process is not engine and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
        if engine and engine.poll() is None:
            try:
                run([str(NODE), '--input-type=module', '-e', """
import mysql from './backend/node_modules/mysql2/promise.js';
const c = await mysql.createConnection({host:'127.0.0.1',port:3307,user:'root',password:process.env.LOCAL_MYSQL_ROOT_PASSWORD});
try { await c.query('SHUTDOWN'); } catch (e) { if (!['PROTOCOL_CONNECTION_LOST','ER_SERVER_SHUTDOWN'].includes(e.code)) throw e; }
"""], ROOT, 'shutdown')
                engine.wait(timeout=20)
            except Exception:
                engine.terminate()
                engine.wait(timeout=15)
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
