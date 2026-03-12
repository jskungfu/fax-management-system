import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { getFaxes, getUsageToday } from '../api';

export default function Dashboard() {
  const [stats, setStats] = useState({ total: 0, delivered: 0, failed: 0, pending: 0 });
  const [usage, setUsage] = useState(null);
  const [recentFaxes, setRecentFaxes] = useState([]);

  useEffect(() => {
    getUsageToday().then(setUsage).catch(() => {});
    getFaxes().then((faxes) => {
      setRecentFaxes(faxes.slice(0, 5));
      setStats({
        total: faxes.length,
        delivered: faxes.filter((f) => f.status === 'delivered' || f.status === 'sent').length,
        failed: faxes.filter((f) => f.status === 'failed').length,
        pending: faxes.filter((f) => ['queued', 'sending', 'busy', 'no_answer'].includes(f.status)).length,
      });
    }).catch(() => {});
  }, []);

  const formatDate = (d) => d ? new Date(d + 'Z').toLocaleString() : '-';

  return (
    <div>
      <h1>Dashboard</h1>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px' }}>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '32px', fontWeight: 700, color: 'var(--primary)' }}>{stats.total}</div>
          <div style={{ color: 'var(--gray-500)', fontSize: '14px' }}>Total Faxes</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '32px', fontWeight: 700, color: 'var(--success)' }}>{stats.delivered}</div>
          <div style={{ color: 'var(--gray-500)', fontSize: '14px' }}>Delivered</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '32px', fontWeight: 700, color: 'var(--danger)' }}>{stats.failed}</div>
          <div style={{ color: 'var(--gray-500)', fontSize: '14px' }}>Failed</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '32px', fontWeight: 700, color: 'var(--warning)' }}>{stats.pending}</div>
          <div style={{ color: 'var(--gray-500)', fontSize: '14px' }}>Pending/Retry</div>
        </div>
      </div>

      {usage && (
        <div className="card" style={{ marginBottom: '24px' }}>
          <h2 style={{ fontSize: '16px', marginBottom: '12px' }}>Free Tier Usage Today</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ flex: 1, background: 'var(--gray-200)', borderRadius: '8px', height: '24px', overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(100, (usage.faxesSent / usage.dailyLimit) * 100)}%`,
                height: '100%',
                background: usage.canSend ? 'var(--primary)' : 'var(--danger)',
                borderRadius: '8px',
                transition: 'width 0.3s',
              }} />
            </div>
            <span style={{ fontSize: '14px', fontWeight: 600, whiteSpace: 'nowrap' }}>
              {usage.faxesSent} / {usage.dailyLimit}
            </span>
          </div>
          <div style={{ marginTop: '8px', fontSize: '13px', color: 'var(--gray-500)' }}>
            {usage.canSend ? `${usage.remaining} faxes remaining today` : 'Daily limit reached. Resets at midnight.'}
          </div>
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '16px', margin: 0 }}>Recent Faxes</h2>
          <Link to="/history" style={{ fontSize: '14px' }}>View All</Link>
        </div>

        {recentFaxes.length === 0 ? (
          <div className="empty-state">
            No faxes yet. <Link to="/send">Send your first fax</Link>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>To</th>
                <th>Status</th>
                <th>Quality</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {recentFaxes.map((fax) => (
                <tr key={fax.id}>
                  <td>{fax.to_name || fax.to_number}</td>
                  <td><span className={`badge ${fax.status}`}>{fax.status}</span></td>
                  <td style={{ fontSize: '13px' }}>{fax.quality || 'standard'}</td>
                  <td style={{ fontSize: '13px' }}>{formatDate(fax.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
