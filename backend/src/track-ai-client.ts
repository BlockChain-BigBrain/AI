import { createReadStream } from "node:fs";
import { basename } from "node:path";

// 환경 변수 파일은 서버 진입점에서 로드될 수 있으므로 호출 시점에 읽습니다.
const getAiBaseUrl = () => process.env.TRACK_AI_URL ?? "http://127.0.0.1:8000";

export type AiJob = {
  jobId: string;
  trackId: string;
  state: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  result: Record<string, unknown> | null;
  error: string | null;
};

export async function aiHealth(): Promise<Response> {
  return fetch(`${getAiBaseUrl()}/health`, { signal: AbortSignal.timeout(5_000) });
}

export async function submitVerification(
  filePath: string,
  originalName: string,
  trackId: string,
  requestId: string,
): Promise<{ jobId: string; statusUrl: string }> {
  // Node's built-in FormData does not accept a file stream directly. The MVP
  // reads at most 250 MB, which is also the upload route's hard limit.
  const chunks: Buffer[] = [];
  for await (const chunk of createReadStream(filePath)) chunks.push(Buffer.from(chunk));
  const merged = Buffer.concat(chunks);
  const bytes = new Uint8Array(merged.length);
  bytes.set(merged);
  const apiKey = process.env.TRACK_AI_API_KEY;
  if (!apiKey) {
    throw new Error("TRACK_AI_API_KEY_NOT_CONFIGURED");
  }

  const form = new FormData();
  form.set("file", new Blob([bytes.buffer]), basename(originalName));
  form.set("trackId", trackId);
  form.set("requestId", requestId);
  const response = await fetch(`${getAiBaseUrl()}/verify`, {
    method: "POST",
    body: form,
    headers: {
      "X-Internal-API-Key": apiKey,
    },
    signal: AbortSignal.timeout(120_000),
  });
  if (!response.ok) throw new Error(`AI_SUBMIT_${response.status}:${await response.text()}`);
  return response.json() as Promise<{ jobId: string; statusUrl: string }>;
}

export async function waitForVerification(statusUrl: string): Promise<AiJob> {
  const apiKey = process.env.TRACK_AI_API_KEY;
  if (!apiKey) {
    throw new Error("TRACK_AI_API_KEY_NOT_CONFIGURED");
  }
  const deadline = Date.now() + 30 * 60_000;
  while (Date.now() < deadline) {
    const response = await fetch(`${getAiBaseUrl()}${statusUrl}`, {
      headers: {
        "X-Internal-API-Key": apiKey,
      },
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) throw new Error(`AI_POLL_${response.status}`);
    const job = (await response.json()) as AiJob;
    if (job.state === "SUCCEEDED") return job;
    if (job.state === "FAILED") throw new Error(`AI_ANALYSIS_FAILED:${job.error}`);
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error("AI_POLL_TIMEOUT");
}
