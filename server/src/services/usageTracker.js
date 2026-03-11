/**
 * Free tier usage tracking.
 * Tracks daily fax sends and page counts against configurable limits.
 */

const DEFAULT_DAILY_LIMIT = 3;   // FaxZero free tier: 3 faxes/day
const DEFAULT_PAGE_LIMIT = 3;    // FaxZero free tier: 3 pages per fax (+ cover)

function getToday() {
  return new Date().toISOString().slice(0, 10);
}

function getUsageToday(db) {
  const today = getToday();
  let usage = db.prepare('SELECT * FROM usage_tracking WHERE date = ?').get(today);

  if (!usage) {
    db.prepare('INSERT INTO usage_tracking (date, faxes_sent, pages_sent) VALUES (?, 0, 0)').run(today);
    usage = { date: today, faxes_sent: 0, pages_sent: 0 };
  }

  const dailyLimit = parseInt(process.env.DAILY_FAX_LIMIT) || DEFAULT_DAILY_LIMIT;

  return {
    date: usage.date,
    faxesSent: usage.faxes_sent,
    pagesSent: usage.pages_sent,
    dailyLimit,
    pageLimit: DEFAULT_PAGE_LIMIT,
    remaining: Math.max(0, dailyLimit - usage.faxes_sent),
    canSend: usage.faxes_sent < dailyLimit,
  };
}

function incrementUsage(db, pageCount = 0) {
  const today = getToday();
  // Ensure row exists
  db.prepare('INSERT OR IGNORE INTO usage_tracking (date, faxes_sent, pages_sent) VALUES (?, 0, 0)').run(today);
  db.prepare('UPDATE usage_tracking SET faxes_sent = faxes_sent + 1, pages_sent = pages_sent + ? WHERE date = ?')
    .run(pageCount, today);
}

function getUsageHistory(db, days = 30) {
  return db.prepare(`
    SELECT * FROM usage_tracking
    ORDER BY date DESC
    LIMIT ?
  `).all(days);
}

module.exports = { getUsageToday, incrementUsage, getUsageHistory };
