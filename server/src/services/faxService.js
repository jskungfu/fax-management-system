const fs = require('fs');
const path = require('path');
const https = require('https');

const FAXZERO_API_URL = 'https://api.faxzero.com/fax/send';

// Quality mode mappings
const QUALITY_SETTINGS = {
  standard: { resolution: '204x98', description: 'Standard quality (fastest)' },
  fine: { resolution: '204x196', description: 'Fine quality (better text clarity)' },
  superfine: { resolution: '204x391', description: 'Super-fine quality (highest detail)' },
};

/**
 * Send a fax via the FaxZero API with quality settings.
 * Free tier: 3 faxes/day, up to 3 pages + cover page.
 * Supports T.38 protocol for Fax-over-IP quality.
 *
 * @param {Object} params
 * @param {string} params.apiKey - FaxZero API key
 * @param {string} params.fromName - Sender name
 * @param {string} params.fromNumber - Sender fax/phone number
 * @param {string} params.fromEmail - Sender email (for confirmations)
 * @param {string} params.toName - Recipient name
 * @param {string} params.toNumber - Recipient fax number
 * @param {string} params.coverMessage - Cover page message
 * @param {string} params.filePath - Path to document file
 * @param {string} params.quality - Quality mode: standard, fine, superfine
 */
function sendFax({ apiKey, fromName, fromNumber, fromEmail, toName, toNumber, coverMessage, filePath, quality = 'standard' }) {
  return new Promise((resolve, reject) => {
    const qualityConfig = QUALITY_SETTINGS[quality] || QUALITY_SETTINGS.standard;

    const payload = {
      api_key: apiKey,
      api_environment: 'production',
      fax_header: `To: ${toName || toNumber}`,
      fax_header_enabled: true,
      sender_name: fromName,
      sender_fax: fromNumber,
      sender_email: fromEmail,
      recipient_name: toName || '',
      recipient_fax: toNumber,
      // T.38 and quality settings
      fax_quality: quality,
      resolution: qualityConfig.resolution,
    };

    if (coverMessage) {
      payload.cover_message = coverMessage;
    }

    // Attach document as base64
    if (filePath && fs.existsSync(filePath)) {
      const fileBuffer = fs.readFileSync(filePath);
      const ext = path.extname(filePath).toLowerCase().replace('.', '');
      const mimeTypes = {
        pdf: 'application/pdf',
        doc: 'application/msword',
        docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        txt: 'text/plain',
        png: 'image/png',
        jpg: 'image/jpeg',
        jpeg: 'image/jpeg',
        tif: 'image/tiff',
        tiff: 'image/tiff',
      };

      payload.document_content = fileBuffer.toString('base64');
      payload.document_type = mimeTypes[ext] || 'application/octet-stream';
    }

    const postData = JSON.stringify(payload);
    const url = new URL(FAXZERO_API_URL);

    const options = {
      hostname: url.hostname,
      path: url.pathname,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData),
      },
    };

    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try {
          const result = JSON.parse(body);
          if (result.success) {
            resolve(result);
          } else {
            // Categorize the error for retry logic
            const error = new Error(result.message || 'FaxZero API error');
            error.faxErrorCode = categorizeError(result.message || '');
            reject(error);
          }
        } catch {
          reject(new Error(`Failed to parse FaxZero response: ${body}`));
        }
      });
    });

    req.on('error', (err) => {
      err.faxErrorCode = 'network_error';
      reject(err);
    });

    req.write(postData);
    req.end();
  });
}

/**
 * Categorize fax errors for retry logic.
 * Returns: 'busy', 'network_error', 'invalid_number', 'limit_exceeded', 'other'
 */
function categorizeError(message) {
  const msg = message.toLowerCase();
  if (msg.includes('busy')) return 'busy';
  if (msg.includes('no answer')) return 'no_answer';
  if (msg.includes('network') || msg.includes('timeout') || msg.includes('connection')) return 'network_error';
  if (msg.includes('invalid') && (msg.includes('number') || msg.includes('fax'))) return 'invalid_number';
  if (msg.includes('limit') || msg.includes('exceed') || msg.includes('quota')) return 'limit_exceeded';
  return 'other';
}

// Errors that should trigger automatic retry
const RETRYABLE_ERRORS = new Set(['busy', 'no_answer', 'network_error']);

function isRetryable(errorCode) {
  return RETRYABLE_ERRORS.has(errorCode);
}

module.exports = { sendFax, categorizeError, isRetryable, QUALITY_SETTINGS };
