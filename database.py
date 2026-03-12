import sqlite3
import uuid
from datetime import datetime, date
from config import DB_PATH


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS faxes (
            id TEXT PRIMARY KEY,
            to_number TEXT NOT NULL,
            to_name TEXT DEFAULT '',
            from_number TEXT DEFAULT '',
            from_name TEXT DEFAULT '',
            from_email TEXT DEFAULT '',
            file_path TEXT,
            tiff_path TEXT,
            cover_message TEXT DEFAULT '',
            status TEXT DEFAULT 'queued',
            provider TEXT,
            provider_fax_id TEXT,
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            next_retry_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            fax_number TEXT NOT NULL,
            company TEXT DEFAULT '',
            email TEXT DEFAULT '',
            sip_uri TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS usage_tracking (
            date TEXT NOT NULL,
            provider TEXT NOT NULL,
            faxes_sent INTEGER DEFAULT 0,
            PRIMARY KEY (date, provider)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS p2p_peers (
            node_id TEXT PRIMARY KEY,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            public_key TEXT DEFAULT '',
            capabilities TEXT DEFAULT '[]',
            area_codes TEXT DEFAULT '[]',
            country_codes TEXT DEFAULT '[]',
            trust_score REAL DEFAULT 0.5,
            relay_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            last_seen TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS p2p_relay_jobs (
            job_id TEXT PRIMARY KEY,
            source_node TEXT NOT NULL,
            target_number TEXT NOT NULL,
            payload_hash TEXT,
            status TEXT DEFAULT 'pending',
            hops TEXT DEFAULT '[]',
            hop_count INTEGER DEFAULT 0,
            delivery_proof TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_faxes_status ON faxes(status);
        CREATE INDEX IF NOT EXISTS idx_faxes_created ON faxes(created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_p2p_peers_trust ON p2p_peers(trust_score);
        CREATE INDEX IF NOT EXISTS idx_p2p_jobs_status ON p2p_relay_jobs(status);
    """)
    db.close()


# ── Fax CRUD ──

def create_fax(to_number, to_name="", from_number="", from_name="",
               from_email="", file_path="", cover_message="", provider=None):
    db = get_db()
    fax_id = str(uuid.uuid4())[:8]
    db.execute(
        """INSERT INTO faxes (id, to_number, to_name, from_number, from_name,
           from_email, file_path, cover_message, provider)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fax_id, to_number, to_name, from_number, from_name,
         from_email, file_path, cover_message, provider)
    )
    db.commit()
    audit("fax_created", "fax", fax_id, f"to={to_number} provider={provider}")
    fax = db.execute("SELECT * FROM faxes WHERE id=?", (fax_id,)).fetchone()
    db.close()
    return dict(fax)


def get_fax(fax_id):
    db = get_db()
    row = db.execute("SELECT * FROM faxes WHERE id=?", (fax_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def list_faxes(status=None, limit=50):
    db = get_db()
    if status:
        rows = db.execute(
            "SELECT * FROM faxes WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM faxes ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def update_fax(fax_id, **kwargs):
    db = get_db()
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [fax_id]
    db.execute(f"UPDATE faxes SET {sets} WHERE id=?", vals)
    db.commit()
    db.close()


def delete_fax(fax_id):
    db = get_db()
    db.execute("DELETE FROM faxes WHERE id=?", (fax_id,))
    db.commit()
    db.close()


# ── Contacts ──

def create_contact(name, fax_number, company="", email="", sip_uri=""):
    db = get_db()
    cur = db.execute(
        "INSERT INTO contacts (name, fax_number, company, email, sip_uri) VALUES (?,?,?,?,?)",
        (name, fax_number, company, email, sip_uri))
    db.commit()
    contact = db.execute("SELECT * FROM contacts WHERE id=?", (cur.lastrowid,)).fetchone()
    db.close()
    return dict(contact)


def list_contacts():
    db = get_db()
    rows = db.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    db.close()
    return [dict(r) for r in rows]


def delete_contact(contact_id):
    db = get_db()
    db.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
    db.commit()
    db.close()


# ── Usage Tracking ──

def increment_usage(provider):
    db = get_db()
    today = date.today().isoformat()
    db.execute(
        """INSERT INTO usage_tracking (date, provider, faxes_sent)
           VALUES (?, ?, 1)
           ON CONFLICT(date, provider) DO UPDATE SET faxes_sent = faxes_sent + 1""",
        (today, provider))
    db.commit()
    db.close()


def get_usage_today(provider=None):
    db = get_db()
    today = date.today().isoformat()
    if provider:
        row = db.execute(
            "SELECT faxes_sent FROM usage_tracking WHERE date=? AND provider=?",
            (today, provider)).fetchone()
        db.close()
        return row["faxes_sent"] if row else 0
    rows = db.execute(
        "SELECT provider, faxes_sent FROM usage_tracking WHERE date=?",
        (today,)).fetchall()
    db.close()
    return {r["provider"]: r["faxes_sent"] for r in rows}


# ── Audit ──

def audit(action, resource_type=None, resource_id=None, details=None):
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (action, resource_type, resource_id, details) VALUES (?,?,?,?)",
        (action, resource_type, resource_id, details))
    db.commit()
    db.close()


def get_audit_log(limit=100):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


init_db()
