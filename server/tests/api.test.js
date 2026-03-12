const { describe, it, before, after } = require('node:test');
const assert = require('node:assert');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { createDb } = require('../src/database');
const { v4: uuidv4 } = require('uuid');
const { categorizeError, isRetryable } = require('../src/services/faxService');
const { getNextRetryTime } = require('../src/services/retryService');
const { generateReceipt, generateReceiptText } = require('../src/services/receiptService');
const { validateFaxNumber, sanitizeString } = require('../src/middleware/security');

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

  it('should create all tables', () => {
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all();
    const names = tables.map((t) => t.name);
    assert.ok(names.includes('faxes'));
    assert.ok(names.includes('contacts'));
    assert.ok(names.includes('audit_log'));
    assert.ok(names.includes('usage_tracking'));
    assert.ok(names.includes('webhook_events'));
  });

  it('should insert and retrieve a fax with quality settings', () => {
    const id = uuidv4();
    db.prepare(`
      INSERT INTO faxes (id, direction, status, from_number, to_number, notes, quality, resolution)
      VALUES (?, 'outbound', 'queued', '15550000000', '15551111111', 'test fax', 'fine', '204x196')
    `).run(id);

    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(id);
    assert.equal(fax.id, id);
    assert.equal(fax.quality, 'fine');
    assert.equal(fax.resolution, '204x196');
    assert.equal(fax.retry_count, 0);
    assert.equal(fax.max_retries, 3);
  });

  it('should insert and retrieve a contact', () => {
    const id = uuidv4();
    db.prepare('INSERT INTO contacts (id, name, fax_number, company) VALUES (?, ?, ?, ?)')
      .run(id, 'Test User', '15552222222', 'Test Corp');

    const contact = db.prepare('SELECT * FROM contacts WHERE id = ?').get(id);
    assert.equal(contact.name, 'Test User');
    assert.equal(contact.fax_number, '15552222222');
  });

  it('should enforce valid fax direction', () => {
    assert.throws(() => {
      db.prepare(`
        INSERT INTO faxes (id, direction, from_number, to_number)
        VALUES (?, 'invalid', '15550000000', '15551111111')
      `).run(uuidv4());
    });
  });

  it('should enforce valid fax status', () => {
    assert.throws(() => {
      db.prepare(`
        INSERT INTO faxes (id, direction, status, from_number, to_number)
        VALUES (?, 'outbound', 'bad_status', '15550000000', '15551111111')
      `).run(uuidv4());
    });
  });

  it('should accept new statuses: sent, busy, no_answer', () => {
    for (const status of ['sent', 'busy', 'no_answer']) {
      const id = uuidv4();
      db.prepare(`
        INSERT INTO faxes (id, direction, status, from_number, to_number)
        VALUES (?, 'outbound', ?, '15550000000', '15551111111')
      `).run(id, status);

      const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(id);
      assert.equal(fax.status, status);
    }
  });

  it('should enforce valid quality setting', () => {
    assert.throws(() => {
      db.prepare(`
        INSERT INTO faxes (id, direction, from_number, to_number, quality)
        VALUES (?, 'outbound', '15550000000', '15551111111', 'ultra')
      `).run(uuidv4());
    });
  });

  it('should write to audit_log', () => {
    db.prepare(`
      INSERT INTO audit_log (action, resource_type, resource_id, details, ip_address)
      VALUES ('test_action', 'fax', 'test-id', 'test details', '127.0.0.1')
    `).run();

    const log = db.prepare("SELECT * FROM audit_log WHERE action = 'test_action'").get();
    assert.equal(log.resource_type, 'fax');
    assert.equal(log.ip_address, '127.0.0.1');
  });

  it('should track usage', () => {
    const today = new Date().toISOString().slice(0, 10);
    db.prepare('INSERT OR IGNORE INTO usage_tracking (date, faxes_sent, pages_sent) VALUES (?, 0, 0)').run(today);
    db.prepare('UPDATE usage_tracking SET faxes_sent = faxes_sent + 1 WHERE date = ?').run(today);

    const usage = db.prepare('SELECT * FROM usage_tracking WHERE date = ?').get(today);
    assert.ok(usage.faxes_sent >= 1);
  });

  it('should store webhook events', () => {
    db.prepare(`
      INSERT INTO webhook_events (event_type, fax_id, payload)
      VALUES ('fax_delivered', 'test-fax-id', '{"status":"success"}')
    `).run();

    const event = db.prepare("SELECT * FROM webhook_events WHERE fax_id = 'test-fax-id'").get();
    assert.equal(event.event_type, 'fax_delivered');
    assert.equal(event.processed, 0);
  });

  it('should delete a fax', () => {
    const id = uuidv4();
    db.prepare(`
      INSERT INTO faxes (id, direction, from_number, to_number)
      VALUES (?, 'outbound', '15550000000', '15551111111')
    `).run(id);

    db.prepare('DELETE FROM faxes WHERE id = ?').run(id);
    assert.equal(db.prepare('SELECT * FROM faxes WHERE id = ?').get(id), undefined);
  });

  it('should update fax status to delivered', () => {
    const id = uuidv4();
    db.prepare(`
      INSERT INTO faxes (id, direction, from_number, to_number)
      VALUES (?, 'outbound', '15550000000', '15551111111')
    `).run(id);

    db.prepare("UPDATE faxes SET status = 'delivered' WHERE id = ?").run(id);
    assert.equal(db.prepare('SELECT * FROM faxes WHERE id = ?').get(id).status, 'delivered');
  });
});

describe('Error Categorization', () => {
  it('should categorize busy errors', () => {
    assert.equal(categorizeError('Line is busy'), 'busy');
  });

  it('should categorize no answer errors', () => {
    assert.equal(categorizeError('No answer from recipient'), 'no_answer');
  });

  it('should categorize network errors', () => {
    assert.equal(categorizeError('Network timeout'), 'network_error');
    assert.equal(categorizeError('Connection refused'), 'network_error');
  });

  it('should categorize invalid number errors', () => {
    assert.equal(categorizeError('Invalid fax number'), 'invalid_number');
  });

  it('should categorize unknown errors as other', () => {
    assert.equal(categorizeError('Something went wrong'), 'other');
  });
});

describe('Retry Logic', () => {
  it('should mark busy and network errors as retryable', () => {
    assert.ok(isRetryable('busy'));
    assert.ok(isRetryable('no_answer'));
    assert.ok(isRetryable('network_error'));
  });

  it('should not retry invalid number or other errors', () => {
    assert.ok(!isRetryable('invalid_number'));
    assert.ok(!isRetryable('other'));
    assert.ok(!isRetryable('limit_exceeded'));
  });

  it('should calculate next retry time in the future', () => {
    const nextRetry = getNextRetryTime(0);
    assert.ok(new Date(nextRetry) > new Date());
  });
});

describe('Fax Number Validation', () => {
  it('should accept valid fax numbers', () => {
    assert.ok(validateFaxNumber('15551234567'));
    assert.ok(validateFaxNumber('1-555-123-4567'));
    assert.ok(validateFaxNumber('+1 (555) 123-4567'));
    assert.ok(validateFaxNumber('5551234567'));
  });

  it('should reject invalid fax numbers', () => {
    assert.ok(!validateFaxNumber(''));
    assert.ok(!validateFaxNumber('abc'));
    assert.ok(!validateFaxNumber('123'));
    assert.ok(!validateFaxNumber(null));
  });
});

describe('Input Sanitization', () => {
  it('should strip HTML tags', () => {
    assert.equal(sanitizeString('<script>alert("xss")</script>'), 'scriptalert("xss")/script');
  });

  it('should trim whitespace', () => {
    assert.equal(sanitizeString('  hello  '), 'hello');
  });

  it('should truncate long strings', () => {
    const long = 'a'.repeat(2000);
    assert.equal(sanitizeString(long).length, 1000);
  });

  it('should return non-strings unchanged', () => {
    assert.equal(sanitizeString(42), 42);
    assert.equal(sanitizeString(null), null);
  });
});

describe('Receipt Generation', () => {
  it('should generate a receipt for a delivered fax', () => {
    const fax = {
      id: 'test-id-12345678',
      status: 'delivered',
      direction: 'outbound',
      from_name: 'John',
      from_number: '15550000000',
      from_email: 'john@example.com',
      to_name: 'Jane',
      to_number: '15551111111',
      page_count: 2,
      quality: 'fine',
      resolution: '204x196',
      retry_count: 0,
      created_at: '2026-01-01 12:00:00',
      updated_at: '2026-01-01 12:01:00',
    };

    const receipt = generateReceipt(fax);
    assert.ok(receipt.receiptId.startsWith('RCT-'));
    assert.equal(receipt.status, 'delivered');
    assert.ok(receipt.confirmation.message.includes('successfully'));
    assert.equal(receipt.document.quality, 'fine');
  });

  it('should generate a text receipt', () => {
    const fax = {
      id: 'test-id-12345678',
      status: 'failed',
      direction: 'outbound',
      from_name: 'John',
      from_number: '15550000000',
      to_name: 'Jane',
      to_number: '15551111111',
      page_count: 1,
      quality: 'standard',
      resolution: '204x98',
      error_message: 'Invalid number',
      retry_count: 3,
      created_at: '2026-01-01 12:00:00',
      updated_at: '2026-01-01 12:05:00',
    };

    const text = generateReceiptText(fax);
    assert.ok(text.includes('FAX TRANSMISSION RECEIPT'));
    assert.ok(text.includes('FAILED'));
    assert.ok(text.includes('Invalid number'));
  });
});
