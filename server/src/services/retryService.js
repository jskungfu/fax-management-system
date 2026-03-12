const { sendFax, isRetryable } = require('./faxService');
const path = require('path');

const UPLOADS_DIR = path.join(__dirname, '..', '..', '..', 'uploads');

// Exponential backoff: 2min, 5min, 15min
const RETRY_DELAYS_MS = [2 * 60_000, 5 * 60_000, 15 * 60_000];

/**
 * Calculate the next retry timestamp based on attempt number.
 */
function getNextRetryTime(retryCount) {
  const delayMs = RETRY_DELAYS_MS[Math.min(retryCount, RETRY_DELAYS_MS.length - 1)];
  return new Date(Date.now() + delayMs).toISOString().replace('T', ' ').slice(0, 19);
}

/**
 * Process a single fax retry attempt.
 */
async function retryFax(db, fax, auditLog) {
  const apiKey = process.env.FAXZERO_API_KEY;
  if (!apiKey) return;

  try {
    db.prepare("UPDATE faxes SET status = 'sending', updated_at = datetime('now') WHERE id = ?")
      .run(fax.id);

    const result = await sendFax({
      apiKey,
      fromName: fax.from_name || '',
      fromNumber: fax.from_number,
      fromEmail: fax.from_email || '',
      toName: fax.to_name || '',
      toNumber: fax.to_number,
      coverMessage: fax.notes || '',
      filePath: fax.file_path ? path.join(UPLOADS_DIR, fax.file_path) : null,
      quality: fax.quality || 'standard',
    });

    db.prepare(`
      UPDATE faxes SET status = 'sent', api_response = ?, api_fax_id = ?,
        retry_count = ?, updated_at = datetime('now'), next_retry_at = NULL
      WHERE id = ?
    `).run(JSON.stringify(result), result.fax_id || null, fax.retry_count + 1, fax.id);

    if (auditLog) auditLog('fax_retry_success', 'fax', fax.id, { attempt: fax.retry_count + 1 });
  } catch (err) {
    const errorCode = err.faxErrorCode || 'other';
    const newRetryCount = fax.retry_count + 1;
    const canRetry = isRetryable(errorCode) && newRetryCount < fax.max_retries;

    if (canRetry) {
      const nextRetry = getNextRetryTime(newRetryCount);
      db.prepare(`
        UPDATE faxes SET status = ?, error_message = ?, retry_count = ?,
          next_retry_at = ?, updated_at = datetime('now')
        WHERE id = ?
      `).run(errorCode === 'busy' ? 'busy' : 'failed', err.message, newRetryCount, nextRetry, fax.id);

      if (auditLog) auditLog('fax_retry_scheduled', 'fax', fax.id, {
        attempt: newRetryCount, nextRetry, errorCode,
      });
    } else {
      db.prepare(`
        UPDATE faxes SET status = 'failed', error_message = ?, retry_count = ?,
          next_retry_at = NULL, updated_at = datetime('now')
        WHERE id = ?
      `).run(
        `${err.message} (${errorCode === 'invalid_number' ? 'Not retryable: invalid number' : `Max retries reached (${newRetryCount})`})`,
        newRetryCount,
        fax.id
      );

      if (auditLog) auditLog('fax_retry_failed_final', 'fax', fax.id, {
        attempt: newRetryCount, errorCode, reason: isRetryable(errorCode) ? 'max_retries' : 'not_retryable',
      });
    }
  }
}

/**
 * Start the retry processor interval.
 * Checks every 60 seconds for faxes that need retrying.
 */
function startRetryProcessor(db, auditLog) {
  const interval = setInterval(async () => {
    const now = new Date().toISOString().replace('T', ' ').slice(0, 19);
    const pendingRetries = db.prepare(`
      SELECT * FROM faxes
      WHERE next_retry_at IS NOT NULL AND next_retry_at <= ?
        AND retry_count < max_retries
      ORDER BY next_retry_at ASC
      LIMIT 5
    `).all(now);

    for (const fax of pendingRetries) {
      await retryFax(db, fax, auditLog);
    }
  }, 60_000);

  // Allow cleanup
  return () => clearInterval(interval);
}

module.exports = { retryFax, startRetryProcessor, getNextRetryTime };
