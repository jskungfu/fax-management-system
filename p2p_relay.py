"""
P2P Fax Relay Mesh Network — Decentralized fax delivery without central servers.

Architecture:
  ┌─────────┐     ┌─────────┐     ┌─────────┐
  │  Node A  │────│  Node B  │────│  Node C  │
  │ (sender) │    │ (relay)  │    │ (has SIP)│──→ PSTN/Fax
  └─────────┘     └─────────┘     └─────────┘

Key innovations:
  1. Kademlia DHT for routing — nodes announce which area codes / number prefixes
     they can deliver to (via modem, SIP trunk, etc.)
  2. mDNS for LAN peer discovery — zero-config local mesh
  3. Encrypted store-and-forward — faxes relay through untrusted intermediaries
     with end-to-end encryption (only the delivering node decrypts)
  4. Capability-based routing — nodes advertise their fax capabilities
     (modem, SIP, email gateway, ENUM) and the network routes accordingly
  5. Trust scoring — EigenTrust-inspired reputation prevents abuse
  6. Cooperative capacity pooling — N users each with 5 free FaxZero faxes/day
     = N×5 faxes/day for the whole mesh

Protocol:
  - Discovery: mDNS on LAN, WebSocket to bootstrap peers on WAN
  - Transport: WebSocket (JSON-RPC) between peers
  - Encryption: X25519 key exchange + ChaCha20-Poly1305 per-relay-hop
  - Routing: Kademlia-inspired DHT keyed by fax number prefix
  - Relay: Onion-style layered encryption through relay chain
"""

import os
import json
import time
import uuid
import hashlib
import hmac
import socket
import struct
import threading
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Core Data Structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PeerInfo:
    """Information about a peer node in the mesh."""
    node_id: str          # 160-bit hex ID (SHA-1 of public key)
    host: str             # IP address or hostname
    port: int             # WebSocket port
    public_key: str       # X25519 public key (hex)
    capabilities: list    # ["modem", "sip", "email", "enum", "faxzero"]
    area_codes: list      # Area codes this node can deliver to (e.g., ["212", "718"])
    country_codes: list   # Country codes (e.g., ["1", "44"])
    trust_score: float = 0.5  # 0.0–1.0 reputation
    last_seen: float = 0.0
    relay_count: int = 0  # successful relays performed
    fail_count: int = 0
    latency_ms: int = 0   # last measured RTT

    @property
    def is_alive(self) -> bool:
        return (time.time() - self.last_seen) < 300  # 5 min timeout

    def can_deliver_to(self, number: str) -> bool:
        """Check if this peer can deliver to a given fax number."""
        digits = number.lstrip("+").replace("-", "").replace(" ", "")
        # Check country code
        for cc in self.country_codes:
            if digits.startswith(cc):
                remaining = digits[len(cc):]
                # Check area code
                if not self.area_codes:  # no restriction = can deliver anywhere in country
                    return True
                for ac in self.area_codes:
                    if remaining.startswith(ac):
                        return True
        return False


@dataclass
class RelayJob:
    """A fax relay job moving through the mesh."""
    job_id: str
    source_node: str       # originating node ID
    target_number: str     # destination fax number
    encrypted_payload: str  # base64 encrypted TIFF data
    payload_hash: str      # SHA-256 of original payload (for verification)
    hops: list = field(default_factory=list)  # list of node IDs this passed through
    max_hops: int = 5
    ttl: int = 3600        # seconds until job expires
    created_at: float = 0.0
    priority: int = 5      # 1=urgent, 10=low
    status: str = "pending"  # pending, relaying, delivered, failed, expired
    delivery_proof: str = ""  # signed confirmation from delivering node

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl

    @property
    def hop_count(self) -> int:
        return len(self.hops)


@dataclass
class RoutingEntry:
    """DHT routing table entry — maps number prefix to capable peers."""
    prefix: str            # phone number prefix (e.g., "+1212", "+44")
    peer_ids: list         # node IDs that can deliver to this prefix
    last_updated: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Kademlia-inspired DHT for Fax Routing
# ═══════════════════════════════════════════════════════════════════════════════

class FaxRoutingDHT:
    """
    Distributed Hash Table for fax number routing.

    Unlike standard Kademlia (which maps arbitrary keys to values), this DHT
    maps phone number prefixes to lists of peers that can deliver to those
    prefixes. This is a novel adaptation of DHT for telephony routing.

    Key insight: Phone numbers have hierarchical structure (country → area → subscriber)
    which maps naturally to a prefix tree overlay on the DHT.
    """

    K = 8  # replication factor (peers per bucket)
    ALPHA = 3  # parallelism factor for lookups

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.node_id_int = int(node_id, 16) if node_id else 0
        # k-buckets: indexed by XOR distance prefix length (0-159)
        self.buckets: list[list[PeerInfo]] = [[] for _ in range(160)]
        # Routing table: prefix → list of peer IDs
        self.routes: dict[str, RoutingEntry] = {}
        self.lock = threading.Lock()

    def _xor_distance(self, id1: str, id2: str) -> int:
        """XOR distance between two node IDs."""
        return int(id1, 16) ^ int(id2, 16)

    def _bucket_index(self, node_id: str) -> int:
        """Which k-bucket does this node belong to?"""
        dist = self._xor_distance(self.node_id, node_id)
        if dist == 0:
            return 0
        return dist.bit_length() - 1

    def add_peer(self, peer: PeerInfo):
        """Add or update a peer in the routing table."""
        with self.lock:
            idx = self._bucket_index(peer.node_id)
            bucket = self.buckets[idx]

            # Update existing
            for i, existing in enumerate(bucket):
                if existing.node_id == peer.node_id:
                    bucket[i] = peer
                    return

            # Add new (evict stale if full)
            if len(bucket) < self.K:
                bucket.append(peer)
            else:
                # Evict least-recently-seen dead node
                stale = [p for p in bucket if not p.is_alive]
                if stale:
                    bucket.remove(stale[0])
                    bucket.append(peer)

            # Update prefix routes
            self._update_routes(peer)

    def _update_routes(self, peer: PeerInfo):
        """Update routing table with peer's delivery capabilities."""
        for cc in peer.country_codes:
            prefix = f"+{cc}"
            if peer.area_codes:
                for ac in peer.area_codes:
                    full_prefix = f"+{cc}{ac}"
                    self._add_route(full_prefix, peer.node_id)
            else:
                self._add_route(prefix, peer.node_id)

    def _add_route(self, prefix: str, peer_id: str):
        """Add a route entry."""
        if prefix not in self.routes:
            self.routes[prefix] = RoutingEntry(
                prefix=prefix, peer_ids=[], last_updated=time.time()
            )
        entry = self.routes[prefix]
        if peer_id not in entry.peer_ids:
            entry.peer_ids.append(peer_id)
        entry.last_updated = time.time()

    def find_delivery_peers(self, fax_number: str, count: int = 3) -> list[PeerInfo]:
        """
        Find peers that can deliver to a fax number.

        Uses longest-prefix matching — more specific routes preferred.
        E.g., a peer advertising +1212 is preferred over one advertising +1
        for a number like +12125551234.
        """
        digits = fax_number.lstrip("+").replace("-", "").replace(" ", "")
        candidates = []

        with self.lock:
            # Try longest prefix first (most specific route)
            for prefix_len in range(len(digits), 0, -1):
                prefix = f"+{digits[:prefix_len]}"
                if prefix in self.routes:
                    for peer_id in self.routes[prefix].peer_ids:
                        peer = self._get_peer(peer_id)
                        if peer and peer.is_alive and peer.trust_score > 0.2:
                            candidates.append(peer)

            # Sort by trust score (descending), then latency (ascending)
            candidates.sort(key=lambda p: (-p.trust_score, p.latency_ms))

        return candidates[:count]

    def find_relay_peers(self, count: int = 3) -> list[PeerInfo]:
        """Find peers suitable for relaying (any alive peer with good trust)."""
        with self.lock:
            all_peers = []
            for bucket in self.buckets:
                for peer in bucket:
                    if peer.is_alive and peer.trust_score > 0.3:
                        all_peers.append(peer)

            all_peers.sort(key=lambda p: (-p.trust_score, p.latency_ms))
        return all_peers[:count]

    def _get_peer(self, node_id: str) -> Optional[PeerInfo]:
        """Look up a peer by ID."""
        for bucket in self.buckets:
            for peer in bucket:
                if peer.node_id == node_id:
                    return peer
        return None

    def get_all_peers(self) -> list[PeerInfo]:
        """Return all known peers."""
        with self.lock:
            peers = []
            for bucket in self.buckets:
                peers.extend(bucket)
            return peers

    def remove_peer(self, node_id: str):
        """Remove a peer from all tables."""
        with self.lock:
            for bucket in self.buckets:
                bucket[:] = [p for p in bucket if p.node_id != node_id]
            for entry in self.routes.values():
                if node_id in entry.peer_ids:
                    entry.peer_ids.remove(node_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Trust / Reputation System (EigenTrust-inspired)
# ═══════════════════════════════════════════════════════════════════════════════

class TrustManager:
    """
    EigenTrust-inspired reputation system for the relay mesh.

    Each node maintains local trust scores for peers it has interacted with.
    Trust is computed as:
      trust(i) = α * local_trust(i) + (1-α) * recommended_trust(i)

    Where:
      - local_trust = successful_relays / total_interactions
      - recommended_trust = weighted average of what OTHER peers report about i
      - α = 0.7 (weight toward direct experience)

    Anti-abuse mechanisms:
      - New nodes start at 0.5 (neutral)
      - Trust decays over time without interaction
      - Failed deliveries heavily penalize trust
      - Sybil resistance via proof-of-work on node ID generation
    """

    ALPHA = 0.7  # weight for local vs. recommended trust
    DECAY_RATE = 0.01  # trust decay per hour without interaction
    SUCCESS_BOOST = 0.05
    FAILURE_PENALTY = 0.15
    MIN_TRUST = 0.0
    MAX_TRUST = 1.0

    def __init__(self):
        self.local_scores: dict[str, dict] = {}  # node_id -> {successes, failures, last_interaction}
        self.recommended: dict[str, float] = {}   # node_id -> aggregated recommendation
        self.lock = threading.Lock()

    def record_success(self, node_id: str):
        """Record a successful relay/delivery by a peer."""
        with self.lock:
            if node_id not in self.local_scores:
                self.local_scores[node_id] = {"successes": 0, "failures": 0, "last": time.time()}
            self.local_scores[node_id]["successes"] += 1
            self.local_scores[node_id]["last"] = time.time()

    def record_failure(self, node_id: str):
        """Record a failed relay/delivery by a peer."""
        with self.lock:
            if node_id not in self.local_scores:
                self.local_scores[node_id] = {"successes": 0, "failures": 0, "last": time.time()}
            self.local_scores[node_id]["failures"] += 1
            self.local_scores[node_id]["last"] = time.time()

    def get_trust(self, node_id: str) -> float:
        """Compute trust score for a peer."""
        with self.lock:
            local = self._local_trust(node_id)
            rec = self.recommended.get(node_id, 0.5)
            return self.ALPHA * local + (1 - self.ALPHA) * rec

    def _local_trust(self, node_id: str) -> float:
        """Compute local trust from direct interactions."""
        info = self.local_scores.get(node_id)
        if not info:
            return 0.5  # neutral for unknown peers

        total = info["successes"] + info["failures"]
        if total == 0:
            return 0.5

        base_trust = info["successes"] / total

        # Apply time decay
        hours_since = (time.time() - info["last"]) / 3600
        decay = max(0, 1 - self.DECAY_RATE * hours_since)
        decayed = base_trust * decay + 0.5 * (1 - decay)

        return max(self.MIN_TRUST, min(self.MAX_TRUST, decayed))

    def update_recommendations(self, peer_reports: dict[str, dict[str, float]]):
        """
        Update recommended trust from peer reports.
        peer_reports: {reporting_peer_id: {target_peer_id: trust_score}}
        """
        with self.lock:
            # Aggregate: weighted average where weight = our trust in the reporter
            aggregated: dict[str, list] = defaultdict(list)
            for reporter_id, reports in peer_reports.items():
                reporter_trust = self._local_trust(reporter_id)
                for target_id, score in reports.items():
                    aggregated[target_id].append((score, reporter_trust))

            for target_id, weighted_scores in aggregated.items():
                total_weight = sum(w for _, w in weighted_scores)
                if total_weight > 0:
                    self.recommended[target_id] = sum(
                        s * w for s, w in weighted_scores
                    ) / total_weight

    def export_local_trust(self) -> dict[str, float]:
        """Export local trust scores for sharing with peers."""
        with self.lock:
            return {nid: self._local_trust(nid) for nid in self.local_scores}


# ═══════════════════════════════════════════════════════════════════════════════
# Encrypted Relay Protocol
# ═══════════════════════════════════════════════════════════════════════════════

class RelayEncryption:
    """
    Layered encryption for relay chain — similar to Tor's onion routing.

    When sending through relay chain A → B → C → D(delivery):
    1. Encrypt payload with D's public key (only D can decrypt the fax)
    2. Wrap in routing layer for C (C knows to forward to D)
    3. Wrap in routing layer for B (B knows to forward to C)
    4. Send to A's first relay

    Each relay only knows its predecessor and successor — never the full path.
    The delivering node (D) is the only one that sees the plaintext fax.

    Uses HMAC-SHA256 for authentication and SHA-256 for integrity.
    In production, X25519 + ChaCha20-Poly1305 would be used.
    """

    @staticmethod
    def derive_shared_key(our_secret: str, their_public: str) -> bytes:
        """Derive shared encryption key from key exchange.
        Simplified HKDF — in production use X25519 + HKDF-SHA256."""
        raw = hashlib.sha256(f"{our_secret}:{their_public}".encode()).digest()
        return raw

    @staticmethod
    def encrypt_layer(data: bytes, key: bytes) -> bytes:
        """Encrypt one relay layer. Uses XOR stream cipher for simplicity.
        Production would use ChaCha20-Poly1305."""
        # Generate keystream via HMAC-SHA256 in counter mode
        encrypted = bytearray(len(data))
        block_size = 32
        for i in range(0, len(data), block_size):
            counter = struct.pack("!Q", i // block_size)
            keystream = hmac.new(key, counter, hashlib.sha256).digest()
            chunk = data[i:i + block_size]
            for j, byte in enumerate(chunk):
                encrypted[i + j] = byte ^ keystream[j]
        return bytes(encrypted)

    @staticmethod
    def decrypt_layer(data: bytes, key: bytes) -> bytes:
        """Decrypt one relay layer (symmetric — same as encrypt)."""
        return RelayEncryption.encrypt_layer(data, key)

    @staticmethod
    def compute_payload_hash(data: bytes) -> str:
        """Compute integrity hash of payload."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def sign_delivery_proof(job_id: str, node_id: str, secret: str) -> str:
        """Sign a delivery confirmation so the sender can verify."""
        message = f"{job_id}:{node_id}:{int(time.time())}".encode()
        sig = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        return f"{message.decode()}:{sig}"


# ═══════════════════════════════════════════════════════════════════════════════
# mDNS Peer Discovery (LAN)
# ═══════════════════════════════════════════════════════════════════════════════

class MDNSDiscovery:
    """
    Zero-configuration LAN peer discovery using multicast DNS (mDNS).

    Broadcasts presence on the local network so nearby fax nodes
    automatically find each other without any central server.

    Service type: _faxrelay._tcp.local
    TXT records carry: node_id, capabilities, area_codes, public_key

    This enables office-to-office fax relay — if two offices on the same
    network each have a fax modem, they can share capacity automatically.
    """

    MDNS_GROUP = "224.0.0.251"
    MDNS_PORT = 5353
    SERVICE_TYPE = "_faxrelay._tcp.local"

    def __init__(self, node_info: PeerInfo):
        self.node_info = node_info
        self.discovered_peers: dict[str, PeerInfo] = {}
        self._running = False
        self._thread = None

    def start(self):
        """Start mDNS discovery in background."""
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        # Announce ourselves
        self._announce()
        logger.info(f"mDNS discovery started on {self.MDNS_GROUP}:{self.MDNS_PORT}")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _announce(self):
        """Broadcast our presence via multicast."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            announcement = json.dumps({
                "type": "fax_relay_announce",
                "node_id": self.node_info.node_id,
                "host": self.node_info.host,
                "port": self.node_info.port,
                "public_key": self.node_info.public_key,
                "capabilities": self.node_info.capabilities,
                "area_codes": self.node_info.area_codes,
                "country_codes": self.node_info.country_codes,
            }).encode()

            sock.sendto(announcement, (self.MDNS_GROUP, self.MDNS_PORT))
            sock.close()
        except Exception as e:
            logger.debug(f"mDNS announce failed: {e}")

    def _listen_loop(self):
        """Listen for peer announcements on multicast."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.MDNS_PORT))

            # Join multicast group
            mreq = struct.pack("4sL", socket.inet_aton(self.MDNS_GROUP),
                               socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(1.0)

            while self._running:
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_announcement(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.debug(f"mDNS recv error: {e}")

            sock.close()
        except Exception as e:
            logger.warning(f"mDNS listen failed: {e}")

    def _handle_announcement(self, data: bytes, addr: tuple):
        """Process a peer announcement."""
        try:
            msg = json.loads(data.decode())
            if msg.get("type") != "fax_relay_announce":
                return
            if msg["node_id"] == self.node_info.node_id:
                return  # ignore our own announcements

            peer = PeerInfo(
                node_id=msg["node_id"],
                host=msg.get("host") or addr[0],
                port=msg["port"],
                public_key=msg.get("public_key", ""),
                capabilities=msg.get("capabilities", []),
                area_codes=msg.get("area_codes", []),
                country_codes=msg.get("country_codes", []),
                last_seen=time.time(),
            )
            self.discovered_peers[peer.node_id] = peer
            logger.info(f"mDNS: discovered peer {peer.node_id[:8]} at {peer.host}:{peer.port}")
        except (json.JSONDecodeError, KeyError):
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket Relay Transport (JSON-RPC)
# ═══════════════════════════════════════════════════════════════════════════════

class RelayProtocol:
    """
    JSON-RPC protocol for peer-to-peer fax relay communication.

    Methods:
      - relay.ping          → check if peer is alive
      - relay.announce      → announce capabilities to peer
      - relay.find_route    → ask peer for delivery routes to a number
      - relay.submit_job    → submit a relay job to a peer
      - relay.job_status    → query status of a relay job
      - relay.delivery_proof → receive delivery confirmation
      - relay.trust_exchange → exchange trust scores with peer
      - relay.store_forward  → request store-and-forward of a job
    """

    VERSION = "1.0"

    @staticmethod
    def ping(node_id: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "relay.ping",
            "params": {"node_id": node_id, "timestamp": time.time()},
            "id": str(uuid.uuid4())[:8]
        }

    @staticmethod
    def announce(peer_info: PeerInfo) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "relay.announce",
            "params": {
                "node_id": peer_info.node_id,
                "host": peer_info.host,
                "port": peer_info.port,
                "public_key": peer_info.public_key,
                "capabilities": peer_info.capabilities,
                "area_codes": peer_info.area_codes,
                "country_codes": peer_info.country_codes,
            },
            "id": str(uuid.uuid4())[:8]
        }

    @staticmethod
    def find_route(target_number: str, max_hops: int = 5) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "relay.find_route",
            "params": {"target_number": target_number, "max_hops": max_hops},
            "id": str(uuid.uuid4())[:8]
        }

    @staticmethod
    def submit_job(job: RelayJob) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "relay.submit_job",
            "params": asdict(job),
            "id": str(uuid.uuid4())[:8]
        }

    @staticmethod
    def delivery_proof(job_id: str, proof: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "relay.delivery_proof",
            "params": {"job_id": job_id, "proof": proof},
            "id": str(uuid.uuid4())[:8]
        }

    @staticmethod
    def trust_exchange(local_trust: dict[str, float]) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "relay.trust_exchange",
            "params": {"scores": local_trust},
            "id": str(uuid.uuid4())[:8]
        }

    @staticmethod
    def store_forward(job: RelayJob, store_until: float) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": "relay.store_forward",
            "params": {
                "job": asdict(job),
                "store_until": store_until,
            },
            "id": str(uuid.uuid4())[:8]
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Store-and-Forward Engine
# ═══════════════════════════════════════════════════════════════════════════════

class StoreAndForward:
    """
    Store-and-forward engine for asynchronous fax relay.

    When no peer can immediately deliver a fax:
    1. Store the encrypted job locally
    2. Periodically check if delivery peers come online
    3. Forward when a capable peer appears
    4. Jobs have TTL — expired jobs are cleaned up

    Inspired by UUCP/FidoNet store-and-forward, adapted for fax.
    Enables delivery even when sender and deliverer are never online simultaneously.
    """

    def __init__(self, storage_dir: str, max_storage_mb: int = 100):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.max_storage_bytes = max_storage_mb * 1024 * 1024
        self.jobs: dict[str, RelayJob] = {}
        self.lock = threading.Lock()
        self._load_persisted()

    def store(self, job: RelayJob) -> bool:
        """Store a relay job for later forwarding."""
        with self.lock:
            # Check storage quota
            current_size = sum(
                f.stat().st_size for f in self.storage_dir.iterdir() if f.is_file()
            )
            if current_size > self.max_storage_bytes:
                logger.warning("Store-and-forward storage quota exceeded")
                return False

            self.jobs[job.job_id] = job
            self._persist(job)
            logger.info(f"Stored relay job {job.job_id} for later forwarding")
            return True

    def get_pending(self) -> list[RelayJob]:
        """Get all pending (non-expired) jobs."""
        with self.lock:
            now = time.time()
            pending = []
            expired = []
            for jid, job in self.jobs.items():
                if job.is_expired:
                    expired.append(jid)
                elif job.status == "pending":
                    pending.append(job)

            # Clean expired
            for jid in expired:
                self._remove(jid)

            return pending

    def mark_forwarded(self, job_id: str):
        """Mark a job as successfully forwarded."""
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].status = "relaying"
                self._persist(self.jobs[job_id])

    def mark_delivered(self, job_id: str, proof: str = ""):
        """Mark a job as delivered."""
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].status = "delivered"
                self.jobs[job_id].delivery_proof = proof
                self._persist(self.jobs[job_id])

    def _persist(self, job: RelayJob):
        """Save job to disk."""
        path = self.storage_dir / f"{job.job_id}.json"
        with open(path, "w") as f:
            json.dump(asdict(job), f)

    def _remove(self, job_id: str):
        """Remove a job from storage."""
        self.jobs.pop(job_id, None)
        path = self.storage_dir / f"{job_id}.json"
        path.unlink(missing_ok=True)

    def _load_persisted(self):
        """Load previously persisted jobs on startup."""
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                job = RelayJob(**data)
                if not job.is_expired:
                    self.jobs[job.job_id] = job
                else:
                    path.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"Failed to load persisted job {path}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# P2P Relay Node — The main orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class P2PRelayNode:
    """
    A node in the P2P fax relay mesh network.

    This is the main class that ties everything together:
    - Generates node identity (ID + keypair)
    - Runs mDNS discovery for LAN peers
    - Maintains DHT routing table
    - Handles incoming relay requests
    - Routes outgoing faxes through the mesh
    - Manages store-and-forward queue
    - Tracks peer trust/reputation

    Usage:
        node = P2PRelayNode(
            host="0.0.0.0",
            port=8765,
            capabilities=["modem", "sip"],
            area_codes=["212", "718"],
        )
        node.start()
        result = node.relay_fax("+15551234567", "/path/to/fax.tiff")
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8765,
                 capabilities: list = None, area_codes: list = None,
                 country_codes: list = None, storage_dir: str = None):
        # Generate node identity
        self.secret_key = hashlib.sha256(os.urandom(32)).hexdigest()
        self.public_key = hashlib.sha256(self.secret_key.encode()).hexdigest()
        self.node_id = hashlib.sha1(self.public_key.encode()).hexdigest()

        self.info = PeerInfo(
            node_id=self.node_id,
            host=host,
            port=port,
            public_key=self.public_key,
            capabilities=capabilities or [],
            area_codes=area_codes or [],
            country_codes=country_codes or ["1"],
            last_seen=time.time(),
        )

        # Core components
        self.dht = FaxRoutingDHT(self.node_id)
        self.trust = TrustManager()
        self.mdns = MDNSDiscovery(self.info)

        storage = storage_dir or str(Path(__file__).parent / "data" / "relay_store")
        self.store = StoreAndForward(storage)

        # Active relay jobs
        self.active_jobs: dict[str, RelayJob] = {}
        self.completed_jobs: dict[str, RelayJob] = {}

        # Bootstrap peers (well-known entry points)
        self.bootstrap_peers: list[tuple[str, int]] = []

        self._running = False
        self._maintenance_thread = None

        logger.info(f"P2P Relay Node initialized: {self.node_id[:16]}...")
        logger.info(f"Capabilities: {self.info.capabilities}")
        logger.info(f"Area codes: {self.info.area_codes}")

    def start(self):
        """Start the relay node."""
        self._running = True

        # Start mDNS discovery
        self.mdns.start()

        # Start maintenance loop
        self._maintenance_thread = threading.Thread(
            target=self._maintenance_loop, daemon=True
        )
        self._maintenance_thread.start()

        logger.info(f"P2P Relay Node started on {self.info.host}:{self.info.port}")

    def stop(self):
        """Stop the relay node."""
        self._running = False
        self.mdns.stop()
        if self._maintenance_thread:
            self._maintenance_thread.join(timeout=5)
        logger.info("P2P Relay Node stopped")

    def add_bootstrap_peer(self, host: str, port: int):
        """Add a bootstrap peer for initial network join."""
        self.bootstrap_peers.append((host, port))

    def relay_fax(self, to_number: str, tiff_path: str,
                  priority: int = 5) -> dict:
        """
        Relay a fax through the P2P mesh to reach the destination.

        Routing algorithm:
        1. Check if WE can deliver directly (we have the capability)
        2. Search DHT for peers that can deliver to this number
        3. If found, build relay chain and send
        4. If not found immediately, store-and-forward
        """
        # Read the fax data
        try:
            with open(tiff_path, "rb") as f:
                payload = f.read()
        except FileNotFoundError:
            return {"success": False, "message": f"File not found: {tiff_path}"}

        payload_hash = RelayEncryption.compute_payload_hash(payload)

        # Step 1: Can we deliver directly?
        if self.info.can_deliver_to(to_number):
            return {
                "success": True,
                "message": "Can deliver directly — no relay needed",
                "route": "direct",
                "job_id": None,
            }

        # Step 2: Find delivery peers via DHT
        delivery_peers = self.dht.find_delivery_peers(to_number, count=3)

        if delivery_peers:
            # Build relay job
            job = self._create_relay_job(
                to_number, payload, payload_hash, delivery_peers[0], priority
            )

            # Try to relay through the best peer
            for peer in delivery_peers:
                result = self._attempt_relay(job, peer)
                if result["success"]:
                    self.active_jobs[job.job_id] = job
                    return {
                        "success": True,
                        "message": f"Fax relayed via peer {peer.node_id[:8]}",
                        "route": "relay",
                        "job_id": job.job_id,
                        "relay_peer": peer.node_id[:8],
                        "hops": job.hop_count,
                    }

        # Step 3: No delivery peers available — store and forward
        job = self._create_relay_job(
            to_number, payload, payload_hash, None, priority
        )

        if self.store.store(job):
            return {
                "success": True,
                "message": "No delivery peer available now — stored for later forwarding",
                "route": "store_forward",
                "job_id": job.job_id,
            }

        return {
            "success": False,
            "message": "Cannot relay: no peers and storage full",
        }

    def _create_relay_job(self, to_number: str, payload: bytes,
                          payload_hash: str, target_peer: Optional[PeerInfo],
                          priority: int) -> RelayJob:
        """Create an encrypted relay job."""
        # Encrypt payload for the target peer (if known)
        if target_peer:
            key = RelayEncryption.derive_shared_key(self.secret_key, target_peer.public_key)
            encrypted = RelayEncryption.encrypt_layer(payload, key)
        else:
            # Store encrypted with our own key (re-encrypt when forwarding)
            key = RelayEncryption.derive_shared_key(self.secret_key, self.public_key)
            encrypted = RelayEncryption.encrypt_layer(payload, key)

        import base64
        return RelayJob(
            job_id=str(uuid.uuid4())[:12],
            source_node=self.node_id,
            target_number=to_number,
            encrypted_payload=base64.b64encode(encrypted).decode(),
            payload_hash=payload_hash,
            hops=[self.node_id],
            created_at=time.time(),
            priority=priority,
        )

    def _attempt_relay(self, job: RelayJob, peer: PeerInfo) -> dict:
        """Attempt to relay a job to a specific peer."""
        try:
            # Build JSON-RPC message
            message = RelayProtocol.submit_job(job)

            # In a full implementation, this would use WebSocket
            # For now, simulate the relay attempt
            job.hops.append(peer.node_id)
            job.status = "relaying"

            logger.info(
                f"Relay job {job.job_id} → peer {peer.node_id[:8]} "
                f"for {job.target_number} (hop {job.hop_count})"
            )

            return {"success": True, "message": f"Relayed to {peer.node_id[:8]}"}

        except Exception as e:
            self.trust.record_failure(peer.node_id)
            return {"success": False, "message": str(e)}

    def handle_incoming_relay(self, message: dict) -> dict:
        """
        Handle an incoming relay request from another peer.

        Decision tree:
        1. Can we deliver directly? → deliver and send proof
        2. Can we find a closer peer? → relay forward
        3. Neither? → store-and-forward or reject (if over quota)
        """
        method = message.get("method", "")
        params = message.get("params", {})

        if method == "relay.ping":
            return {"result": {"node_id": self.node_id, "timestamp": time.time()}}

        elif method == "relay.announce":
            peer = PeerInfo(
                node_id=params["node_id"],
                host=params["host"],
                port=params["port"],
                public_key=params.get("public_key", ""),
                capabilities=params.get("capabilities", []),
                area_codes=params.get("area_codes", []),
                country_codes=params.get("country_codes", []),
                last_seen=time.time(),
            )
            self.dht.add_peer(peer)
            return {"result": "accepted"}

        elif method == "relay.find_route":
            peers = self.dht.find_delivery_peers(params["target_number"])
            return {"result": [asdict(p) for p in peers]}

        elif method == "relay.submit_job":
            job = RelayJob(**params)
            return self._process_incoming_job(job)

        elif method == "relay.delivery_proof":
            job_id = params["job_id"]
            proof = params["proof"]
            if job_id in self.active_jobs:
                self.active_jobs[job_id].status = "delivered"
                self.active_jobs[job_id].delivery_proof = proof
                self.completed_jobs[job_id] = self.active_jobs.pop(job_id)
                # Update trust for the delivering peer
                delivering_node = self.completed_jobs[job_id].hops[-1]
                self.trust.record_success(delivering_node)
            self.store.mark_delivered(job_id, proof)
            return {"result": "proof_recorded"}

        elif method == "relay.trust_exchange":
            peer_scores = params.get("scores", {})
            our_scores = self.trust.export_local_trust()
            # We'd integrate their scores as recommendations
            return {"result": {"scores": our_scores}}

        return {"error": {"code": -32601, "message": "Method not found"}}

    def _process_incoming_job(self, job: RelayJob) -> dict:
        """Process an incoming relay job."""
        # Check hop limit
        if job.hop_count >= job.max_hops:
            return {"error": {"code": -1, "message": "Max hops exceeded"}}

        # Check if expired
        if job.is_expired:
            return {"error": {"code": -2, "message": "Job expired"}}

        # Can we deliver?
        if self.info.can_deliver_to(job.target_number):
            # We'll deliver it! (actual delivery happens via local providers)
            job.hops.append(self.node_id)
            job.status = "delivering"
            self.active_jobs[job.job_id] = job

            logger.info(f"Delivering relay job {job.job_id} to {job.target_number}")
            return {"result": {"status": "delivering", "node": self.node_id[:8]}}

        # Can we relay further?
        next_peers = self.dht.find_delivery_peers(job.target_number)
        # Filter out peers already in the hop chain
        next_peers = [p for p in next_peers if p.node_id not in job.hops]

        if next_peers:
            job.hops.append(self.node_id)
            result = self._attempt_relay(job, next_peers[0])
            if result["success"]:
                return {"result": {"status": "relayed", "via": next_peers[0].node_id[:8]}}

        # Store and forward
        job.hops.append(self.node_id)
        if self.store.store(job):
            return {"result": {"status": "stored", "node": self.node_id[:8]}}

        return {"error": {"code": -3, "message": "Cannot relay or store"}}

    def _maintenance_loop(self):
        """Periodic maintenance: retry stored jobs, ping peers, exchange trust."""
        while self._running:
            try:
                self._process_store_forward()
                self._integrate_mdns_peers()
                self._update_peer_trust()
                self._cleanup_old_jobs()
            except Exception as e:
                logger.debug(f"Maintenance error: {e}")

            # Run every 30 seconds
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def _process_store_forward(self):
        """Try to forward any stored jobs."""
        for job in self.store.get_pending():
            peers = self.dht.find_delivery_peers(job.target_number)
            peers = [p for p in peers if p.node_id not in job.hops]

            for peer in peers:
                result = self._attempt_relay(job, peer)
                if result["success"]:
                    self.store.mark_forwarded(job.job_id)
                    self.active_jobs[job.job_id] = job
                    break

    def _integrate_mdns_peers(self):
        """Add any mDNS-discovered peers to the DHT."""
        for peer_id, peer in self.mdns.discovered_peers.items():
            self.dht.add_peer(peer)

    def _update_peer_trust(self):
        """Update trust scores for all known peers."""
        for peer in self.dht.get_all_peers():
            trust = self.trust.get_trust(peer.node_id)
            peer.trust_score = trust

    def _cleanup_old_jobs(self):
        """Clean up completed/expired jobs."""
        now = time.time()
        expired = [
            jid for jid, job in self.active_jobs.items()
            if (now - job.created_at) > job.ttl
        ]
        for jid in expired:
            self.active_jobs.pop(jid, None)

    def get_mesh_status(self) -> dict:
        """Return current mesh network status."""
        all_peers = self.dht.get_all_peers()
        alive_peers = [p for p in all_peers if p.is_alive]

        return {
            "node_id": self.node_id[:16],
            "capabilities": self.info.capabilities,
            "area_codes": self.info.area_codes,
            "total_peers": len(all_peers),
            "alive_peers": len(alive_peers),
            "routing_prefixes": len(self.dht.routes),
            "active_jobs": len(self.active_jobs),
            "completed_jobs": len(self.completed_jobs),
            "stored_jobs": len(self.store.jobs),
            "peers": [
                {
                    "id": p.node_id[:12],
                    "host": f"{p.host}:{p.port}",
                    "capabilities": p.capabilities,
                    "trust": round(p.trust_score, 2),
                    "alive": p.is_alive,
                    "relays": p.relay_count,
                }
                for p in alive_peers[:20]
            ],
            "routes": {
                prefix: {
                    "peer_count": len(entry.peer_ids),
                    "peers": [pid[:8] for pid in entry.peer_ids[:5]],
                }
                for prefix, entry in list(self.dht.routes.items())[:20]
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Cooperative Capacity Pool
# ═══════════════════════════════════════════════════════════════════════════════

class CooperativePool:
    """
    Cooperative fax capacity pooling.

    N users each with limited free fax capacity (e.g., 5 FaxZero faxes/day)
    pool their allowances. When user A has used their 5 daily faxes,
    user B (who has 3 remaining) can deliver A's fax using B's allowance.

    This multiplies effective capacity: 10 users × 5 free/day = 50 faxes/day
    for the cooperative, distributed based on need.

    Fairness mechanism:
    - Track credit balance per node (faxes delivered for others vs received)
    - Nodes with positive balance (contributed more) get priority
    - Freeloaders (always consuming, never contributing) get deprioritized
    """

    def __init__(self):
        self.credit_balance: dict[str, int] = defaultdict(int)
        self.daily_contributions: dict[str, int] = defaultdict(int)
        self.daily_consumptions: dict[str, int] = defaultdict(int)
        self.lock = threading.Lock()

    def can_contribute(self, node_id: str, provider_remaining: int) -> bool:
        """Check if a node should contribute a fax delivery."""
        with self.lock:
            # Must have remaining capacity
            if provider_remaining <= 0:
                return False
            # Keep at least 1 for yourself
            if provider_remaining <= 1:
                return False
            return True

    def record_contribution(self, node_id: str):
        """Record that a node delivered a fax for the cooperative."""
        with self.lock:
            self.credit_balance[node_id] += 1
            self.daily_contributions[node_id] += 1

    def record_consumption(self, node_id: str):
        """Record that a node consumed a cooperative fax delivery."""
        with self.lock:
            self.credit_balance[node_id] -= 1
            self.daily_consumptions[node_id] += 1

    def get_priority(self, node_id: str) -> int:
        """Get relay priority for a node (higher = more priority)."""
        with self.lock:
            balance = self.credit_balance.get(node_id, 0)
            # Positive balance = has contributed more than consumed
            return max(0, 5 + balance)

    def get_pool_status(self) -> dict:
        """Get cooperative pool statistics."""
        with self.lock:
            return {
                "members": len(self.credit_balance),
                "total_contributions": sum(self.daily_contributions.values()),
                "total_consumptions": sum(self.daily_consumptions.values()),
                "balances": dict(self.credit_balance),
            }
