const Database = require('better-sqlite3');
const path = require('path');
const fs = require('fs');

const DATA_DIR = path.join(__dirname, '..', '..', 'data');

function createDb(dbPath) {
  const resolvedPath = dbPath || path.join(DATA_DIR, 'fax.db');
  fs.mkdirSync(path.dirname(resolvedPath), { recursive: true });

  const db = new Database(resolvedPath);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');

  db.exec(`
    CREATE TABLE IF NOT EXISTS faxes (
      id TEXT PRIMARY KEY,
      direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
      status TEXT NOT NULL DEFAULT 'queued'
        CHECK(status IN ('queued', 'sending', 'sent', 'delivered', 'failed', 'busy', 'no_answer', 'received')),
      from_name TEXT,
      from_number TEXT NOT NULL,
      from_email TEXT,
      to_name TEXT,
      to_number TEXT NOT NULL,
      page_count INTEGER DEFAULT 0,
      file_path TEXT,
      notes TEXT,
      quality TEXT DEFAULT 'standard' CHECK(quality IN ('standard', 'fine', 'superfine')),
      resolution TEXT DEFAULT '204x98' CHECK(resolution IN ('204x98', '204x196', '204x391')),
      api_response TEXT,
      api_fax_id TEXT,
      error_message TEXT,
      retry_count INTEGER DEFAULT 0,
      max_retries INTEGER DEFAULT 3,
      next_retry_at TEXT,
      transmission_receipt TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS contacts (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      fax_number TEXT NOT NULL,
      company TEXT,
      email TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      action TEXT NOT NULL,
      resource_type TEXT NOT NULL,
      resource_id TEXT,
      details TEXT,
      ip_address TEXT,
      user_agent TEXT,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS usage_tracking (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      date TEXT NOT NULL,
      faxes_sent INTEGER DEFAULT 0,
      pages_sent INTEGER DEFAULT 0,
      UNIQUE(date)
    );

    CREATE TABLE IF NOT EXISTS webhook_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_type TEXT NOT NULL,
      fax_id TEXT,
      payload TEXT,
      processed INTEGER DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_faxes_status ON faxes(status);
    CREATE INDEX IF NOT EXISTS idx_faxes_direction ON faxes(direction);
    CREATE INDEX IF NOT EXISTS idx_faxes_created_at ON faxes(created_at);
    CREATE INDEX IF NOT EXISTS idx_faxes_next_retry ON faxes(next_retry_at);
    CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
    CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
    CREATE INDEX IF NOT EXISTS idx_usage_date ON usage_tracking(date);
  `);

  return db;
}

module.exports = { createDb };
