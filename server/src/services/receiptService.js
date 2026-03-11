/**
 * Transmission Receipt / Confirmation Report generator.
 * Generates a receipt once a fax is marked as 'delivered'.
 */

function generateReceipt(fax) {
  const receipt = {
    receiptId: `RCT-${fax.id.slice(0, 8).toUpperCase()}`,
    faxId: fax.id,
    status: fax.status,
    direction: fax.direction,
    sender: {
      name: fax.from_name || 'N/A',
      number: fax.from_number,
      email: fax.from_email || 'N/A',
    },
    recipient: {
      name: fax.to_name || 'N/A',
      number: fax.to_number,
    },
    document: {
      pageCount: fax.page_count || 0,
      quality: fax.quality || 'standard',
      resolution: fax.resolution || '204x98',
    },
    timing: {
      created: fax.created_at,
      lastUpdated: fax.updated_at,
      retryCount: fax.retry_count || 0,
    },
    generatedAt: new Date().toISOString(),
  };

  if (fax.status === 'delivered') {
    receipt.confirmation = {
      deliveredAt: fax.updated_at,
      message: 'Fax was successfully delivered and received by the target machine.',
    };
  } else if (fax.status === 'sent') {
    receipt.confirmation = {
      sentAt: fax.updated_at,
      message: 'Fax has left the server but delivery confirmation is pending.',
    };
  } else if (fax.status === 'failed') {
    receipt.confirmation = {
      failedAt: fax.updated_at,
      errorMessage: fax.error_message || 'Unknown error',
      message: 'Fax transmission failed.',
    };
  }

  return receipt;
}

function generateReceiptText(fax) {
  const r = generateReceipt(fax);
  const lines = [
    '═══════════════════════════════════════════════════',
    '          FAX TRANSMISSION RECEIPT',
    '═══════════════════════════════════════════════════',
    `  Receipt ID:    ${r.receiptId}`,
    `  Fax ID:        ${r.faxId}`,
    `  Status:        ${r.status.toUpperCase()}`,
    '───────────────────────────────────────────────────',
    '  SENDER',
    `    Name:        ${r.sender.name}`,
    `    Number:      ${r.sender.number}`,
    `    Email:       ${r.sender.email}`,
    '───────────────────────────────────────────────────',
    '  RECIPIENT',
    `    Name:        ${r.recipient.name}`,
    `    Number:      ${r.recipient.number}`,
    '───────────────────────────────────────────────────',
    '  DOCUMENT',
    `    Pages:       ${r.document.pageCount}`,
    `    Quality:     ${r.document.quality}`,
    `    Resolution:  ${r.document.resolution}`,
    '───────────────────────────────────────────────────',
    '  TRANSMISSION',
    `    Created:     ${r.timing.created}`,
    `    Updated:     ${r.timing.lastUpdated}`,
    `    Retries:     ${r.timing.retryCount}`,
    '───────────────────────────────────────────────────',
  ];

  if (r.confirmation) {
    lines.push(`  ${r.confirmation.message}`);
    if (r.confirmation.errorMessage) {
      lines.push(`  Error: ${r.confirmation.errorMessage}`);
    }
  }

  lines.push('═══════════════════════════════════════════════════');
  lines.push(`  Generated: ${r.generatedAt}`);
  lines.push('═══════════════════════════════════════════════════');

  return lines.join('\n');
}

module.exports = { generateReceipt, generateReceiptText };
