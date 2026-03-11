const express = require('express');
const { v4: uuidv4 } = require('uuid');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const { sendFax } = require('../services/faxService');

const UPLOADS_DIR = path.join(__dirname, '..', '..', '..', 'uploads');

function createRouter(db) {
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
      cb(null, allowed.includes(ext));
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

    res.json(db.prepare(sql).all(...params));
  });

  // Get single fax
  router.get('/:id', (req, res) => {
    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(req.params.id);
    if (!fax) return res.status(404).json({ error: 'Fax not found' });
    res.json(fax);
  });

  // Send a fax
  router.post('/send', upload.single('document'), async (req, res) => {
    const { to_number, to_name, from_number, from_name, from_email, notes } = req.body;

    if (!to_number) {
      return res.status(400).json({ error: 'to_number is required' });
    }

    const apiKey = process.env.FAXZERO_API_KEY;
    if (!apiKey) {
      return res.status(500).json({ error: 'FAXZERO_API_KEY is not configured. See .env.example' });
    }

    const id = uuidv4();
    const filePath = req.file ? req.file.filename : null;
    const senderNumber = from_number || process.env.DEFAULT_FROM_FAX || '';
    const senderName = from_name || process.env.DEFAULT_FROM_NAME || '';
    const senderEmail = from_email || process.env.DEFAULT_FROM_EMAIL || '';

    // Insert as queued
    db.prepare(`
      INSERT INTO faxes (id, direction, status, from_name, from_number, from_email, to_name, to_number, file_path, notes)
      VALUES (?, 'outbound', 'queued', ?, ?, ?, ?, ?, ?, ?)
    `).run(id, senderName, senderNumber, senderEmail, to_name || '', to_number, filePath, notes || null);

    // Attempt to send via FaxZero
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
      });

      db.prepare(`
        UPDATE faxes SET status = 'delivered', api_response = ?, updated_at = datetime('now') WHERE id = ?
      `).run(JSON.stringify(result), id);
    } catch (err) {
      db.prepare(`
        UPDATE faxes SET status = 'failed', error_message = ?, updated_at = datetime('now') WHERE id = ?
      `).run(err.message, id);
    }

    const fax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(id);
    res.status(201).json(fax);
  });

  // Update fax status
  router.patch('/:id/status', (req, res) => {
    const { status } = req.body;
    const valid = ['queued', 'sending', 'delivered', 'failed', 'received'];
    if (!status || !valid.includes(status)) {
      return res.status(400).json({ error: `status must be one of: ${valid.join(', ')}` });
    }

    const result = db.prepare(
      "UPDATE faxes SET status = ?, updated_at = datetime('now') WHERE id = ?"
    ).run(status, req.params.id);

    if (result.changes === 0) return res.status(404).json({ error: 'Fax not found' });
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
    res.json({ message: 'Fax deleted' });
  });

  return router;
}

module.exports = createRouter;
