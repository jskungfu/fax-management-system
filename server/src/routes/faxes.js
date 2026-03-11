const express = require('express');
const { v4: uuidv4 } = require('uuid');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { sendFax, isRetryable, QUALITY_SETTINGS } = require('../services/faxService');
const { getNextRetryTime } = require('../services/retryService');
const { getUsageToday, incrementUsage } = require('../services/usageTracker');
const { generateReceipt, generateReceiptText } = require('../services/receiptService');
const { validateFaxNumber } = require('../middleware/security');

const UPLOADS_DIR = path.join(__dirname, '..', '..', '..', 'uploads');

function createRouter(db, auditLog) {
  const router = express.Router();
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });

  const storage = multer.diskStorage({
    destination: UPLOADS_DIR,
    filename: (_req, file, cb) => {
      cb(null, `${uuidv4()}${path.extname(file.originalname)}`);
    },
  });
  const upload = multer({
    storage,
    limits: { fileSize: 10 * 1024 * 1024 },
    fileFilter: (_req, file, cb) => {
      const allowed = ['.pdf', '.doc', '.docx', '.txt', '.png', '.jpg', '.jpeg', '.tif', '.tiff'];
      const ext = path.extname(file.originalname).toLowerCase();
      if (!allowed.includes(ext)) {
        return cb(new Error(`File type ${ext} not allowed. Accepted: ${allowed.join(', ')}`));
      }
      cb(null, true);
    },
  });

  // List faxes
  router.get('/', (req, res) => {
    const { status, direction } = req.query;
    let sql = 'SELECT * FROM faxes WHERE 1=1';
    const params = [];

    if (status) {
      sql += ' AND status = ?';
      params.push(status);
    }
    if (direction) {
      sql += ' AND direction = ?';
      params.push(direction);
    }
    sql += ' ORDER BY created_at DESC';

    auditLog('list_faxes', 'fax', null, { status, direction }, req);
    res.json(db.prepare(sql).all(...params));
  });

  // Get single fax
  router.get('/:id', (req, res) => {
    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(req.params.id);
    if (!fax) return res.status(404).json({ error: 'Fax not found' });
    auditLog('view_fax', 'fax', fax.id, null, req);
    res.json(fax);
  });

  // Get transmission receipt
  router.get('/:id/receipt', (req, res) => {
    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(req.params.id);
    if (!fax) return res.status(404).json({ error: 'Fax not found' });

    const format = req.query.format || 'json';
    auditLog('view_receipt', 'fax', fax.id, { format }, req);

    if (format === 'text') {
      res.type('text/plain').send(generateReceiptText(fax));
    } else {
      res.json(generateReceipt(fax));
    }
  });

  // Get quality settings info
  router.get('/settings/quality', (_req, res) => {
    res.json(QUALITY_SETTINGS);
  });

  // Send a fax
  router.post('/send', upload.single('document'), async (req, res) => {
    const { to_number, to_name, from_number, from_name, from_email, notes, quality, page_count } = req.body;

    if (!to_number) {
      return res.status(400).json({ error: 'to_number is required' });
    }

    if (!validateFaxNumber(to_number)) {
      return res.status(400).json({ error: 'Invalid fax number format. Use digits with optional dashes/spaces (7-15 digits).' });
    }

    const apiKey = process.env.FAXZERO_API_KEY;
    if (!apiKey) {
      return res.status(500).json({ error: 'FAXZERO_API_KEY is not configured. See .env.example' });
    }

    // Check free tier usage
    const usage = getUsageToday(db);
    if (!usage.canSend) {
      auditLog('fax_blocked_limit', 'fax', null, { usage }, req);
      return res.status(429).json({
        error: `Daily free tier limit reached (${usage.dailyLimit} faxes/day). Try again tomorrow.`,
        usage,
      });
    }

    const pages = parseInt(page_count) || 0;
    if (pages > usage.pageLimit) {
      return res.status(400).json({
        error: `Free tier allows max ${usage.pageLimit} pages per fax. You specified ${pages}.`,
      });
    }

    const faxQuality = quality || 'standard';
    const qualityConfig = QUALITY_SETTINGS[faxQuality];
    if (!qualityConfig) {
      return res.status(400).json({ error: `Invalid quality. Use: ${Object.keys(QUALITY_SETTINGS).join(', ')}` });
    }

    const id = uuidv4();
    const filePath = req.file ? req.file.filename : null;
    const senderNumber = from_number || process.env.DEFAULT_FROM_FAX || '';
    const senderName = from_name || process.env.DEFAULT_FROM_NAME || '';
    const senderEmail = from_email || process.env.DEFAULT_FROM_EMAIL || '';

    // Insert as queued
    db.prepare(`
      INSERT INTO faxes (id, direction, status, from_name, from_number, from_email,
        to_name, to_number, page_count, file_path, notes, quality, resolution)
      VALUES (?, 'outbound', 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).run(id, senderName, senderNumber, senderEmail, to_name || '',
      to_number, pages, filePath, notes || null, faxQuality, qualityConfig.resolution);

    auditLog('fax_send_initiated', 'fax', id, { to_number, quality: faxQuality }, req);

    // Attempt to send
    try {
      db.prepare("UPDATE faxes SET status = 'sending', updated_at = datetime('now') WHERE id = ?").run(id);

      const result = await sendFax({
        apiKey,
        fromName: senderName,
        fromNumber: senderNumber,
        fromEmail: senderEmail,
        toName: to_name || '',
        toNumber: to_number,
        coverMessage: notes || '',
        filePath: filePath ? path.join(UPLOADS_DIR, filePath) : null,
        quality: faxQuality,
      });

      db.prepare(`
        UPDATE faxes SET status = 'sent', api_response = ?, api_fax_id = ?,
          updated_at = datetime('now')
        WHERE id = ?
      `).run(JSON.stringify(result), result.fax_id || null, id);

      incrementUsage(db, pages);
      auditLog('fax_sent', 'fax', id, { api_fax_id: result.fax_id }, req);
    } catch (err) {
      const errorCode = err.faxErrorCode || 'other';
      const canRetry = isRetryable(errorCode);

      if (canRetry) {
        const nextRetry = getNextRetryTime(0);
        db.prepare(`
          UPDATE faxes SET status = ?, error_message = ?, next_retry_at = ?,
            updated_at = datetime('now')
          WHERE id = ?
        `).run(errorCode === 'busy' ? 'busy' : (errorCode === 'no_answer' ? 'no_answer' : 'failed'),
          err.message, nextRetry, id);

        auditLog('fax_retry_scheduled', 'fax', id, { errorCode, nextRetry }, req);
      } else {
        db.prepare(`
          UPDATE faxes SET status = 'failed', error_message = ?,
            updated_at = datetime('now')
          WHERE id = ?
        `).run(`${err.message} (Not retryable: ${errorCode})`, id);

        auditLog('fax_failed', 'fax', id, { errorCode, message: err.message }, req);
      }
    }

    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(id);
    res.status(201).json(fax);
  });

  // Update fax status (used by webhooks)
  router.patch('/:id/status', (req, res) => {
    const { status } = req.body;
    const valid = ['queued', 'sending', 'sent', 'delivered', 'failed', 'busy', 'no_answer', 'received'];
    if (!status || !valid.includes(status)) {
      return res.status(400).json({ error: `status must be one of: ${valid.join(', ')}` });
    }

    const result = db.prepare(
      "UPDATE faxes SET status = ?, updated_at = datetime('now') WHERE id = ?"
    ).run(status, req.params.id);

    if (result.changes === 0) return res.status(404).json({ error: 'Fax not found' });

    auditLog('fax_status_updated', 'fax', req.params.id, { status }, req);

    // Generate receipt on delivery
    if (status === 'delivered') {
      const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(req.params.id);
      const receipt = JSON.stringify(generateReceipt(fax));
      db.prepare('UPDATE faxes SET transmission_receipt = ? WHERE id = ?').run(receipt, req.params.id);
    }

    res.json(db.prepare('SELECT * FROM faxes WHERE id = ?').get(req.params.id));
  });

  // Delete fax
  router.delete('/:id', (req, res) => {
    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(req.params.id);
    if (!fax) return res.status(404).json({ error: 'Fax not found' });

    if (fax.file_path) {
      const fullPath = path.join(UPLOADS_DIR, fax.file_path);
      if (fs.existsSync(fullPath)) fs.unlinkSync(fullPath);
    }

    db.prepare('DELETE FROM faxes WHERE id = ?').run(req.params.id);
    auditLog('fax_deleted', 'fax', req.params.id, null, req);
    res.json({ message: 'Fax deleted' });
  });

  return router;
}

module.exports = createRouter;
