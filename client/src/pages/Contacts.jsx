import { useState, useEffect } from 'react';
import { getContacts, createContact, deleteContact } from '../api';

export default function Contacts() {
  const [contacts, setContacts] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', fax_number: '', company: '', email: '' });
  const [error, setError] = useState('');

  const loadContacts = async () => {
    try {
      setContacts(await getContacts());
    } catch {
      setContacts([]);
    }
  };

  useEffect(() => { loadContacts(); }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await createContact(form);
      setForm({ name: '', fax_number: '', company: '', email: '' });
      setShowForm(false);
      loadContacts();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this contact?')) return;
    try {
      await deleteContact(id);
      setContacts(contacts.filter((c) => c.id !== id));
    } catch {
      alert('Failed to delete contact');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h1 style={{ marginBottom: 0 }}>Contacts</h1>
        <button className="primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : 'Add Contact'}
        </button>
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: '24px' }}>
          {error && <div className="alert error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div className="form-group">
                <label>Name *</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              </div>
              <div className="form-group">
                <label>Fax Number *</label>
                <input
                  value={form.fax_number}
                  onChange={(e) => setForm({ ...form, fax_number: e.target.value })}
                  placeholder="e.g. 1-555-123-4567"
                  required
                />
              </div>
              <div className="form-group">
                <label>Company</label>
                <input
                  value={form.company}
                  onChange={(e) => setForm({ ...form, company: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label>Email</label>
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>
            </div>
            <button type="submit" className="primary">Save Contact</button>
          </form>
        </div>
      )}

      <div className="card">
        {contacts.length === 0 ? (
          <div className="empty-state">No contacts yet. Add your first contact!</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Fax Number</th>
                <th>Company</th>
                <th>Email</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>{c.fax_number}</td>
                  <td>{c.company || '-'}</td>
                  <td>{c.email || '-'}</td>
                  <td>
                    <button className="danger" onClick={() => handleDelete(c.id)} style={{ fontSize: '12px', padding: '4px 10px' }}>
                      Delete
                    </button>
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
