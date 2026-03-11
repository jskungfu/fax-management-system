/**
 * HIPAA-compliant security middleware.
 * - Secure HTTP headers
 * - Input sanitization
 * - Rate limiting
 * - Audit logging
 */

// Simple in-memory rate limiter (per IP)
const rateLimitStore = new Map();

function rateLimit({ windowMs = 60_000, maxRequests = 30 } = {}) {
  return (req, res, next) => {
    const ip = req.ip || req.socket.remoteAddress;
    const now = Date.now();
    const key = ip;

    if (!rateLimitStore.has(key)) {
      rateLimitStore.set(key, { count: 1, resetAt: now + windowMs });
      return next();
    }

    const entry = rateLimitStore.get(key);
    if (now > entry.resetAt) {
      entry.count = 1;
      entry.resetAt = now + windowMs;
      return next();
    }

    entry.count++;
    if (entry.count > maxRequests) {
      return res.status(429).json({ error: 'Too many requests. Please try again later.' });
    }
    next();
  };
}

// Secure HTTP headers (HIPAA requirement: protect data in transit)
function secureHeaders(req, res, next) {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('X-XSS-Protection', '1; mode=block');
  res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, private');
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
  res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
  next();
}

// Sanitize string inputs to prevent injection
function sanitizeString(str) {
  if (typeof str !== 'string') return str;
  return str
    .replace(/[<>]/g, '') // Strip HTML tags
    .trim()
    .slice(0, 1000); // Limit length
}

function sanitizeBody(req, _res, next) {
  if (req.body && typeof req.body === 'object') {
    for (const [key, value] of Object.entries(req.body)) {
      if (typeof value === 'string') {
        req.body[key] = sanitizeString(value);
      }
    }
  }
  next();
}

// Validate fax number format (E.164-ish or common formats)
function validateFaxNumber(number) {
  if (!number || typeof number !== 'string') return false;
  const cleaned = number.replace(/[\s\-().+]/g, '');
  return /^\d{7,15}$/.test(cleaned);
}

// Audit logger
function createAuditLogger(db) {
  return (action, resourceType, resourceId, details, req) => {
    try {
      db.prepare(`
        INSERT INTO audit_log (action, resource_type, resource_id, details, ip_address, user_agent)
        VALUES (?, ?, ?, ?, ?, ?)
      `).run(
        action,
        resourceType,
        resourceId || null,
        typeof details === 'object' ? JSON.stringify(details) : (details || null),
        req?.ip || req?.socket?.remoteAddress || null,
        req?.headers?.['user-agent'] || null
      );
    } catch {
      // Don't let audit failures break the request
      console.error('Audit log write failed');
    }
  };
}

module.exports = {
  rateLimit,
  secureHeaders,
  sanitizeBody,
  sanitizeString,
  validateFaxNumber,
  createAuditLogger,
};
