import express from "express";
import multer from "multer";
import { DatabaseSync } from "node:sqlite";
import { existsSync } from "node:fs";
import { mkdir, unlink } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
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
  CREATE TABLE IF NOT EXISTS provenance_events (
    track_id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    creator_wallet TEXT,
    creator_signature TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(track_id) REFERENCES tracks(id)
  );
  CREATE TABLE IF NOT EXISTS contributors (
    track_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    share_bps INTEGER NOT NULL,
    signature TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(track_id, wallet_address),
    FOREIGN KEY(track_id) REFERENCES tracks(id)
  );
  CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reviewer_wallet TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(track_id) REFERENCES tracks(id)
  );
  CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY,
    track_id TEXT NOT NULL,
    gross_amount TEXT NOT NULL,
    fee_bps INTEGER NOT NULL,
    net_amount TEXT NOT NULL,
    status TEXT NOT NULL,
    transaction_hash TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(track_id) REFERENCES tracks(id)
  );
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
const frontendOrigin = process.env.FRONTEND_ORIGIN ?? "*";
app.use((request, response, next) => {
  response.setHeader("Access-Control-Allow-Origin", frontendOrigin);
  response.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Requested-With");
  response.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  if (request.method === "OPTIONS") {
    response.status(204).end();
    return;
  }
  next();
});

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function getTrack(trackId: string): Record<string, unknown> | undefined {
  return db.prepare("SELECT * FROM tracks WHERE id=?").get(trackId) as
    Record<string, unknown> | undefined;
}

function publicTrack(row: Record<string, unknown> | undefined) {
  if (!row) return null;
  const review = db.prepare(
    "SELECT status, reviewer_wallet AS reviewerWallet, note, created_at AS createdAt FROM reviews WHERE track_id=? ORDER BY created_at DESC LIMIT 1",
  ).get(String(row.id)) as Record<string, unknown> | undefined;
  const provenance = db.prepare(
    "SELECT manifest_hash AS manifestHash, creator_wallet AS creatorWallet, created_at AS createdAt FROM provenance_events WHERE track_id=?",
  ).get(String(row.id)) as Record<string, unknown> | undefined;
  return {
    id: row.id,
    originalName: row.original_name,
    state: row.state,
    decision: row.decision,
    audioHash: row.audio_hash,
    similarityScore: row.similarity_score,
    aiJobId: row.ai_job_id,
    result: row.result_json ? JSON.parse(String(row.result_json)) : null,
    review: review ?? null,
    provenance: provenance ?? null,
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
  const row = getTrack(request.params.id);
  if (!row) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  response.json(publicTrack(row));
});

// Record creator evidence as a tamper-evident manifest. This does not make a
// legal ownership decision; it creates a verifiable submission record.
app.post("/api/tracks/:id/provenance", (request, response) => {
  if (!getTrack(request.params.id)) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  const body = request.body as Record<string, unknown>;
  const manifest = body.manifest;
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    response.status(422).json({ code: "PROVENANCE_MANIFEST_REQUIRED" });
    return;
  }
  const manifestJson = canonical(manifest);
  const manifestHash = createHash("sha256").update(manifestJson).digest("hex");
  const creatorWallet = typeof body.creatorWallet === "string" ? body.creatorWallet : null;
  const creatorSignature = typeof body.creatorSignature === "string" ? body.creatorSignature : null;
  db.prepare(`INSERT INTO provenance_events
    (track_id, manifest_hash, manifest_json, creator_wallet, creator_signature, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(track_id) DO UPDATE SET manifest_hash=excluded.manifest_hash,
      manifest_json=excluded.manifest_json, creator_wallet=excluded.creator_wallet,
      creator_signature=excluded.creator_signature, created_at=excluded.created_at`).run(
        request.params.id, manifestHash, manifestJson, creatorWallet, creatorSignature, new Date().toISOString(),
      );
  response.status(201).json({
    trackId: request.params.id,
    manifestHash,
    status: "RECORDED",
    chainAnchor: {
      network: process.env.POLYGON_NETWORK ?? "amoy",
      contractAddress: process.env.TRACK_REGISTRY_CONTRACT ?? null,
      payload: { trackId: request.params.id, manifestHash },
    },
  });
});

app.get("/api/tracks/:id/provenance", (request, response) => {
  if (!getTrack(request.params.id)) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  const row = db.prepare("SELECT * FROM provenance_events WHERE track_id=?").get(request.params.id) as
    Record<string, unknown> | undefined;
  if (!row) {
    response.status(404).json({ code: "PROVENANCE_NOT_FOUND" });
    return;
  }
  response.json({
    trackId: request.params.id,
    manifestHash: row.manifest_hash,
    manifest: JSON.parse(String(row.manifest_json)),
    creatorWallet: row.creator_wallet,
    creatorSignature: row.creator_signature,
    createdAt: row.created_at,
  });
});

app.post("/api/tracks/:id/contributors", (request, response) => {
  if (!getTrack(request.params.id)) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  const contributors = request.body?.contributors;
  if (!Array.isArray(contributors) || contributors.length === 0) {
    response.status(422).json({ code: "CONTRIBUTORS_REQUIRED" });
    return;
  }
  const normalized: Array<{ walletAddress: string; shareBps: number; signature: string | null }> = contributors.map((item: unknown) => {
    const value = item as Record<string, unknown>;
    return {
      walletAddress: typeof value.walletAddress === "string" ? value.walletAddress : "",
      shareBps: typeof value.shareBps === "number" ? value.shareBps : -1,
      signature: typeof value.signature === "string" ? value.signature : null,
    };
  });
  if (normalized.some((item) => typeof item.walletAddress !== "string" ||
      !Number.isInteger(item.shareBps) || item.shareBps < 0 || item.shareBps > 10000)) {
    response.status(422).json({ code: "INVALID_CONTRIBUTOR_SHARE" });
    return;
  }
  const total = normalized.reduce((sum, item) => sum + Number(item.shareBps), 0);
  if (total !== 10000) {
    response.status(422).json({ code: "SHARES_MUST_TOTAL_10000_BPS", total });
    return;
  }
  db.prepare("DELETE FROM contributors WHERE track_id=?").run(request.params.id);
  const insert = db.prepare(`INSERT INTO contributors
    (track_id, wallet_address, share_bps, signature, created_at) VALUES (?, ?, ?, ?, ?)`);
  const now = new Date().toISOString();
  for (const item of normalized) {
    insert.run(request.params.id, item.walletAddress, item.shareBps, item.signature, now);
  }
  response.status(201).json({ trackId: request.params.id, contributors: normalized });
});

app.get("/api/tracks/:id/contributors", (request, response) => {
  if (!getTrack(request.params.id)) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  const rows = db.prepare(`SELECT wallet_address AS walletAddress, share_bps AS shareBps,
    signature FROM contributors WHERE track_id=? ORDER BY rowid`).all(request.params.id);
  response.json({ trackId: request.params.id, contributors: rows });
});

app.post("/api/tracks/:id/review", (request, response) => {
  if (!getTrack(request.params.id)) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  const { status, reviewerWallet, note } = request.body ?? {};
  if (!new Set(["APPROVED", "REJECTED", "NEEDS_INFO"]).has(status)) {
    response.status(422).json({ code: "INVALID_REVIEW_STATUS" });
    return;
  }
  const reviewId = randomUUID();
  db.prepare(`INSERT INTO reviews (id, track_id, status, reviewer_wallet, note, created_at)
    VALUES (?, ?, ?, ?, ?, ?)`).run(
      reviewId, request.params.id, status, typeof reviewerWallet === "string" ? reviewerWallet : null,
      typeof note === "string" ? note.slice(0, 2000) : null, new Date().toISOString(),
    );
  response.status(201).json({ reviewId, trackId: request.params.id, status });
});

app.get("/api/reviews/pending", (_request, response) => {
  const rows = db.prepare(`SELECT t.id AS trackId, t.original_name AS originalName,
    t.decision, t.result_json AS resultJson, t.created_at AS createdAt
    FROM tracks t LEFT JOIN reviews r ON r.track_id=t.id
    WHERE t.decision IN ('HOLD','WARN') AND r.id IS NULL ORDER BY t.created_at`).all() as
    Array<Record<string, unknown>>;
  response.json({ tracks: rows.map((row) => ({ ...row, result: row.resultJson ? JSON.parse(String(row.resultJson)) : null, resultJson: undefined })) });
});

app.post("/api/tracks/:id/settlement-quote", (request, response) => {
  if (!getTrack(request.params.id)) {
    response.status(404).json({ code: "TRACK_NOT_FOUND" });
    return;
  }
  const gross = request.body?.grossAmount;
  const feeBps = request.body?.feeBps ?? 1000;
  if (typeof gross !== "string" || !/^\d+$/.test(gross) || !Number.isInteger(feeBps) || feeBps < 0 || feeBps > 10000) {
    response.status(422).json({ code: "INVALID_SETTLEMENT_AMOUNT" });
    return;
  }
  const contributors = db.prepare("SELECT wallet_address AS walletAddress, share_bps AS shareBps FROM contributors WHERE track_id=? ORDER BY rowid").all(request.params.id) as Array<Record<string, unknown>>;
  if (!contributors.length) {
    response.status(422).json({ code: "CONTRIBUTORS_NOT_REGISTERED" });
    return;
  }
  const grossUnits = BigInt(gross);
  const netUnits = (grossUnits * BigInt(10000 - feeBps)) / 10000n;
  const settlementId = randomUUID();
  db.prepare(`INSERT INTO settlements
    (id, track_id, gross_amount, fee_bps, net_amount, status, transaction_hash, created_at)
    VALUES (?, ?, ?, ?, ?, 'QUOTED', NULL, ?)`).run(
      settlementId, request.params.id, gross, feeBps, netUnits.toString(), new Date().toISOString(),
    );
  response.json({
    settlementId,
    trackId: request.params.id,
    grossAmount: gross,
    feeBps,
    platformFee: (grossUnits - netUnits).toString(),
    netAmount: netUnits.toString(),
    payouts: contributors.map((item) => ({
      walletAddress: item.walletAddress,
      shareBps: item.shareBps,
      amount: (netUnits * BigInt(Number(item.shareBps))) / 10000n,
    })).map((item) => ({ ...item, amount: item.amount.toString() })),
    blockchain: { network: process.env.POLYGON_NETWORK ?? "amoy", status: "READY_FOR_ANCHOR" },
  });
});

app.post("/api/settlements/:id/anchor", (request, response) => {
  const txHash = request.body?.transactionHash;
  if (typeof txHash !== "string" || txHash.length < 16) {
    response.status(422).json({ code: "TRANSACTION_HASH_REQUIRED" });
    return;
  }
  const row = db.prepare("SELECT * FROM settlements WHERE id=?").get(request.params.id) as Record<string, unknown> | undefined;
  if (!row) {
    response.status(404).json({ code: "SETTLEMENT_NOT_FOUND" });
    return;
  }
  db.prepare("UPDATE settlements SET status='ANCHORED', transaction_hash=? WHERE id=?").run(txHash, request.params.id);
  response.json({ settlementId: request.params.id, status: "ANCHORED", transactionHash: txHash });
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
