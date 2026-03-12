# Fax Management System

Send faxes for free from your local machine using the [FaxZero API](https://faxzero.com/fax_api.php). Built with **Node.js/Express** backend and **React** frontend. Designed with **HIPAA compliance** in mind.

## Features

- **Send faxes for free** via FaxZero API (3 free faxes/day)
- **HIPAA-compliant security** - secure headers, input sanitization, rate limiting, audit logging
- **Document upload** - PDF, DOC, DOCX, TXT, PNG, JPG, TIFF (up to 10MB)
- **Quality settings** - Standard, Fine (204x196 DPI), and Super-Fine (204x391 DPI) modes
- **T.38 protocol support** for Fax-over-IP quality
- **Webhook listener** for real-time delivery status (Success, Failed, Busy, No Answer)
- **Smart retry mechanism** - auto-retries on Busy/Network Error, skips Invalid Number
- **Transmission receipts** - detailed confirmation reports for delivered faxes
- **Free tier tracking** - SQLite counter to monitor daily usage against limits
- **Audit log** - HIPAA-compliant activity tracking for all operations
- **Contact management** for quick fax sending
- **Responsive React UI** with dashboard, send form, history, contacts, and audit pages
- **SQLite database** - no external DB setup needed

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

**Environment variables:**

| Variable | Description | Required |
|----------|-------------|----------|
| `FAXZERO_API_KEY` | Your FaxZero API key | Yes |
| `DEFAULT_FROM_NAME` | Default sender name | No |
| `DEFAULT_FROM_FAX` | Default sender fax/phone number | No |
| `DEFAULT_FROM_EMAIL` | Default sender email (for notifications) | No |
| `PORT` | Server port (default: 3001) | No |
| `CORS_ORIGIN` | Allowed CORS origin (default: http://localhost:3000) | No |
| `DAILY_FAX_LIMIT` | Daily free tier limit (default: 3) | No |

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
├── server/
│   ├── src/
│   │   ├── server.js              # Entry point
│   │   ├── database.js            # SQLite schema (faxes, contacts, audit, usage, webhooks)
│   │   ├── middleware/
│   │   │   └── security.js        # HIPAA: secure headers, rate limit, sanitization, audit
│   │   ├── routes/
│   │   │   ├── faxes.js           # Send/list/delete faxes, receipts
│   │   │   ├── contacts.js        # CRUD contacts
│   │   │   ├── webhooks.js        # Webhook listener for delivery status
│   │   │   ├── usage.js           # Free tier usage tracking
│   │   │   └── audit.js           # HIPAA audit log viewer
│   │   └── services/
│   │       ├── faxService.js      # FaxZero API integration + T.38 + quality
│   │       ├── retryService.js    # Smart retry with exponential backoff
│   │       ├── usageTracker.js    # Daily fax limit counter
│   │       └── receiptService.js  # Transmission receipt generator
│   └── tests/
│       └── api.test.js            # Comprehensive test suite
├── client/                        # React frontend (Vite)
│   ├── src/
│   │   ├── App.jsx                # Layout + routing
│   │   ├── api.js                 # API client
│   │   └── pages/
│   │       ├── Dashboard.jsx      # Usage stats, recent faxes
│   │       ├── SendFax.jsx        # Send fax form with quality settings
│   │       ├── FaxHistory.jsx     # History table + receipt viewer
│   │       ├── Contacts.jsx       # Contact management
│   │       └── AuditLog.jsx       # HIPAA audit trail
│   └── vite.config.js
├── .env.example
└── package.json
```

## API Endpoints

### Faxes
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/faxes/send` | Send a fax (multipart form with document) |
| `GET` | `/api/faxes` | List faxes (`?status=` `?direction=` filters) |
| `GET` | `/api/faxes/:id` | Get fax details |
| `GET` | `/api/faxes/:id/receipt` | Get transmission receipt (`?format=text` or `json`) |
| `PATCH` | `/api/faxes/:id/status` | Update fax status |
| `DELETE` | `/api/faxes/:id` | Delete a fax record |

### Contacts
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/contacts` | List contacts |
| `POST` | `/api/contacts` | Create contact |
| `PUT` | `/api/contacts/:id` | Update contact |
| `DELETE` | `/api/contacts/:id` | Delete contact |

### Webhooks
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/webhooks/status` | Receive delivery status callbacks |
| `GET` | `/api/webhooks/events` | List webhook events (debug) |

### Usage & Audit
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/usage/today` | Today's free tier usage |
| `GET` | `/api/usage/history` | Usage history |
| `GET` | `/api/audit` | HIPAA audit log |

## Security (HIPAA Compliance)

- **Secure HTTP headers** - HSTS, X-Content-Type-Options, X-Frame-Options, etc.
- **Input sanitization** - HTML tag stripping, length limits on all inputs
- **Rate limiting** - 60 requests/minute per IP
- **Fax number validation** - E.164 format enforcement
- **Audit logging** - Every API action logged with IP, user-agent, timestamp
- **No-cache headers** - Prevents sensitive data caching
- **Graceful shutdown** - Clean database/connection closure

## Fax Quality & Status

**Quality Modes:**
| Mode | Resolution | Use Case |
|------|-----------|----------|
| Standard | 204x98 DPI | Fast, general documents |
| Fine | 204x196 DPI | Better text clarity |
| Super-Fine | 204x391 DPI | Highest detail for images |

**Status Flow:**
- `queued` → `sending` → `sent` → `delivered` (success path)
- `queued` → `sending` → `busy`/`no_answer` → auto-retry (up to 3 times)
- `queued` → `sending` → `failed` (invalid number or max retries reached)

**Retry Logic:**
- Retries on: `busy`, `no_answer`, `network_error`
- Does NOT retry: `invalid_number`, `limit_exceeded`
- Backoff: 2min → 5min → 15min

## Free Tier Limits (FaxZero)

- 3 free faxes per day (tracked in SQLite)
- Up to 3 pages + cover page per fax
- Ad appears on cover page for free faxes
- US and Canada fax numbers supported

## Running Tests

```bash
npm test
```

## License

MIT
