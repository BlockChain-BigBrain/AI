import assert from 'node:assert/strict';
import test from 'node:test';
import { openDatabase, mysqlSql } from '../src/database.js';

test('async repository preserves Unicode names, JSON evidence and updates', async () => {
  const old = process.env.DATABASE_URL;
  delete process.env.DATABASE_URL;
  const db = await openDatabase(':memory:', 'CREATE TABLE tracks(id TEXT PRIMARY KEY, original_name TEXT, result_json TEXT, state TEXT);');
  try {
    const evidence = { decision: 'WARN', similarTracks: [{ trackId: '원곡', score: 0.85 }] };
    await db.prepare('INSERT INTO tracks VALUES(?,?,?,?)').run('a', '내 음원.wav', JSON.stringify(evidence), 'ANALYZING');
    await db.prepare('UPDATE tracks SET state=? WHERE id=?').run('VERIFIED', 'a');
    const row = await db.prepare('SELECT * FROM tracks WHERE id=?').get('a');
    assert.equal(row?.original_name, '내 음원.wav');
    assert.equal(row?.state, 'VERIFIED');
    assert.deepEqual(JSON.parse(String(row?.result_json)), evidence);
    assert.equal((await db.prepare('SELECT * FROM tracks').all()).length, 1);
    await assert.rejects(db.prepare('INSERT INTO tracks(id) VALUES(?)').run('a'));
  } finally { await db.close(); if (old === undefined) delete process.env.DATABASE_URL; else process.env.DATABASE_URL = old; }
});

test('MySQL translation preserves placeholders and adapts supported SQLite clauses', () => {
  const sql = mysqlSql("INSERT INTO provenance_events(track_id,manifest_hash) VALUES(?,?) ON CONFLICT(track_id) DO UPDATE SET manifest_hash=excluded.manifest_hash,created_at=datetime('now')");
  assert.equal((sql.match(/\?/g) || []).length, 2);
  assert.match(sql, /ON DUPLICATE KEY UPDATE manifest_hash=VALUES\(manifest_hash\)/);
  assert.doesNotMatch(sql, /excluded\.|ON CONFLICT|datetime\(/);
});
