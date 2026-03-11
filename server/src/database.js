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
        CHECK(status IN ('queued', 'sending', 'delivered', 'failed', 'received')),
      from_name TEXT,
      from_number TEXT NOT NULL,
      from_email TEXT,
      to_name TEXT,
      to_number TEXT NOT NULL,
      page_count INTEGER DEFAULT 0,
      file_path TEXT,
      notes TEXT,
      api_response TEXT,
      error_message TEXT,
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

    CREATE INDEX IF NOT EXISTS idx_faxes_status ON faxes(status);
    CREATE INDEX IF NOT EXISTS idx_faxes_direction ON faxes(direction);
    CREATE INDEX IF NOT EXISTS idx_faxes_created_at ON faxes(created_at);
    CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
  `);

  return db;
}

module.exports = { createDb };
