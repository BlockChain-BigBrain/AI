import { DatabaseSync, type SQLInputValue } from 'node:sqlite';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

type Parameter = string | number | null;
type Row = Record<string, unknown>;
type Contributor = { walletAddress: string; shareBps: number; signature: string | null };
export type Statement = {
  run: (...params: Parameter[]) => Promise<unknown>;
  get: (...params: Parameter[]) => Promise<Row | undefined>;
  all: (...params: Parameter[]) => Promise<Row[]>;
};
export type Store = { kind: 'sqlite' | 'mysql'; prepare: (sql: string) => Statement;
  replaceContributors: (trackId: string, rows: Contributor[], createdAt: string) => Promise<void>;
  close: () => Promise<void> };

export function mysqlSql(sql: string): string {
  return sql.replace(/datetime\('now'\)/g, "DATE_FORMAT(UTC_TIMESTAMP(), '%Y-%m-%dT%H:%i:%sZ')")
    .replace(/ORDER BY rowid/g, 'ORDER BY wallet_address')
    .replace(/ON CONFLICT\(track_id\) DO UPDATE SET/g, 'ON DUPLICATE KEY UPDATE')
    .replace(/excluded\.([a-z_]+)/g, 'VALUES($1)');
}

export async function openDatabase(path: string, sqliteSchema: string): Promise<Store> {
  const url = process.env.DATABASE_URL;
  if (!url) {
    const db = new DatabaseSync(path);
    db.exec(sqliteSchema);
    return { kind: 'sqlite', prepare(sql) {
      const statement = db.prepare(sql);
      return {
        async run(...params) { return statement.run(...params as SQLInputValue[]); },
        async get(...params) { return statement.get(...params as SQLInputValue[]) as Row | undefined; },
        async all(...params) { return statement.all(...params as SQLInputValue[]) as Row[]; },
      };
    }, async replaceContributors(trackId, rows, createdAt) {
      db.exec('BEGIN IMMEDIATE');
      try {
        db.prepare('DELETE FROM contributors WHERE track_id=?').run(trackId);
        const insert = db.prepare('INSERT INTO contributors(track_id,wallet_address,share_bps,signature,created_at) VALUES(?,?,?,?,?)');
        for (const row of rows) insert.run(trackId,row.walletAddress,row.shareBps,row.signature,createdAt);
        db.exec('COMMIT');
      } catch (error) { db.exec('ROLLBACK'); throw error; }
    }, async close() { db.close(); } };
  }
  if (!url.startsWith('mysql://')) throw new Error('DATABASE_URL must use mysql://; unset it for local SQLite.');
  const mysql = await import('mysql2/promise');
  const pool = mysql.createPool(url);
  try {
    await pool.execute('SELECT 1');
    const schema = await readFile(fileURLToPath(new URL('../schema.mysql.sql', import.meta.url)), 'utf8');
    for (const sql of schema.split(';').map(s => s.trim()).filter(Boolean)) await pool.query(sql);
    await pool.execute("UPDATE tracks SET state='FAILED', error='BACKEND_RESTARTED', updated_at=DATE_FORMAT(UTC_TIMESTAMP(), '%Y-%m-%dT%H:%i:%sZ') WHERE state='ANALYZING'");
  } catch {
    await pool.end();
    throw new Error('MYSQL_STARTUP_FAILED: check connection, permissions and schema; credentials are not logged.');
  }
  return { kind: 'mysql', prepare(sql) {
    const translated = mysqlSql(sql);
    return {
      async run(...params) { const [result] = await pool.execute(translated, params); return result; },
      async get(...params) { const [rows] = await pool.execute(translated, params); return (rows as Row[])[0]; },
      async all(...params) { const [rows] = await pool.execute(translated, params); return rows as Row[]; },
    };
  }, async replaceContributors(trackId, rows, createdAt) {
    const connection = await pool.getConnection();
    try {
      await connection.beginTransaction();
      await connection.execute('DELETE FROM contributors WHERE track_id=?',[trackId]);
      for (const row of rows) await connection.execute(
        'INSERT INTO contributors(track_id,wallet_address,share_bps,signature,created_at) VALUES(?,?,?,?,?)',
        [trackId,row.walletAddress,row.shareBps,row.signature,createdAt]);
      await connection.commit();
    } catch (error) { await connection.rollback(); throw error; }
    finally { connection.release(); }
  }, async close() { await pool.end(); } };
}
