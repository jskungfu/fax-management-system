const express = require('express');

function createRouter(db) {
  const router = express.Router();

  // Get audit log (HIPAA compliance)
  router.get('/', (req, res) => {
    const limit = Math.min(parseInt(req.query.limit) || 100, 500);
    const offset = parseInt(req.query.offset) || 0;
    const resourceType = req.query.type;

    let sql = 'SELECT * FROM audit_log WHERE 1=1';
    const params = [];

    if (resourceType) {
      sql += ' AND resource_type = ?';
      params.push(resourceType);
    }

    sql += ' ORDER BY created_at DESC LIMIT ? OFFSET ?';
    params.push(limit, offset);

    const logs = db.prepare(sql).all(...params);
    const total = db.prepare('SELECT COUNT(*) as count FROM audit_log').get().count;

    res.json({ logs, total, limit, offset });
  });

  return router;
}

module.exports = createRouter;
