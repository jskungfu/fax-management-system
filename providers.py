"""
Fax delivery providers — pluggable backends for sending faxes.

FREE local methods (no external API):
  1. SIPFaxProvider   — T.38 fax over SIP via local Asterisk (apt install asterisk)
  2. EmailFaxProvider — RFC 3965 Internet Fax via your own SMTP (Gmail etc.)
  3. ModemFaxProvider — USB fax modem via efax command (apt install efax)

External fallback:
  4. FaxZeroProvider  — 5 free faxes/day via FaxZero API
"""

import os
import json
import shutil
import socket
import subprocess
import smtplib
import base64
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from datetime import date

import database as db
import config


class FaxProvider(ABC):
    """Base class for all fax providers."""

    name: str = "base"
    daily_limit: int = 0  # 0 = unlimited
    requires_config: list = []

    @abstractmethod
    def send(self, tiff_path: str, to_number: str, from_number: str = "",
             from_name: str = "", from_email: str = "", cover_message: str = "") -> dict:
        """Send a fax. Returns {"success": bool, "provider_fax_id": str, "message": str}."""
        pass

    def is_available(self) -> bool:
        """Check if this provider is configured and usable."""
        return True

    def remaining_today(self) -> int:
        """How many faxes can still be sent today."""
        if self.daily_limit == 0:
            return 999
        used = db.get_usage_today(self.name)
        return max(0, self.daily_limit - used)

    def record_send(self):
        db.increment_usage(self.name)


# ══════════════════════════════════════════════════════════════════════════════
# 1. SIP/T.38 FAX — Direct internet fax via local Asterisk
# ══════════════════════════════════════════════════════════════════════════════

class SIPFaxProvider(FaxProvider):
    """
    Send fax over SIP using T.38 protocol via local Asterisk PBX.

    How it works:
    - Asterisk runs locally (apt install asterisk)
    - We submit fax jobs via Asterisk Manager Interface (AMI)
    - Asterisk sends T.38 fax over IP directly to recipient
    - For PSTN recipients: add a SIP trunk (e.g., VoIP.ms) to Asterisk
    - For SIP recipients: fax goes directly over internet (FREE)

    Setup:
      sudo apt install asterisk
      # Configure /etc/asterisk/manager.conf with AMI user
      # Configure SIP trunk in /etc/asterisk/sip.conf or pjsip.conf
    """

    name = "sip_t38"
    daily_limit = 0  # unlimited
    requires_config = ["AMI_SECRET"]

    def is_available(self) -> bool:
        if not config.AMI_SECRET:
            return False
        # Check if Asterisk is running
        return shutil.which("asterisk") is not None

    def send(self, tiff_path: str, to_number: str, **kwargs) -> dict:
        try:
            # Connect to Asterisk Manager Interface
            response = self._ami_originate_fax(tiff_path, to_number)
            self.record_send()
            return {"success": True, "provider_fax_id": response, "message": "Fax queued via Asterisk SIP/T.38"}
        except Exception as e:
            return {"success": False, "provider_fax_id": "", "message": str(e)}

    def _ami_originate_fax(self, tiff_path: str, to_number: str) -> str:
        """Send fax via Asterisk AMI (Manager Interface)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((config.AMI_HOST, config.AMI_PORT))

        # Read banner
        s.recv(1024)

        # Login
        action_id = f"fax-{to_number}-{date.today().isoformat()}"
        self._ami_send(s, {
            "Action": "Login",
            "Username": config.AMI_USER,
            "Secret": config.AMI_SECRET,
        })
        resp = self._ami_recv(s)
        if "Success" not in resp:
            s.close()
            raise ConnectionError(f"AMI login failed: {resp}")

        # Originate call with SendFAX application
        self._ami_send(s, {
            "Action": "Originate",
            "Channel": f"SIP/{to_number}@default",
            "Application": "SendFAX",
            "Data": f"{tiff_path},d",
            "ActionID": action_id,
            "CallerID": config.FROM_NUMBER or to_number,
            "Timeout": "60000",
        })
        resp = self._ami_recv(s)

        # Logoff
        self._ami_send(s, {"Action": "Logoff"})
        s.close()

        if "Success" not in resp and "Follows" not in resp:
            raise RuntimeError(f"AMI originate failed: {resp}")

        return action_id

    @staticmethod
    def _ami_send(sock, fields: dict):
        msg = "".join(f"{k}: {v}\r\n" for k, v in fields.items()) + "\r\n"
        sock.sendall(msg.encode())

    @staticmethod
    def _ami_recv(sock) -> str:
        data = b""
        while True:
            chunk = sock.recv(4096)
            data += chunk
            if b"\r\n\r\n" in data:
                break
        return data.decode(errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# 2. EMAIL FAX — RFC 3965 Internet Fax via SMTP
# ══════════════════════════════════════════════════════════════════════════════

class EmailFaxProvider(FaxProvider):
    """
    Send fax as TIFF-F attachment via email (RFC 3965 Internet Fax).

    How it works:
    - Converts document to standard TIFF-F format (fax standard)
    - Sends via YOUR own email (Gmail, Outlook, any SMTP)
    - Recipient receives the fax document via email
    - Works great when recipient has email-based fax (eFax, RingCentral, etc.)

    Use cases:
    - Recipient has an eFax email address
    - Recipient accepts documents via email
    - You know recipient's email-to-fax gateway address
    - Sending to SIP URI (some accept email)

    This is the RFC 3965 standard for "Internet Fax" — legitimate fax over email.
    """

    name = "email_fax"
    daily_limit = 0  # limited only by your email provider
    requires_config = ["SMTP_USER", "SMTP_PASS"]

    def is_available(self) -> bool:
        return bool(config.SMTP_USER and config.SMTP_PASS)

    def send(self, tiff_path: str, to_number: str, from_name: str = "",
             from_email: str = "", cover_message: str = "", **kwargs) -> dict:
        # to_number can be an email address for email fax
        recipient_email = to_number if "@" in to_number else ""
        if not recipient_email:
            return {
                "success": False,
                "provider_fax_id": "",
                "message": "Email fax requires recipient email or email-to-fax gateway address. "
                           "Format: number@efax-provider.com or recipient@email.com"
            }

        try:
            msg = MIMEMultipart()
            msg["From"] = from_email or config.SMTP_USER
            msg["To"] = recipient_email
            msg["Subject"] = f"Fax from {from_name or config.FROM_NAME}"

            # Body text
            body = cover_message or "Please find attached fax document."
            msg.attach(MIMEText(body, "plain"))

            # Attach TIFF-F (standard fax format per RFC 3965)
            with open(tiff_path, "rb") as f:
                part = MIMEBase("image", "tiff")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition",
                                f'attachment; filename="{Path(tiff_path).name}"')
                part.add_header("Content-Description", "Internet Fax")
                msg.attach(part)

            # Send via SMTP
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as smtp:
                smtp.starttls()
                smtp.login(config.SMTP_USER, config.SMTP_PASS)
                smtp.send_message(msg)

            self.record_send()
            return {
                "success": True,
                "provider_fax_id": f"email-{recipient_email}",
                "message": f"Fax sent via email to {recipient_email}"
            }

        except Exception as e:
            return {"success": False, "provider_fax_id": "", "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# 3. USB MODEM FAX — Local fax modem via efax
# ══════════════════════════════════════════════════════════════════════════════

class ModemFaxProvider(FaxProvider):
    """
    Send fax using a USB fax modem via the `efax` command.

    How it works:
    - Plug in a USB fax modem (~$10, e.g. USRobotics USR5637)
    - Connect to any phone line (or VoIP ATA like Ooma)
    - efax handles the T.30 protocol over the modem
    - Unlimited faxes, zero recurring cost

    Setup:
      sudo apt install efax
      # Plug in USB modem, it appears as /dev/ttyUSB0
    """

    name = "usb_modem"
    daily_limit = 0  # unlimited
    requires_config = ["MODEM_DEVICE"]

    def is_available(self) -> bool:
        if not shutil.which("efax"):
            return False
        return os.path.exists(config.MODEM_DEVICE)

    def send(self, tiff_path: str, to_number: str, **kwargs) -> dict:
        try:
            # efax expects the number without + prefix
            number = to_number.lstrip("+").replace("-", "").replace(" ", "")

            result = subprocess.run(
                ["efax", "-d", config.MODEM_DEVICE, "-t", number, tiff_path],
                capture_output=True, text=True, timeout=300
            )

            if result.returncode == 0:
                self.record_send()
                return {
                    "success": True,
                    "provider_fax_id": f"modem-{number}",
                    "message": "Fax sent via USB modem"
                }
            else:
                return {
                    "success": False,
                    "provider_fax_id": "",
                    "message": f"Modem error: {result.stderr or result.stdout}"
                }

        except FileNotFoundError:
            return {"success": False, "provider_fax_id": "",
                    "message": "efax not installed. Run: sudo apt install efax"}
        except subprocess.TimeoutExpired:
            return {"success": False, "provider_fax_id": "",
                    "message": "Fax transmission timed out (5 min)"}
        except Exception as e:
            return {"success": False, "provider_fax_id": "", "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# 4. FAXZERO — Free API fallback (5/day)
# ══════════════════════════════════════════════════════════════════════════════

class FaxZeroProvider(FaxProvider):
    """
    FaxZero API — 5 free faxes per day (with branding on cover page).
    Get free API key at faxzero.com. This is the PSTN fallback
    for when local methods can't reach the recipient.
    """

    name = "faxzero"
    daily_limit = 5
    requires_config = ["FAXZERO_API_KEY"]

    def is_available(self) -> bool:
        return bool(config.FAXZERO_API_KEY)

    def send(self, tiff_path: str, to_number: str, from_number: str = "",
             from_name: str = "", from_email: str = "", cover_message: str = "",
             **kwargs) -> dict:
        try:
            import urllib.request
            import urllib.parse

            with open(tiff_path, "rb") as f:
                file_data = base64.b64encode(f.read()).decode()

            payload = json.dumps({
                "api_key": config.FAXZERO_API_KEY,
                "fax_number": to_number,
                "fax_src": from_number or config.FROM_NUMBER,
                "fax_src_name": from_name or config.FROM_NAME,
                "header": f"To: {to_number}",
                "send_email": from_email or config.FROM_EMAIL,
                "file_name": Path(tiff_path).name,
                "file_content": file_data,
            }).encode()

            req = urllib.request.Request(
                "https://api.faxzero.com/fax/send",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())

            if result.get("success"):
                self.record_send()
                return {
                    "success": True,
                    "provider_fax_id": str(result.get("fax_id", "")),
                    "message": "Fax queued via FaxZero"
                }
            else:
                return {
                    "success": False,
                    "provider_fax_id": "",
                    "message": result.get("message", "FaxZero API error")
                }

        except Exception as e:
            return {"success": False, "provider_fax_id": "", "message": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Provider Registry
# ══════════════════════════════════════════════════════════════════════════════

ALL_PROVIDERS = [
    SIPFaxProvider(),
    EmailFaxProvider(),
    ModemFaxProvider(),
    FaxZeroProvider(),
]


def get_available_providers() -> list:
    """Return list of providers that are configured and usable."""
    return [p for p in ALL_PROVIDERS if p.is_available()]


def get_provider(name: str) -> FaxProvider | None:
    """Get a specific provider by name."""
    for p in ALL_PROVIDERS:
        if p.name == name:
            return p
    return None


def best_provider(to_address: str = "") -> FaxProvider | None:
    """Auto-select the best available provider.

    Priority:
    1. SIP/T.38 (if Asterisk is running)
    2. Email (if recipient has email and SMTP is configured)
    3. USB Modem (if modem connected)
    4. FaxZero (fallback, if API key set and daily limit not hit)
    """
    available = get_available_providers()

    for p in available:
        if p.name == "sip_t38":
            return p

    if "@" in to_address:
        for p in available:
            if p.name == "email_fax":
                return p

    for p in available:
        if p.name == "usb_modem":
            return p

    for p in available:
        if p.name == "faxzero" and p.remaining_today() > 0:
            return p

    return None
