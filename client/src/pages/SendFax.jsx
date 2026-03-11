import { useState, useEffect } from 'react';
import { sendFax, getContacts } from '../api';

export default function SendFax() {
  const [contacts, setContacts] = useState([]);
  const [form, setForm] = useState({
    to_number: '',
    to_name: '',
    from_number: '',
    from_name: '',
    from_email: '',
    notes: '',
  });
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getContacts().then(setContacts).catch(() => {});
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
      } else {
        setStatus({ type: 'success', message: `Fax sent successfully! Status: ${result.status}` });
        setForm({ to_number: '', to_name: '', from_number: '', from_name: '', from_email: '', notes: '' });
        setFile(null);
      }
    } catch (err) {
      setStatus({ type: 'error', message: err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h1>Send a Fax</h1>

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
                placeholder="e.g. 1-555-123-4567"
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
              placeholder="you@example.com"
              value={form.from_email}
              onChange={handleChange}
            />
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

          <button type="submit" className="primary" disabled={loading} style={{ width: '100%', padding: '12px' }}>
            {loading ? 'Sending...' : 'Send Fax'}
          </button>
        </form>
      </div>

      <div style={{ marginTop: '24px', padding: '16px', background: 'var(--gray-100)', borderRadius: 'var(--radius)', fontSize: '13px', color: 'var(--gray-500)' }}>
        <strong>Free Tier Info (FaxZero):</strong> Up to 3 free faxes per day, max 3 pages + cover page.
        An ad will appear on the cover page for free faxes.
        Get your API key at <a href="https://faxzero.com/fax_api.php" target="_blank" rel="noreferrer">faxzero.com/fax_api.php</a>.
      </div>
    </div>
  );
}
