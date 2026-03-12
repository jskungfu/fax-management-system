import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
TIFF_DIR = DATA_DIR / "tiff"
DB_PATH = DATA_DIR / "fax.db"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)
TIFF_DIR.mkdir(exist_ok=True)

# Sender defaults
FROM_NAME = os.getenv("FAX_FROM_NAME", "")
FROM_NUMBER = os.getenv("FAX_FROM_NUMBER", "")
FROM_EMAIL = os.getenv("FAX_FROM_EMAIL", "")

# SMTP settings (for email-based fax - RFC 3965)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# Asterisk AMI (for SIP/T.38 fax)
AMI_HOST = os.getenv("AMI_HOST", "127.0.0.1")
AMI_PORT = int(os.getenv("AMI_PORT", "5038"))
AMI_USER = os.getenv("AMI_USER", "faxuser")
AMI_SECRET = os.getenv("AMI_SECRET", "")

# USB modem (for local modem fax)
MODEM_DEVICE = os.getenv("MODEM_DEVICE", "/dev/ttyUSB0")

# FaxZero fallback
FAXZERO_API_KEY = os.getenv("FAXZERO_API_KEY", "")

# P2P Relay Mesh Network
P2P_RELAY_ENABLED = os.getenv("P2P_RELAY_ENABLED", "false").lower() in ("true", "1", "yes")
P2P_RELAY_HOST = os.getenv("P2P_RELAY_HOST", "0.0.0.0")
P2P_RELAY_PORT = int(os.getenv("P2P_RELAY_PORT", "8765"))
P2P_AREA_CODES = [ac.strip() for ac in os.getenv("P2P_AREA_CODES", "").split(",") if ac.strip()]
P2P_COUNTRY_CODES = [cc.strip() for cc in os.getenv("P2P_COUNTRY_CODES", "1").split(",") if cc.strip()]
P2P_BOOTSTRAP_PEERS = [p.strip() for p in os.getenv("P2P_BOOTSTRAP_PEERS", "").split(",") if p.strip()]

# Flask
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
PORT = int(os.getenv("PORT", "5000"))
