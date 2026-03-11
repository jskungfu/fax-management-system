require('dotenv').config({ path: require('path').join(__dirname, '..', '..', '.env') });

const express = require('express');
const cors = require('cors');
const path = require('path');
const { createDb } = require('./database');
const createFaxRouter = require('./routes/faxes');
const createContactRouter = require('./routes/contacts');

const PORT = process.env.PORT || 3001;

const app = express();
const db = createDb();

app.use(cors());
app.use(express.json());

// API routes
app.use('/api/faxes', createFaxRouter(db));
app.use('/api/contacts', createContactRouter(db));

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

app.listen(PORT, () => {
  console.log(`Fax Management Server running on http://localhost:${PORT}`);
});

module.exports = app;
