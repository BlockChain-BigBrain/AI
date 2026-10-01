"""Local MVP API: durable jobs, one analysis worker, no registration side effects."""
from pathlib import Path
import sys
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / '.deps'))
sys.path.insert(0, str(BASE))
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from engine import Engine
from schemas import HealthResponse, JobAccepted, VerificationJob

DATA = BASE / 'runtime'
DATA.mkdir(exist_ok=True)
DB = DATA / 'jobs.sqlite3'
POOL = ThreadPoolExecutor(max_workers=1)
engine = None


def connection():
    return sqlite3.connect(DB, timeout=30)


def update(job_id, state, result=None, error=None):
    with connection() as db:
        db.execute('UPDATE jobs SET state=?, result=?, error=? WHERE id=?',
                   (state, json.dumps(result, ensure_ascii=False) if result else None, error, job_id))


def analyze(job_id, path, audio_hash):
    """Runs outside the HTTP event loop; failure is never interpreted as PASS."""
    start = time.perf_counter()
    update(job_id, 'RUNNING')
    try:
        result = engine.verify(path, audio_hash)
        result['processingSeconds'] = round(time.perf_counter() - start, 3)
        update(job_id, 'SUCCEEDED', result)
    except Exception:
        logging.exception('Analysis failed for job %s', job_id)
        update(job_id, 'FAILED', error='ANALYSIS_FAILED')
    finally:
        path.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(app):
    global engine
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, track_id TEXT, audio_hash TEXT, state TEXT, result TEXT, error TEXT, request_key TEXT UNIQUE)')
        # Interrupted jobs remain visible as failed; clients can explicitly resubmit.
        db.execute("UPDATE jobs SET state='FAILED', error='SERVER_RESTARTED' WHERE state IN ('PENDING','RUNNING')")
    for path in DATA.glob('*.upload.*'):
        path.unlink()
    engine = await asyncio.get_running_loop().run_in_executor(POOL, Engine)
    yield
    POOL.shutdown(wait=True)


app = FastAPI(title='Track-AI Verification', version='1.0.0', lifespan=lifespan)


@app.get('/health', response_model=HealthResponse)
def health():
    return dict(status='ready', referenceTracks=len(engine.groups), referenceWindows=len(engine.ids),
                modelVersion='laion/clap-htsat-unfused', scoreVersion='seg_top3_centered-v1')


@app.post('/verify', status_code=202, response_model=JobAccepted)
async def verify(file: UploadFile = File(...), trackId: str = Form(..., min_length=1, max_length=200),
                 requestId: str = Form(..., min_length=1, max_length=200)):
    """Multipart contract. Reusing a requestId for different input returns 409."""
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in {'.mp3','.wav','.webm','.flac','.m4a','.aac','.ogg','.wma'}:
        raise HTTPException(415, 'UNSUPPORTED_FORMAT')
    job_id = uuid.uuid4().hex
    path = DATA / (job_id + '.upload' + suffix)
    digest = hashlib.sha256()
    size = 0
    submitted = False
    try:
        with path.open('wb') as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 250 * 1024 * 1024:
                    raise HTTPException(413, 'FILE_TOO_LARGE')
                out.write(chunk)
                digest.update(chunk)
        if not size:
            raise HTTPException(422, 'EMPTY_FILE')
        audio_hash = digest.hexdigest()
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT id, track_id, audio_hash FROM jobs WHERE request_key=?', (requestId,)).fetchone()
            if old:
                if old[1:] != (trackId, audio_hash):
                    raise HTTPException(409, 'REQUEST_ID_CONFLICT')
                return dict(jobId=old[0], statusUrl='/verify/' + old[0])
            pending = db.execute("SELECT count(*) FROM jobs WHERE state IN ('PENDING','RUNNING')").fetchone()[0]
            if pending >= 8:
                raise HTTPException(429, 'QUEUE_FULL')
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                       (job_id, trackId, audio_hash, 'PENDING', None, None, requestId))
        POOL.submit(analyze, job_id, path, audio_hash)
        submitted = True
        return dict(jobId=job_id, statusUrl='/verify/' + job_id)
    finally:
        await file.close()
        if not submitted:
            path.unlink(missing_ok=True)


@app.get('/verify/{job_id}', response_model=VerificationJob)
def result(job_id: str):
    with connection() as db:
        row = db.execute('SELECT track_id,state,result,error FROM jobs WHERE id=?', (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'JOB_NOT_FOUND')
    return dict(jobId=job_id, trackId=row[0], state=row[1],
                result=json.loads(row[2]) if row[2] else None, error=row[3])


if __name__ == '__main__':
    import uvicorn
    # One process only: the MVP owns a single worker and immutable reference snapshot.
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('TRACK_AI_PORT', '8000')))
