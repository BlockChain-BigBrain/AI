import express from "express";
import multer from "multer";
import { DatabaseSync } from "node:sqlite";
import { mkdir, unlink } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { aiHealth, submitVerification, waitForVerification } from "./track-ai-client.js";

const HERE = dirname(fileURLToPath(import.meta.url));
// FastAPI와 공유하는 로컬 환경 변수(.env)를 개발 시 자동 로드합니다.
const ROOT_ENV = resolve(HERE, "../..", ".env");
const loadEnvFile = (process as NodeJS.Process & {
  loadEnvFile?: (path?: string) => void;
}).loadEnvFile;
if (existsSync(ROOT_ENV) && loadEnvFile) {
  loadEnvFile(ROOT_ENV);
}
const RUNTIME = resolve(HERE, "../runtime");
const UPLOADS = resolve(RUNTIME, "uploads");
await mkdir(UPLOADS, { recursive: true });

const db = new DatabaseSync(resolve(RUNTIME, "tracks.sqlite3"));
db.exec(`
  CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    state TEXT NOT NULL,
    decision TEXT,
    audio_hash TEXT,
    similarity_score REAL,
    ai_job_id TEXT,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );
  UPDATE tracks SET state='FAILED', error='BACKEND_RESTARTED', updated_at=datetime('now')
  WHERE state='ANALYZING';
`);

const allowed = new Set([".mp3", ".wav", ".webm", ".flac", ".m4a", ".aac", ".ogg", ".wma"]);
const upload = multer({
  dest: UPLOADS,
  limits: { fileSize: 250 * 1024 * 1024, files: 1 },
  fileFilter: (_request, file, callback) => {
    callback(null, allowed.has(extname(file.originalname).toLowerCase()));
  },
});

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "1mb" }));

function publicTrack(row: Record<string, unknown> | undefined) {
  if (!row) return null;
  return {
    id: row.id,
    originalName: row.original_name,
    state: row.state,
    decision: row.decision,
    audioHash: row.audio_hash,
    similarityScore: row.similarity_score,
    aiJobId: row.ai_job_id,
    result: row.result_json ? JSON.parse(String(row.result_json)) : null,
    error: row.error,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

async function analyzeTrack(trackId: string, filePath: string, originalName: string) {
  try {
    const accepted = await submitVerification(filePath, originalName, trackId, `verify:${trackId}`);
    db.prepare("UPDATE tracks SET ai_job_id=?, updated_at=datetime('now') WHERE id=?")
      .run(accepted.jobId, trackId);
    const job = await waitForVerification(accepted.statusUrl);
    const result = job.result ?? {};
    const decision = typeof result.decision === "string" ? result.decision : null;
    const audioHash = typeof result.audioHash === "string" ? result.audioHash : null;
    const similarityScore = typeof result.similarityScore === "number" ? result.similarityScore : null;
    db.prepare(`UPDATE tracks SET state='VERIFIED', decision=?, audio_hash=?, similarity_score=?,
      result_json=?, error=NULL, updated_at=datetime('now') WHERE id=?`).run(
        decision,
        audioHash,
        similarityScore,
        JSON.stringify(result),
        trackId,
      );
  } catch (error) {
    console.error("Track analysis failed", trackId, error);
    db.prepare("UPDATE tracks SET state='FAILED', error=?, updated_at=datetime('now') WHERE id=?")
      .run(error instanceof Error ? error.message.slice(0, 500) : "UNKNOWN_ERROR", trackId);
  } finally {
    await unlink(filePath).catch(() => undefined);
  }
}

app.get("/health", async (_request, response) => {
  try {
    const ai = await aiHealth();
    response.status(ai.ok ? 200 : 503).json({ status: ai.ok ? "ready" : "degraded", ai: await ai.json() });
  } catch {
    response.status(503).json({ status: "degraded", ai: null });
  }
});

app.post("/api/tracks", upload.single("file"), (request, response) => {
  if (!request.file) {
    response.status(422).json({ code: "AUDIO_FILE_REQUIRED" });
    return;
  }
  const trackId = randomUUID();
  const now = new Date().toISOString();
  db.prepare(`INSERT INTO tracks
    (id, original_name, state, created_at, updated_at) VALUES (?, ?, 'ANALYZING', ?, ?)`)
    .run(trackId, request.file.originalname, now, now);
  void analyzeTrack(trackId, request.file.path, request.file.originalname);
  response.status(202).json({ trackId, state: "ANALYZING", statusUrl: `/api/tracks/${trackId}` });
});

app.get("/api/tracks/:id", (request, response) => {
  const row = db.prepare("SELECT * FROM tracks WHERE id=?").get(request.params.id) as
    Record<string, unknown> | undefined;
  if (!row) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  response.json(publicTrack(row));
});

app.use((error: unknown, _request: express.Request, response: express.Response, _next: express.NextFunction) => {
  if (error instanceof multer.MulterError && error.code === "LIMIT_FILE_SIZE") {
    response.status(413).json({ code: "FILE_TOO_LARGE" });
    return;
  }
  console.error(error);
  response.status(500).json({ code: "INTERNAL_ERROR" });
});

const port = Number(process.env.PORT ?? 3000);
app.listen(port, "127.0.0.1", () => console.log(`Track-AI backend: http://127.0.0.1:${port}`));
import { existsSync } from "node:fs";
