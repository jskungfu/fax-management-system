import { useState, useEffect } from 'react';
import { getAuditLog } from '../api';

export default function AuditLog() {
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const loadLogs = async () => {
    setLoading(true);
    try {
      const result = await getAuditLog({ limit: 100 });
      setLogs(result.logs);
      setTotal(result.total);
    } catch {
      setLogs([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadLogs(); }, []);

  const formatDate = (d) => d ? new Date(d + 'Z').toLocaleString() : '-';

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h1 style={{ marginBottom: 0 }}>Audit Log (HIPAA)</h1>
        <span style={{ fontSize: '14px', color: 'var(--gray-500)' }}>{total} total entries</span>
      </div>

      <div className="card">
        {loading ? (
          <div className="empty-state">Loading...</div>
        ) : logs.length === 0 ? (
          <div className="empty-state">No audit entries yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Resource</th>
                <th>Details</th>
                <th>IP</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td style={{ fontFamily: 'monospace', fontSize: '13px' }}>{log.action}</td>
                  <td>
                    <span style={{ fontSize: '12px', color: 'var(--gray-500)' }}>{log.resource_type}</span>
                    {log.resource_id && (
                      <div style={{ fontSize: '11px', color: 'var(--gray-500)', fontFamily: 'monospace' }}>
                        {log.resource_id.slice(0, 8)}...
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: '12px', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {log.details || '-'}
                  </td>
                  <td style={{ fontSize: '12px', fontFamily: 'monospace' }}>{log.ip_address || '-'}</td>
                  <td style={{ fontSize: '12px' }}>{formatDate(log.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
