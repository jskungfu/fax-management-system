import { useState, useEffect } from 'react';
import { sendFax, getContacts, getUsageToday } from '../api';

export default function SendFax() {
  const [contacts, setContacts] = useState([]);
  const [usage, setUsage] = useState(null);
  const [form, setForm] = useState({
    to_number: '',
    to_name: '',
    from_number: '',
    from_name: '',
    from_email: '',
    notes: '',
    quality: 'standard',
    page_count: '',
  });
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getContacts().then(setContacts).catch(() => {});
    getUsageToday().then(setUsage).catch(() => {});
  }, []);

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleContactSelect = (e) => {
    const contact = contacts.find((c) => c.id === e.target.value);
    if (contact) {
      setForm({ ...form, to_number: contact.fax_number, to_name: contact.name });
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setStatus(null);

    const formData = new FormData();
    Object.entries(form).forEach(([key, val]) => {
      if (val) formData.append(key, val);
    });
    if (file) formData.append('document', file);

    try {
      const result = await sendFax(formData);
      if (result.status === 'failed') {
        setStatus({ type: 'error', message: `Fax failed: ${result.error_message || 'Unknown error'}` });
      } else if (result.status === 'busy' || result.status === 'no_answer') {
        setStatus({ type: 'success', message: `Fax queued for retry. Current status: ${result.status}. Will retry automatically.` });
      } else {
        setStatus({ type: 'success', message: `Fax sent successfully! Status: ${result.status}` });
        setForm({ to_number: '', to_name: '', from_number: '', from_name: '', from_email: '', notes: '', quality: 'standard', page_count: '' });
        setFile(null);
      }
      // Refresh usage
      getUsageToday().then(setUsage).catch(() => {});
    } catch (err) {
      setStatus({ type: 'error', message: err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1>Send a Fax</h1>

      {usage && (
        <div style={{ marginBottom: '16px', padding: '12px 16px', background: usage.canSend ? '#dcfce7' : '#fee2e2', borderRadius: 'var(--radius)', fontSize: '14px' }}>
          <strong>Daily Usage:</strong> {usage.faxesSent} / {usage.dailyLimit} faxes sent today
          {usage.canSend
            ? ` (${usage.remaining} remaining)`
            : ' — Limit reached. Try again tomorrow.'}
        </div>
      )}

      {status && <div className={`alert ${status.type}`}>{status.message}</div>}

      <div className="card">
        <form onSubmit={handleSubmit}>
          {contacts.length > 0 && (
            <div className="form-group">
              <label>Quick Select Contact</label>
              <select onChange={handleContactSelect} defaultValue="">
                <option value="" disabled>Choose a contact...</option>
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} - {c.fax_number}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div className="form-group">
              <label htmlFor="to_number">Recipient Fax Number *</label>
              <input
                id="to_number"
                name="to_number"
                placeholder="e.g. 15551234567"
                value={form.to_number}
                onChange={handleChange}
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="to_name">Recipient Name</label>
              <input
                id="to_name"
                name="to_name"
                placeholder="John Doe"
                value={form.to_name}
                onChange={handleChange}
              />
            </div>
            <div className="form-group">
              <label htmlFor="from_number">Your Fax/Phone Number</label>
              <input
                id="from_number"
                name="from_number"
                placeholder="Your phone number"
                value={form.from_number}
                onChange={handleChange}
              />
            </div>
            <div className="form-group">
              <label htmlFor="from_name">Your Name</label>
              <input
                id="from_name"
                name="from_name"
                placeholder="Your name"
                value={form.from_name}
                onChange={handleChange}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="from_email">Your Email</label>
            <input
              id="from_email"
              name="from_email"
              type="email"
              placeholder="you@example.com (for delivery notifications)"
              value={form.from_email}
              onChange={handleChange}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div className="form-group">
              <label htmlFor="quality">Fax Quality</label>
              <select id="quality" name="quality" value={form.quality} onChange={handleChange}>
                <option value="standard">Standard (204x98 DPI) - Fastest</option>
                <option value="fine">Fine (204x196 DPI) - Better text</option>
                <option value="superfine">Super-Fine (204x391 DPI) - Highest detail</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="page_count">Page Count</label>
              <input
                id="page_count"
                name="page_count"
                type="number"
                min="0"
                max="3"
                placeholder="Number of pages (max 3)"
                value={form.page_count}
                onChange={handleChange}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="document">Attach Document</label>
            <input
              id="document"
              type="file"
              accept=".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.tif,.tiff"
              onChange={(e) => setFile(e.target.files[0] || null)}
            />
            <small style={{ color: 'var(--gray-500)' }}>
              PDF, DOC, TXT, PNG, JPG, TIFF - Max 10MB, up to 3 pages (free tier)
            </small>
          </div>

          <div className="form-group">
            <label htmlFor="notes">Cover Page Message</label>
            <textarea
              id="notes"
              name="notes"
              rows={3}
              placeholder="Optional message for the cover page"
              value={form.notes}
              onChange={handleChange}
            />
          </div>

          <button
            type="submit"
            className="primary"
            disabled={loading || (usage && !usage.canSend)}
            style={{ width: '100%', padding: '12px' }}
          >
            {loading ? 'Sending...' : 'Send Fax'}
          </button>
        </form>
      </div>

      <div style={{ marginTop: '24px', padding: '16px', background: 'var(--gray-100)', borderRadius: 'var(--radius)', fontSize: '13px', color: 'var(--gray-500)' }}>
        <strong>Free Tier Info (FaxZero):</strong> Up to 3 free faxes per day, max 3 pages + cover page.
        An ad will appear on the cover page for free faxes. Supports T.38 protocol for Fax-over-IP quality.
        Get your API key at <a href="https://faxzero.com/fax_api.php" target="_blank" rel="noreferrer">faxzero.com/fax_api.php</a>.
      </div>
    </div>
  );
}
