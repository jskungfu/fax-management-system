const express = require('express');
const { getUsageToday, getUsageHistory } = require('../services/usageTracker');

function createRouter(db) {
  const router = express.Router();

  // Get today's usage
  router.get('/today', (_req, res) => {
    res.json(getUsageToday(db));
  });

  // Get usage history
  router.get('/history', (req, res) => {
    const days = Math.min(parseInt(req.query.days) || 30, 365);
    res.json(getUsageHistory(db, days));
  });

  return router;
}

module.exports = createRouter;
