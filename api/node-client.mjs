// Node 22+: backend integration example using built-in fetch and FormData.
// Run: node api/node-client.mjs "C:\path\audio.mp3" [trackId] [requestId]
import { readFile } from 'node:fs/promises';
import { basename } from 'node:path';
import { randomUUID } from 'node:crypto';
import { setTimeout } from 'node:timers/promises';

export async function verifyAudio(path, trackId, requestId = randomUUID()) {
  const base = process.env.TRACK_AI_URL || 'http://127.0.0.1:8000';
  const form = new FormData();
  form.set('file', new Blob([await readFile(path)]), basename(path));
  form.set('trackId', trackId);
  form.set('requestId', requestId);
  const response = await fetch(`${base}/verify`, {method:'POST', body:form, signal:AbortSignal.timeout(120000)});
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  const job = await response.json();
  // Polling only retrieves results; it does not submit duplicate analysis jobs.
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const poll = await fetch(`${base}${job.statusUrl}`, {signal:AbortSignal.timeout(10000)});
    if (!poll.ok) throw new Error(`Poll failed: ${poll.status}`);
    const report = await poll.json();
    if (report.state === 'SUCCEEDED') return report;
    if (report.state === 'FAILED') throw new Error(JSON.stringify(report));
    await setTimeout(1000);
  }
  throw new Error(`Client timeout; resume polling job ${job.jobId}`);
}

if (process.argv[1]?.endsWith('node-client.mjs')) {
  if (!process.argv[2]) throw new Error('Provide an audio file path');
  console.log(JSON.stringify(await verifyAudio(process.argv[2], process.argv[3] || 'demo-track', process.argv[4]), null, 2));
}
