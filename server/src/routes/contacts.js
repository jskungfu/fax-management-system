const express = require('express');
const { v4: uuidv4 } = require('uuid');

function createRouter(db) {
  const router = express.Router();

  // List contacts
  router.get('/', (_req, res) => {
    res.json(db.prepare('SELECT * FROM contacts ORDER BY name ASC').all());
  });

  // Get single contact
  router.get('/:id', (req, res) => {
    const contact = db.prepare('SELECT * FROM contacts WHERE id = ?').get(req.params.id);
    if (!contact) return res.status(404).json({ error: 'Contact not found' });
    res.json(contact);
  });

  // Create contact
  router.post('/', (req, res) => {
    const { name, fax_number, company, email } = req.body;
    if (!name || !fax_number) {
      return res.status(400).json({ error: 'name and fax_number are required' });
    }

    const id = uuidv4();
    db.prepare('INSERT INTO contacts (id, name, fax_number, company, email) VALUES (?, ?, ?, ?, ?)')
      .run(id, name, fax_number, company || null, email || null);

    res.status(201).json(db.prepare('SELECT * FROM contacts WHERE id = ?').get(id));
  });

  // Update contact
  router.put('/:id', (req, res) => {
    const { name, fax_number, company, email } = req.body;
    if (!name || !fax_number) {
      return res.status(400).json({ error: 'name and fax_number are required' });
    }

    const result = db.prepare(
      'UPDATE contacts SET name = ?, fax_number = ?, company = ?, email = ? WHERE id = ?'
    ).run(name, fax_number, company || null, email || null, req.params.id);

    if (result.changes === 0) return res.status(404).json({ error: 'Contact not found' });
    res.json(db.prepare('SELECT * FROM contacts WHERE id = ?').get(req.params.id));
  });

  // Delete contact
  router.delete('/:id', (req, res) => {
    const result = db.prepare('DELETE FROM contacts WHERE id = ?').run(req.params.id);
    if (result.changes === 0) return res.status(404).json({ error: 'Contact not found' });
    res.json({ message: 'Contact deleted' });
  });

  return router;
}

module.exports = createRouter;
