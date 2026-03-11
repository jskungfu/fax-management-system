import { useState, useEffect } from 'react';
import { getFaxes, deleteFax } from '../api';

export default function FaxHistory() {
  const [faxes, setFaxes] = useState([]);
  const [filters, setFilters] = useState({ status: '', direction: '' });
  const [loading, setLoading] = useState(true);

  const loadFaxes = async () => {
    setLoading(true);
    try {
      const params = {};
      if (filters.status) params.status = filters.status;
      if (filters.direction) params.direction = filters.direction;
      setFaxes(await getFaxes(params));
    } catch {
      setFaxes([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadFaxes(); }, [filters]);

  const handleDelete = async (id) => {
    if (!confirm('Delete this fax record?')) return;
    try {
      await deleteFax(id);
      setFaxes(faxes.filter((f) => f.id !== id));
    } catch {
      alert('Failed to delete fax');
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    return new Date(dateStr + 'Z').toLocaleString();
  };

  return (
    <div>
      <h1>Fax History</h1>

      <div className="filters">
        <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
          <option value="">All Statuses</option>
          <option value="queued">Queued</option>
          <option value="sending">Sending</option>
          <option value="delivered">Delivered</option>
          <option value="failed">Failed</option>
          <option value="received">Received</option>
        </select>
        <select value={filters.direction} onChange={(e) => setFilters({ ...filters, direction: e.target.value })}>
          <option value="">All Directions</option>
          <option value="outbound">Outbound</option>
          <option value="inbound">Inbound</option>
        </select>
      </div>

      <div className="card">
        {loading ? (
          <div className="empty-state">Loading...</div>
        ) : faxes.length === 0 ? (
          <div className="empty-state">No faxes found. Send your first fax!</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Direction</th>
                <th>To</th>
                <th>From</th>
                <th>Status</th>
                <th>Date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {faxes.map((fax) => (
                <tr key={fax.id}>
                  <td>{fax.direction === 'outbound' ? 'Sent' : 'Received'}</td>
                  <td>
                    <div>{fax.to_name || '-'}</div>
                    <small style={{ color: 'var(--gray-500)' }}>{fax.to_number}</small>
                  </td>
                  <td>
                    <div>{fax.from_name || '-'}</div>
                    <small style={{ color: 'var(--gray-500)' }}>{fax.from_number}</small>
                  </td>
                  <td><span className={`badge ${fax.status}`}>{fax.status}</span></td>
                  <td style={{ fontSize: '13px' }}>{formatDate(fax.created_at)}</td>
                  <td>
                    <div className="actions">
                      <button className="danger" onClick={() => handleDelete(fax.id)} style={{ fontSize: '12px', padding: '4px 10px' }}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
