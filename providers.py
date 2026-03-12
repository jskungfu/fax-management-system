"""
Fax delivery providers — pluggable backends for sending faxes.

FREE local methods (no external API, no phone line, no hardware):
  0. ENUMFaxProvider  — DNS-based route discovery (RFC 6116) + direct SIP/T.38
  1. VirtualModemFaxProvider — Software modem via t38modem (no hardware needed)
  2. SIPFaxProvider   — T.38 fax over SIP via local Asterisk
  3. EmailFaxProvider — RFC 3965 Internet Fax via your own SMTP (Gmail etc.)
  4. ModemFaxProvider — USB fax modem via efax command

P2P mesh relay:
  5. P2PRelayProvider — Decentralized mesh network relay (Kademlia DHT + mDNS)

External fallback:
  6. FaxZeroProvider  — 5 free faxes/day via FaxZero API
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

import re
import struct

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
# 0. ENUM — DNS-based phone number → SIP URI discovery (RFC 6116)
# ══════════════════════════════════════════════════════════════════════════════

class ENUMFaxProvider(FaxProvider):
    """
    ENUM (RFC 6116): Use DNS to discover if a phone number has a SIP endpoint.

    How it works:
    1. Take phone number +1-609-409-5610
    2. Reverse digits, query DNS: 0.1.6.5.9.0.4.9.0.6.1.e164.arpa
    3. If NAPTR record exists → get SIP URI (e.g., sip:+16094095610@gateway.com)
    4. Send T.38 fax directly to that SIP URI over the internet

    This is completely FREE:
    - DNS query = free
    - SIP call over internet = free
    - No PSTN, no phone line, no API, no hardware

    Many VoIP/cloud fax recipients are already on IP — ENUM discovers this
    automatically. The fax never touches PSTN.

    Multiple ENUM roots are queried:
    - e164.arpa       (official ITU root)
    - e164.org        (community/public root)
    - e164.freedns.xxx (alternative roots, if configured)
    """

    name = "enum_sip"
    daily_limit = 0  # unlimited — it's just DNS + SIP
    requires_config = []

    # ENUM DNS roots to query (most to least authoritative)
    ENUM_ROOTS = [
        "e164.arpa",
        "e164.org",
    ]

    def is_available(self) -> bool:
        # ENUM is always available — it just does DNS lookups
        # But we need Asterisk or t38modem to actually send the T.38 fax
        return (shutil.which("asterisk") is not None or
                shutil.which("t38modem") is not None or
                os.path.exists("/dev/t38modem0"))

    def send(self, tiff_path: str, to_number: str, **kwargs) -> dict:
        # Step 1: Resolve phone number to SIP URI via ENUM
        digits = re.sub(r"[^\d]", "", to_number)
        if not digits:
            return {"success": False, "provider_fax_id": "",
                    "message": "Invalid phone number"}

        sip_uri = self._enum_lookup(digits)
        if not sip_uri:
            return {"success": False, "provider_fax_id": "",
                    "message": f"ENUM: No SIP endpoint found for {to_number}. "
                               "Number is likely on PSTN only (not reachable via internet)."}

        # Step 2: Send T.38 fax to discovered SIP URI
        try:
            if shutil.which("asterisk") and config.AMI_SECRET:
                result = self._send_via_asterisk(tiff_path, sip_uri)
            else:
                result = self._send_via_t38modem(tiff_path, sip_uri)

            if result:
                self.record_send()
                return {"success": True, "provider_fax_id": f"enum-{sip_uri}",
                        "message": f"Fax sent via ENUM→SIP to {sip_uri} (FREE, no PSTN!)"}
            else:
                return {"success": False, "provider_fax_id": "",
                        "message": f"ENUM resolved to {sip_uri} but T.38 delivery failed"}
        except Exception as e:
            return {"success": False, "provider_fax_id": "", "message": str(e)}

    def _enum_lookup(self, digits: str) -> str | None:
        """
        ENUM lookup: convert phone number to DNS NAPTR query.

        +16094095610 → 0.1.6.5.9.0.4.9.0.6.1.e164.arpa
        Query for NAPTR records, extract SIP URI.
        """
        # Build ENUM domain: reverse digits, dot-separated
        reversed_digits = ".".join(reversed(digits))

        for root in self.ENUM_ROOTS:
            domain = f"{reversed_digits}.{root}"
            try:
                # Use dig for NAPTR lookup (available on most Linux systems)
                result = subprocess.run(
                    ["dig", "+short", "NAPTR", domain],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    uri = self._parse_naptr(result.stdout)
                    if uri:
                        return uri
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # dig not available, try Python DNS resolution
                uri = self._enum_lookup_python(domain)
                if uri:
                    return uri

        return None

    def _enum_lookup_python(self, domain: str) -> str | None:
        """Pure Python ENUM lookup using raw DNS query over UDP."""
        try:
            # Build DNS query for NAPTR record (type 35)
            query = self._build_dns_query(domain, qtype=35)

            # Send to system resolver
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)

            # Read resolv.conf for nameserver
            nameserver = "8.8.8.8"
            try:
                with open("/etc/resolv.conf") as f:
                    for line in f:
                        if line.strip().startswith("nameserver"):
                            nameserver = line.split()[1]
                            break
            except (FileNotFoundError, IndexError):
                pass

            sock.sendto(query, (nameserver, 53))
            data, _ = sock.recvfrom(4096)
            sock.close()

            return self._parse_dns_naptr_response(data)

        except Exception:
            return None

    @staticmethod
    def _build_dns_query(domain: str, qtype: int = 35) -> bytes:
        """Build a raw DNS query packet for NAPTR (type 35) records."""
        import random
        txn_id = random.randint(0, 65535)
        # Header: ID, flags (standard query), QDCOUNT=1
        header = struct.pack("!HHHHHH", txn_id, 0x0100, 1, 0, 0, 0)

        # Question section
        question = b""
        for label in domain.split("."):
            question += bytes([len(label)]) + label.encode()
        question += b"\x00"  # root label
        question += struct.pack("!HH", qtype, 1)  # NAPTR, IN class

        return header + question

    @staticmethod
    def _parse_naptr(dig_output: str) -> str | None:
        """Parse dig NAPTR output for SIP URIs."""
        for line in dig_output.strip().split("\n"):
            line = line.strip()
            # NAPTR records contain regex replacement patterns for E2U+sip
            if "E2U+sip" in line.lower() or "sip:" in line.lower():
                # Extract SIP URI from the regex or replacement field
                sip_match = re.search(r'sip:[^\s"]+', line, re.IGNORECASE)
                if sip_match:
                    return sip_match.group(0)
                # Try to extract from NAPTR regex field like !^.*$!sip:+1234@gw.com!
                regex_match = re.search(r'!(.*?)!(.*?)!', line)
                if regex_match:
                    replacement = regex_match.group(2)
                    if "sip:" in replacement.lower():
                        return replacement
        return None

    @staticmethod
    def _parse_dns_naptr_response(data: bytes) -> str | None:
        """Parse raw DNS response for NAPTR records containing SIP URIs."""
        try:
            text = data.decode("ascii", errors="replace")
            sip_match = re.search(r'sip:[^\s\x00]+', text, re.IGNORECASE)
            if sip_match:
                return sip_match.group(0)
        except Exception:
            pass
        return None

    def _send_via_asterisk(self, tiff_path: str, sip_uri: str) -> bool:
        """Send T.38 fax to SIP URI via Asterisk AMI."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((config.AMI_HOST, config.AMI_PORT))
        s.recv(1024)  # banner

        # Login
        msg = f"Action: Login\r\nUsername: {config.AMI_USER}\r\nSecret: {config.AMI_SECRET}\r\n\r\n"
        s.sendall(msg.encode())
        if "Success" not in s.recv(4096).decode(errors="replace"):
            s.close()
            return False

        # Originate call to SIP URI with SendFAX
        msg = (f"Action: Originate\r\nChannel: SIP/{sip_uri}\r\n"
               f"Application: SendFAX\r\nData: {tiff_path},d\r\n"
               f"Timeout: 60000\r\n\r\n")
        s.sendall(msg.encode())
        resp = s.recv(4096).decode(errors="replace")

        s.sendall(b"Action: Logoff\r\n\r\n")
        s.close()
        return "Success" in resp or "Follows" in resp

    @staticmethod
    def _send_via_t38modem(tiff_path: str, sip_uri: str) -> bool:
        """Send T.38 fax via t38modem virtual modem device."""
        modem_dev = "/dev/t38modem0"
        if not os.path.exists(modem_dev):
            return False
        try:
            result = subprocess.run(
                ["efax", "-d", modem_dev, "-t", sip_uri, tiff_path],
                capture_output=True, text=True, timeout=300
            )
            return result.returncode == 0
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════════════
# 0b. VIRTUAL MODEM — Software fax modem via t38modem (no hardware)
# ══════════════════════════════════════════════════════════════════════════════

class VirtualModemFaxProvider(FaxProvider):
    """
    t38modem: creates a virtual fax modem in software. No USB modem needed.

    How it works:
    - t38modem creates a pseudo-TTY device (e.g., /dev/t38modem0)
    - This device behaves exactly like a hardware fax modem
    - efax/HylaFAX talks to it as if it were real hardware
    - t38modem converts modem commands to SIP/T.38 packets
    - Packets go over the internet to the recipient

    Architecture:
      Document → TIFF → efax → /dev/t38modem0 → SIP/T.38 → Internet → Recipient

    No phone line. No hardware. No API. Pure software.

    Setup:
      # Install from OPAL project
      sudo apt install opal-utils t38modem
      # Or build from source: https://github.com/T38Modem/t38modem
      # Start: t38modem --ptty /dev/t38modem0 --sip-listen udp:5060
    """

    name = "virtual_modem"
    daily_limit = 0  # unlimited
    requires_config = []

    def is_available(self) -> bool:
        # Check if t38modem is running (creates /dev/t38modem0)
        if os.path.exists("/dev/t38modem0"):
            return True
        # Check if t38modem binary exists
        return shutil.which("t38modem") is not None

    def send(self, tiff_path: str, to_number: str, **kwargs) -> dict:
        modem_dev = "/dev/t38modem0"

        # Auto-start t38modem if binary exists but device doesn't
        if not os.path.exists(modem_dev) and shutil.which("t38modem"):
            try:
                subprocess.Popen(
                    ["t38modem", "--ptty", modem_dev, "--sip-listen", "udp$*:5060"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                import time
                time.sleep(2)  # wait for device to appear
            except Exception as e:
                return {"success": False, "provider_fax_id": "",
                        "message": f"Failed to start t38modem: {e}"}

        if not os.path.exists(modem_dev):
            return {"success": False, "provider_fax_id": "",
                    "message": "Virtual modem device not found. Install: sudo apt install t38modem"}

        try:
            number = re.sub(r"[^\d+]", "", to_number)
            result = subprocess.run(
                ["efax", "-d", modem_dev, "-t", number, tiff_path],
                capture_output=True, text=True, timeout=300
            )

            if result.returncode == 0:
                self.record_send()
                return {
                    "success": True,
                    "provider_fax_id": f"vmodem-{number}",
                    "message": "Fax sent via virtual modem (t38modem → SIP/T.38, no hardware!)"
                }
            else:
                return {
                    "success": False,
                    "provider_fax_id": "",
                    "message": f"Virtual modem error: {result.stderr or result.stdout}"
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "provider_fax_id": "",
                    "message": "Fax transmission timed out (5 min)"}
        except Exception as e:
            return {"success": False, "provider_fax_id": "", "message": str(e)}


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
# 4. P2P RELAY — Decentralized mesh network fax delivery
# ══════════════════════════════════════════════════════════════════════════════

class P2PRelayProvider(FaxProvider):
    """
    Peer-to-Peer Fax Relay Mesh Network.

    How it works:
    - Your node joins a decentralized mesh of other fax nodes
    - Nodes announce which phone numbers they can deliver to (via modem, SIP, etc.)
    - When you send a fax, the mesh routes it through peers to a node
      that can actually deliver it
    - Uses Kademlia DHT for routing, mDNS for LAN discovery
    - Encrypted store-and-forward for reliability
    - Trust/reputation scoring prevents abuse

    Architecture:
      You → [encrypted relay] → Peer B → [relay] → Peer C (has modem) → PSTN → Fax

    This is completely FREE:
    - No API keys needed
    - No phone line needed locally
    - Leverages the collective fax infrastructure of all mesh participants
    - N users × M faxes/day each = N×M total capacity for the network

    Setup:
      # Just enable it — peer discovery is automatic via mDNS on LAN
      # For WAN: add bootstrap peer addresses in .env
      P2P_RELAY_ENABLED=true
      P2P_RELAY_PORT=8765
      P2P_AREA_CODES=212,718  # area codes you can deliver to (if you have modem/SIP)
    """

    name = "p2p_relay"
    daily_limit = 0  # unlimited — depends on mesh capacity
    requires_config = []

    _node = None  # singleton relay node

    def is_available(self) -> bool:
        return config.P2P_RELAY_ENABLED

    def _get_node(self):
        """Get or create the singleton P2P relay node."""
        if P2PRelayProvider._node is None:
            from p2p_relay import P2PRelayNode
            P2PRelayProvider._node = P2PRelayNode(
                host=config.P2P_RELAY_HOST,
                port=config.P2P_RELAY_PORT,
                capabilities=self._detect_capabilities(),
                area_codes=config.P2P_AREA_CODES,
                country_codes=config.P2P_COUNTRY_CODES,
            )
            # Add bootstrap peers
            for peer in config.P2P_BOOTSTRAP_PEERS:
                if ":" in peer:
                    host, port = peer.rsplit(":", 1)
                    P2PRelayProvider._node.add_bootstrap_peer(host, int(port))
            P2PRelayProvider._node.start()
        return P2PRelayProvider._node

    def _detect_capabilities(self) -> list:
        """Auto-detect what fax capabilities this node has."""
        caps = []
        if shutil.which("asterisk") and config.AMI_SECRET:
            caps.append("sip")
        if os.path.exists("/dev/t38modem0") or shutil.which("t38modem"):
            caps.append("virtual_modem")
        if shutil.which("efax") and os.path.exists(config.MODEM_DEVICE):
            caps.append("modem")
        if config.SMTP_USER and config.SMTP_PASS:
            caps.append("email")
        if config.FAXZERO_API_KEY:
            caps.append("faxzero")
        return caps

    def send(self, tiff_path: str, to_number: str, **kwargs) -> dict:
        try:
            node = self._get_node()
            result = node.relay_fax(to_number, tiff_path)

            if result["success"]:
                self.record_send()
                route = result.get("route", "unknown")
                msg_parts = [f"Fax relayed via P2P mesh ({route})"]
                if result.get("relay_peer"):
                    msg_parts.append(f"via peer {result['relay_peer']}")
                if result.get("hops"):
                    msg_parts.append(f"{result['hops']} hops")

                return {
                    "success": True,
                    "provider_fax_id": result.get("job_id", ""),
                    "message": " — ".join(msg_parts),
                }
            else:
                return {
                    "success": False,
                    "provider_fax_id": "",
                    "message": result.get("message", "P2P relay failed"),
                }

        except Exception as e:
            return {"success": False, "provider_fax_id": "", "message": str(e)}

    def get_mesh_status(self) -> dict:
        """Get P2P mesh network status."""
        try:
            node = self._get_node()
            return node.get_mesh_status()
        except Exception:
            return {"error": "P2P relay not running"}


# ══════════════════════════════════════════════════════════════════════════════
# 5. FAXZERO — Free API fallback (5/day)
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
    ENUMFaxProvider(),        # FREE: DNS route discovery → direct SIP (no PSTN!)
    VirtualModemFaxProvider(),  # FREE: software modem, no hardware
    SIPFaxProvider(),         # FREE: Asterisk + SIP/T.38
    EmailFaxProvider(),       # FREE: RFC 3965 via your SMTP
    ModemFaxProvider(),       # FREE: USB modem + efax (needs hardware)
    P2PRelayProvider(),       # FREE: Decentralized mesh relay (no hardware!)
    FaxZeroProvider(),        # FALLBACK: 5 free/day
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

    Priority (most free/local first):
    0. ENUM → SIP (DNS discovery, completely free, no PSTN!)
    1. Virtual Modem (t38modem, no hardware)
    2. SIP/T.38 via Asterisk
    3. Email (if recipient has email)
    4. USB Modem (if hardware connected)
    5. FaxZero (fallback, 5 free/day)
    """
    available = get_available_providers()
    avail_names = {p.name for p in available}

    # ENUM first — tries DNS to bypass PSTN entirely
    if "enum_sip" in avail_names:
        return get_provider("enum_sip")

    # Virtual modem — software-only, no hardware
    if "virtual_modem" in avail_names:
        return get_provider("virtual_modem")

    # Asterisk SIP/T.38
    if "sip_t38" in avail_names:
        return get_provider("sip_t38")

    # Email fax — only if recipient has email address
    if "@" in to_address and "email_fax" in avail_names:
        return get_provider("email_fax")

    # USB modem
    if "usb_modem" in avail_names:
        return get_provider("usb_modem")

    # P2P relay mesh — try the decentralized network
    if "p2p_relay" in avail_names:
        return get_provider("p2p_relay")

    # FaxZero fallback
    for p in available:
        if p.name == "faxzero" and p.remaining_today() > 0:
            return p

    return None
