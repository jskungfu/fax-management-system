const fs = require('fs');
const path = require('path');
const https = require('https');

const FAXZERO_API_URL = 'https://api.faxzero.com/fax/send';

/**
 * Send a fax via the FaxZero API.
 * Free tier: 3 faxes/day, up to 3 pages + cover page, ads on cover page.
 * See: https://faxzero.com/fax_api.php
 */
function sendFax({ apiKey, fromName, fromNumber, fromEmail, toName, toNumber, coverMessage, filePath }) {
  return new Promise((resolve, reject) => {
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
    };

    // Add cover page message if provided
    if (coverMessage) {
      payload.cover_message = coverMessage;
    }

    // Attach document file as base64
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
            reject(new Error(result.message || 'FaxZero API returned an error'));
          }
        } catch (e) {
          reject(new Error(`Failed to parse FaxZero response: ${body}`));
        }
      });
    });

    req.on('error', (err) => reject(err));
    req.write(postData);
    req.end();
  });
}

module.exports = { sendFax };
