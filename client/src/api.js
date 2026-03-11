const BASE = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

// Faxes
export const getFaxes = (params = {}) => {
  const query = new URLSearchParams(params).toString();
  return request(`/faxes${query ? `?${query}` : ''}`);
};

export const getFax = (id) => request(`/faxes/${id}`);

export const sendFax = (formData) =>
  fetch(`${BASE}/faxes/send`, { method: 'POST', body: formData }).then(async (res) => {
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to send fax');
    return data;
  });

export const deleteFax = (id) => request(`/faxes/${id}`, { method: 'DELETE' });

export const getFaxReceipt = (id, format = 'json') =>
  request(`/faxes/${id}/receipt?format=${format}`);

// Contacts
export const getContacts = () => request('/contacts');
export const createContact = (contact) =>
  request('/contacts', { method: 'POST', body: JSON.stringify(contact) });
export const updateContact = (id, contact) =>
  request(`/contacts/${id}`, { method: 'PUT', body: JSON.stringify(contact) });
export const deleteContact = (id) => request(`/contacts/${id}`, { method: 'DELETE' });

// Usage tracking
export const getUsageToday = () => request('/usage/today');
export const getUsageHistory = (days = 30) => request(`/usage/history?days=${days}`);

// Audit log
export const getAuditLog = (params = {}) => {
  const query = new URLSearchParams(params).toString();
  return request(`/audit${query ? `?${query}` : ''}`);
};
