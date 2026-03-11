const { describe, it, before, after } = require('node:test');
const assert = require('node:assert');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { createDb } = require('../src/database');

describe('Database', () => {
  let db;
  const dbPath = path.join(os.tmpdir(), `fax-test-${Date.now()}.db`);

  before(() => {
    db = createDb(dbPath);
  });

  after(() => {
    db.close();
    if (fs.existsSync(dbPath)) fs.unlinkSync(dbPath);
  });

  it('should create tables', () => {
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all();
    const names = tables.map((t) => t.name);
    assert.ok(names.includes('faxes'));
    assert.ok(names.includes('contacts'));
  });

  it('should insert and retrieve a fax', () => {
    const { v4: uuidv4 } = require('uuid');
    const id = uuidv4();
    db.prepare(`
      INSERT INTO faxes (id, direction, status, from_number, to_number, notes)
      VALUES (?, 'outbound', 'queued', '1-555-000-0000', '1-555-111-1111', 'test fax')
    `).run(id);

    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(id);
    assert.equal(fax.id, id);
    assert.equal(fax.direction, 'outbound');
    assert.equal(fax.status, 'queued');
    assert.equal(fax.to_number, '1-555-111-1111');
  });

  it('should insert and retrieve a contact', () => {
    const { v4: uuidv4 } = require('uuid');
    const id = uuidv4();
    db.prepare('INSERT INTO contacts (id, name, fax_number, company) VALUES (?, ?, ?, ?)')
      .run(id, 'Test User', '1-555-222-2222', 'Test Corp');

    const contact = db.prepare('SELECT * FROM contacts WHERE id = ?').get(id);
    assert.equal(contact.name, 'Test User');
    assert.equal(contact.fax_number, '1-555-222-2222');
    assert.equal(contact.company, 'Test Corp');
  });

  it('should enforce valid fax direction', () => {
    const { v4: uuidv4 } = require('uuid');
    assert.throws(() => {
      db.prepare(`
        INSERT INTO faxes (id, direction, from_number, to_number)
        VALUES (?, 'invalid', '1-555-000-0000', '1-555-111-1111')
      `).run(uuidv4());
    });
  });

  it('should enforce valid fax status', () => {
    const { v4: uuidv4 } = require('uuid');
    assert.throws(() => {
      db.prepare(`
        INSERT INTO faxes (id, direction, status, from_number, to_number)
        VALUES (?, 'outbound', 'bad_status', '1-555-000-0000', '1-555-111-1111')
      `).run(uuidv4());
    });
  });

  it('should list faxes with status filter', () => {
    const all = db.prepare('SELECT * FROM faxes WHERE status = ?').all('queued');
    assert.ok(Array.isArray(all));
    assert.ok(all.length > 0);
  });

  it('should delete a fax', () => {
    const { v4: uuidv4 } = require('uuid');
    const id = uuidv4();
    db.prepare(`
      INSERT INTO faxes (id, direction, from_number, to_number)
      VALUES (?, 'outbound', '1-555-000-0000', '1-555-111-1111')
    `).run(id);

    db.prepare('DELETE FROM faxes WHERE id = ?').run(id);
    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(id);
    assert.equal(fax, undefined);
  });

  it('should update fax status', () => {
    const { v4: uuidv4 } = require('uuid');
    const id = uuidv4();
    db.prepare(`
      INSERT INTO faxes (id, direction, from_number, to_number)
      VALUES (?, 'outbound', '1-555-000-0000', '1-555-111-1111')
    `).run(id);

    db.prepare("UPDATE faxes SET status = 'delivered' WHERE id = ?").run(id);
    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(id);
    assert.equal(fax.status, 'delivered');
  });
});
