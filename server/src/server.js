require('dotenv').config({ path: require('path').join(__dirname, '..', '..', '.env') });

const express = require('express');
const cors = require('cors');
const path = require('path');
const { createDb } = require('./database');
const { secureHeaders, rateLimit, sanitizeBody, createAuditLogger } = require('./middleware/security');
const createFaxRouter = require('./routes/faxes');
const createContactRouter = require('./routes/contacts');
const createWebhookRouter = require('./routes/webhooks');
const createUsageRouter = require('./routes/usage');
const createAuditRouter = require('./routes/audit');
const { startRetryProcessor } = require('./services/retryService');

const PORT = process.env.PORT || 3001;

const app = express();
const db = createDb();
const auditLog = createAuditLogger(db);

// Security middleware (HIPAA compliance)
app.use(secureHeaders);
app.use(rateLimit({ windowMs: 60_000, maxRequests: 60 }));
app.use(cors({ origin: process.env.CORS_ORIGIN || 'http://localhost:3000' }));
app.use(express.json({ limit: '1mb' }));
app.use(sanitizeBody);

// API routes
app.use('/api/faxes', createFaxRouter(db, auditLog));
app.use('/api/contacts', createContactRouter(db));
app.use('/api/webhooks', createWebhookRouter(db, auditLog));
app.use('/api/usage', createUsageRouter(db));
app.use('/api/audit', createAuditRouter(db));

// Health check
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Serve React build in production
const clientDist = path.join(__dirname, '..', '..', 'client', 'dist');
app.use(express.static(clientDist));
app.get('*', (_req, res) => {
  res.sendFile(path.join(clientDist, 'index.html'));
});

// Global error handler
app.use((err, _req, res, _next) => {
  console.error('Unhandled error:', err.message);
  auditLog('server_error', 'system', null, { error: err.message });
  res.status(500).json({ error: 'Internal server error' });
});

// Start retry processor
const stopRetryProcessor = startRetryProcessor(db, auditLog);

const server = app.listen(PORT, () => {
  console.log(`Fax Management Server running on http://localhost:${PORT}`);
  console.log('Security: HIPAA-compliant headers, rate limiting, audit logging enabled');
  console.log('Retry processor: Running (checks every 60s)');
});

// Graceful shutdown
process.on('SIGTERM', () => {
  stopRetryProcessor();
  server.close(() => {
    db.close();
    process.exit(0);
  });
});

module.exports = app;
