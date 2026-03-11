# Fax Management System

Send faxes for free from your local machine using the [FaxZero API](https://faxzero.com/fax_api.php). Built with **Node.js/Express** backend and **React** frontend.

## Features

- **Send faxes for free** via FaxZero API (3 free faxes/day)
- Attach documents (PDF, DOC, TXT, images)
- Track fax history with status updates
- Manage contacts for quick fax sending
- Clean, responsive React UI
- SQLite database (no external DB setup needed)

## Prerequisites

- Node.js 18+
- A free FaxZero API key ([get one here](https://faxzero.com/fax_api.php))

## Quick Start

### 1. Install dependencies

```bash
npm run install:all
```

### 2. Configure your API key

```bash
cp .env.example .env
# Edit .env and add your FaxZero API key and sender details
```

### 3. Run in development mode

```bash
npm run dev
```

This starts:
- **Backend** on `http://localhost:3001`
- **React UI** on `http://localhost:3000` (proxies API calls to backend)

### 4. Production build

```bash
npm run build   # Build React frontend
npm start       # Start server (serves built frontend)
```

## Project Structure

```
fax-management-system/
├── server/                   # Express backend
│   ├── src/
│   │   ├── server.js         # Entry point
│   │   ├── database.js       # SQLite setup
│   │   ├── routes/
│   │   │   ├── faxes.js      # Fax CRUD + send via API
│   │   │   └── contacts.js   # Contact management
│   │   └── services/
│   │       └── faxService.js # FaxZero API integration
│   └── tests/
│       └── api.test.js       # Database & API tests
├── client/                   # React frontend (Vite)
│   ├── src/
│   │   ├── App.jsx           # Main layout + routing
│   │   ├── api.js            # API client
│   │   └── pages/
│   │       ├── SendFax.jsx   # Send fax form
│   │       ├── FaxHistory.jsx# Fax history table
│   │       └── Contacts.jsx  # Contact management
│   └── vite.config.js
├── .env.example              # Environment variables template
└── package.json              # Root scripts
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/faxes/send` | Send a new fax (multipart form) |
| `GET` | `/api/faxes` | List faxes (`?status=` `?direction=` filters) |
| `GET` | `/api/faxes/:id` | Get fax details |
| `PATCH` | `/api/faxes/:id/status` | Update fax status |
| `DELETE` | `/api/faxes/:id` | Delete a fax record |
| `GET` | `/api/contacts` | List contacts |
| `POST` | `/api/contacts` | Create contact |
| `PUT` | `/api/contacts/:id` | Update contact |
| `DELETE` | `/api/contacts/:id` | Delete contact |

## Free Tier Limits (FaxZero)

- 3 free faxes per day
- Up to 3 pages + cover page per fax
- Ad appears on cover page for free faxes
- US and Canada fax numbers supported

## Running Tests

```bash
npm test
```

## License

MIT
