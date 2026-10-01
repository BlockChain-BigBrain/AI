import { readFile } from "node:fs/promises";
import { basename } from "node:path";

const filePath = process.argv[2];
const expectedDecision = process.argv[3];
if (!filePath) throw new Error("Usage: npm run test:e2e -- <audio-path> [expected-decision]");

const base = process.env.BACKEND_URL ?? "http://127.0.0.1:3000";
const bytes = await readFile(filePath);
const form = new FormData();
form.set("file", new Blob([bytes]), basename(filePath));
const submitted = await fetch(`${base}/api/tracks`, { method: "POST", body: form });
if (submitted.status !== 202) throw new Error(`Expected HTTP 202, got ${submitted.status}: ${await submitted.text()}`);
const accepted = await submitted.json() as { trackId: string; statusUrl: string };

const deadline = Date.now() + 30 * 60_000;
while (Date.now() < deadline) {
  const response = await fetch(`${base}${accepted.statusUrl}`);
  if (!response.ok) throw new Error(`Status request failed: ${response.status}`);
  const track = await response.json() as { state: string; decision: string | null; error: string | null };
  if (track.state === "FAILED") throw new Error(`Track failed: ${track.error}`);
  if (track.state === "VERIFIED") {
    if (expectedDecision && track.decision !== expectedDecision) {
      throw new Error(`Expected ${expectedDecision}, got ${track.decision}`);
    }
    console.log(JSON.stringify({ trackId: accepted.trackId, state: track.state, decision: track.decision }, null, 2));
    process.exit(0);
  }
  await new Promise((resolve) => setTimeout(resolve, 500));
}
throw new Error("E2E timeout");
