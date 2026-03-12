const express = require('express');
const { generateReceipt } = require('../services/receiptService');

/**
 * Webhook listener for real-time fax status updates.
 * Receives callbacks from the fax provider with delivery status.
 *
 * Expected webhook payload:
 * {
 *   fax_id: string,       // The API fax ID
 *   status: string,       // 'success', 'failed', 'busy', 'no_answer'
 *   message: string,      // Human-readable status message
 *   pages: number,        // Number of pages transmitted
 *   timestamp: string     // ISO timestamp
 * }
 */
function createRouter(db, auditLog) {
  const router = express.Router();

  // Status mapping from webhook status to internal status
  const STATUS_MAP = {
    success: 'delivered',
    delivered: 'delivered',
    failed: 'failed',
    busy: 'busy',
    no_answer: 'no_answer',
    sending: 'sending',
    queued: 'queued',
  };

  // Receive webhook callback
  router.post('/status', (req, res) => {
    const { fax_id, status, message, pages, timestamp } = req.body;

    if (!fax_id || !status) {
      return res.status(400).json({ error: 'fax_id and status are required' });
    }

    const internalStatus = STATUS_MAP[status.toLowerCase()] || 'failed';

    // Log the webhook event
    db.prepare(`
      INSERT INTO webhook_events (event_type, fax_id, payload)
      VALUES (?, ?, ?)
    `).run(`fax_${internalStatus}`, fax_id, JSON.stringify(req.body));

    // Find and update the fax by api_fax_id
    const fax = db.prepare('SELECT * FROM faxes WHERE api_fax_id = ?').get(fax_id);

    if (!fax) {
      auditLog('webhook_fax_not_found', 'webhook', null, { fax_id, status }, req);
      // Still return 200 to acknowledge receipt (avoid retries from provider)
      return res.json({ received: true, matched: false });
    }

    // Update fax status
    db.prepare(`
      UPDATE faxes SET status = ?, updated_at = datetime('now'),
        page_count = COALESCE(?, page_count)
      WHERE id = ?
    `).run(internalStatus, pages || null, fax.id);

    auditLog('webhook_status_update', 'fax', fax.id, {
      webhookStatus: status,
      internalStatus,
      message,
      timestamp,
    }, req);

    // Generate transmission receipt on delivery
    if (internalStatus === 'delivered') {
      const updatedFax = db.prepare('SELECT * FROM faxes WHERE id = ?').get(fax.id);
      const receipt = JSON.stringify(generateReceipt(updatedFax));
      db.prepare('UPDATE faxes SET transmission_receipt = ? WHERE id = ?').run(receipt, fax.id);
      auditLog('receipt_generated', 'fax', fax.id, null, req);
    }

    // Clear retry schedule on terminal states
    if (['delivered', 'failed'].includes(internalStatus)) {
      db.prepare('UPDATE faxes SET next_retry_at = NULL WHERE id = ?').run(fax.id);
    }

    res.json({ received: true, matched: true, faxId: fax.id, status: internalStatus });
  });

  // List webhook events (for debugging)
  router.get('/events', (req, res) => {
    const limit = Math.min(parseInt(req.query.limit) || 50, 200);
    const events = db.prepare('SELECT * FROM webhook_events ORDER BY created_at DESC LIMIT ?').all(limit);
    auditLog('list_webhook_events', 'webhook', null, { limit }, req);
    res.json(events);
  });

  return router;
}

module.exports = createRouter;
