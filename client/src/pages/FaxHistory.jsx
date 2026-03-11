import { useState, useEffect } from 'react';
import { getFaxes, deleteFax, getFaxReceipt } from '../api';

export default function FaxHistory() {
  const [faxes, setFaxes] = useState([]);
  const [filters, setFilters] = useState({ status: '', direction: '' });
  const [loading, setLoading] = useState(true);
  const [receiptModal, setReceiptModal] = useState(null);

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

  const handleViewReceipt = async (id) => {
    try {
      const receipt = await getFaxReceipt(id);
      setReceiptModal(receipt);
    } catch {
      alert('Failed to fetch receipt');
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
          <option value="sent">Sent</option>
          <option value="delivered">Delivered</option>
          <option value="failed">Failed</option>
          <option value="busy">Busy</option>
          <option value="no_answer">No Answer</option>
          <option value="received">Received</option>
        </select>
        <select value={filters.direction} onChange={(e) => setFilters({ ...filters, direction: e.target.value })}>
          <option value="">All Directions</option>
          <option value="outbound">Outbound</option>
          <option value="inbound">Inbound</option>
        </select>
        <button className="secondary" onClick={loadFaxes}>Refresh</button>
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
                <th>To</th>
                <th>From</th>
                <th>Status</th>
                <th>Quality</th>
                <th>Retries</th>
                <th>Date</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {faxes.map((fax) => (
                <tr key={fax.id}>
                  <td>
                    <div>{fax.to_name || '-'}</div>
                    <small style={{ color: 'var(--gray-500)' }}>{fax.to_number}</small>
                  </td>
                  <td>
                    <div>{fax.from_name || '-'}</div>
                    <small style={{ color: 'var(--gray-500)' }}>{fax.from_number}</small>
                  </td>
                  <td>
                    <span className={`badge ${fax.status}`}>{fax.status}</span>
                    {fax.error_message && (
                      <div style={{ fontSize: '11px', color: 'var(--danger)', marginTop: '4px', maxWidth: '200px' }}>
                        {fax.error_message.slice(0, 60)}{fax.error_message.length > 60 ? '...' : ''}
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: '13px' }}>{fax.quality || 'standard'}</td>
                  <td style={{ fontSize: '13px' }}>
                    {fax.retry_count || 0}/{fax.max_retries || 3}
                    {fax.next_retry_at && (
                      <div style={{ fontSize: '11px', color: 'var(--warning)' }}>
                        Next: {formatDate(fax.next_retry_at)}
                      </div>
                    )}
                  </td>
                  <td style={{ fontSize: '13px' }}>{formatDate(fax.created_at)}</td>
                  <td>
                    <div className="actions">
                      <button className="secondary" onClick={() => handleViewReceipt(fax.id)} style={{ fontSize: '12px', padding: '4px 10px' }}>
                        Receipt
                      </button>
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

      {receiptModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }} onClick={() => setReceiptModal(null)}>
          <div className="card" style={{ maxWidth: '600px', width: '90%', maxHeight: '80vh', overflow: 'auto' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h2 style={{ margin: 0, fontSize: '18px' }}>Transmission Receipt</h2>
              <button className="secondary" onClick={() => setReceiptModal(null)}>Close</button>
            </div>
            <pre style={{ background: 'var(--gray-100)', padding: '16px', borderRadius: '8px', fontSize: '13px', overflow: 'auto', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(receiptModal, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
