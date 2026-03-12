#!/usr/bin/env python3
"""
sendfax — CLI tool for sending faxes using free, local methods.

Usage:
  python sendfax.py send --to +15551234567 --file document.pdf
  python sendfax.py send --to user@efax.com --file doc.pdf --provider email_fax
  python sendfax.py status <fax-id>
  python sendfax.py history
  python sendfax.py providers
  python sendfax.py contacts
"""

import argparse
import sys
import json

import database as db
from queue_manager import submit_fax, get_system_status, process_retries
from providers import get_available_providers, ALL_PROVIDERS


def cmd_send(args):
    """Send a fax."""
    result = submit_fax(
        to_number=args.to,
        file_path=args.file,
        to_name=args.to_name or "",
        from_number=args.from_number or "",
        from_name=args.from_name or "",
        from_email=args.from_email or "",
        cover_message=args.message or "",
        provider_name=args.provider,
    )

    if "error" in result:
        print(f"\n  ERROR: {result['error']}\n")
        sys.exit(1)

    print(f"\n  Fax #{result['id']}")
    print(f"  Status:   {result['status']}")
    print(f"  To:       {result['to_number']}")
    print(f"  Provider: {result['provider']}")
    if result.get("error_message"):
        print(f"  Error:    {result['error_message']}")
    if result.get("provider_fax_id"):
        print(f"  Ref:      {result['provider_fax_id']}")
    print()


def cmd_status(args):
    """Check fax status."""
    fax = db.get_fax(args.id)
    if not fax:
        print(f"  Fax #{args.id} not found")
        sys.exit(1)
    print(f"\n  Fax #{fax['id']}")
    print(f"  Status:   {fax['status']}")
    print(f"  To:       {fax['to_name']} {fax['to_number']}")
    print(f"  From:     {fax['from_name']} {fax['from_number']}")
    print(f"  Provider: {fax['provider']}")
    print(f"  Created:  {fax['created_at']}")
    if fax.get("error_message"):
        print(f"  Error:    {fax['error_message']}")
    if fax.get("next_retry_at"):
        print(f"  Retry at: {fax['next_retry_at']}")
    print()


def cmd_history(args):
    """List fax history."""
    faxes = db.list_faxes(limit=args.limit)
    if not faxes:
        print("\n  No faxes yet.\n")
        return

    print(f"\n  {'ID':<10} {'TO':<18} {'STATUS':<15} {'PROVIDER':<12} {'DATE'}")
    print(f"  {'─'*10} {'─'*18} {'─'*15} {'─'*12} {'─'*20}")
    for f in faxes:
        status = f["status"]
        if status == "sent":
            status = "✓ sent"
        elif status == "failed":
            status = "✗ failed"
        elif status == "retry_pending":
            status = "↻ retry"
        print(f"  {f['id']:<10} {f['to_number']:<18} {status:<15} {f['provider'] or '':<12} {f['created_at'][:16]}")
    print()


def cmd_providers(args):
    """Show provider status."""
    print("\n  FAX PROVIDERS")
    print(f"  {'─'*55}")
    for p in ALL_PROVIDERS:
        avail = "✓ READY" if p.is_available() else "✗ not configured"
        limit = f"{p.daily_limit}/day" if p.daily_limit else "unlimited"
        remaining = p.remaining_today() if p.is_available() else "-"
        print(f"  {p.name:<14} {avail:<20} {limit:<12} remaining: {remaining}")
    print(f"\n  Configure providers in .env file.\n")
    print("  FREE — no phone line, no hardware, no API:")
    print("    enum_sip      — ENUM DNS discovery → direct SIP/T.38 (RFC 6116)")
    print("    virtual_modem — Software modem via t38modem (no hardware)")
    print("    sip_t38       — Asterisk + SIP/T.38 (apt install asterisk)")
    print("    email_fax     — RFC 3965 via your own SMTP (Gmail etc)")
    print("  FREE — needs hardware:")
    print("    usb_modem     — USB fax modem + efax (apt install efax)")
    print("  Fallback (external):")
    print("    faxzero       — 5 free/day via FaxZero API\n")


def cmd_contacts(args):
    """List contacts."""
    contacts = db.list_contacts()
    if not contacts:
        print("\n  No contacts yet. Add with: sendfax.py contact-add --name 'Name' --number '+1555...'\n")
        return
    print(f"\n  {'ID':<5} {'NAME':<20} {'NUMBER':<18} {'COMPANY':<15} {'SIP/EMAIL'}")
    print(f"  {'─'*5} {'─'*20} {'─'*18} {'─'*15} {'─'*20}")
    for c in contacts:
        extra = c.get("sip_uri") or c.get("email") or ""
        print(f"  {c['id']:<5} {c['name']:<20} {c['fax_number']:<18} {c.get('company',''):<15} {extra}")
    print()


def cmd_contact_add(args):
    """Add a contact."""
    contact = db.create_contact(
        name=args.name, fax_number=args.number,
        company=args.company or "", email=args.email or "",
        sip_uri=args.sip or ""
    )
    print(f"\n  Contact added: {contact['name']} ({contact['fax_number']})\n")


def cmd_retry(args):
    """Process pending retries."""
    process_retries()
    print("  Retries processed.\n")


def cmd_mesh(args):
    """Show P2P mesh network status."""
    from providers import get_provider
    p2p = get_provider("p2p_relay")
    if not p2p or not p2p.is_available():
        print("\n  P2P relay not enabled. Set P2P_RELAY_ENABLED=true in .env\n")
        return

    mesh = p2p.get_mesh_status()
    print("\n  ╔══════════════════════════════════════╗")
    print("  ║     P2P FAX RELAY MESH NETWORK       ║")
    print("  ╚══════════════════════════════════════╝\n")

    print(f"  Node ID:     {mesh.get('node_id', 'unknown')}")
    print(f"  Capabilities: {', '.join(mesh.get('capabilities', [])) or 'relay only'}")
    print(f"  Area codes:  {', '.join(mesh.get('area_codes', [])) or 'any'}")
    print(f"\n  Peers: {mesh.get('alive_peers', 0)} alive / {mesh.get('total_peers', 0)} total")
    print(f"  Routes: {mesh.get('routing_prefixes', 0)} phone prefixes")
    print(f"  Jobs: {mesh.get('active_jobs', 0)} active, {mesh.get('stored_jobs', 0)} stored, "
          f"{mesh.get('completed_jobs', 0)} completed")

    peers = mesh.get("peers", [])
    if peers:
        print(f"\n  {'NODE':<14} {'ADDRESS':<20} {'CAPS':<18} {'TRUST':<7} {'STATUS'}")
        print(f"  {'─'*14} {'─'*20} {'─'*18} {'─'*7} {'─'*8}")
        for p in peers:
            caps = ",".join(p.get("capabilities", []))[:16]
            status_icon = "●" if p.get("alive") else "○"
            print(f"  {p['id']:<14} {p['host']:<20} {caps:<18} {p['trust']:<7} {status_icon}")

    routes = mesh.get("routes", {})
    if routes:
        print(f"\n  ROUTING TABLE:")
        for prefix, info in routes.items():
            print(f"    {prefix:<8} → {info['peer_count']} peers [{', '.join(info.get('peers', []))}]")
    print()


def cmd_dashboard(args):
    """Show system dashboard."""
    status = get_system_status()

    print("\n  ╔══════════════════════════════════════╗")
    print("  ║       FAX MANAGEMENT SYSTEM          ║")
    print("  ╚══════════════════════════════════════╝\n")

    s = status["stats"]
    print(f"  Total: {s['total']}  |  Sent: {s['sent']}  |  Failed: {s['failed']}  |  "
          f"Queued: {s['queued']}  |  Retry: {s['retry']}\n")

    print("  PROVIDERS:")
    for p in status["providers"]:
        icon = "●" if p["available"] else "○"
        limit = f"{p['daily_limit']}/day" if p["daily_limit"] else "unlimited"
        print(f"    {icon} {p['name']:<14} {'READY' if p['available'] else 'OFF':<8} "
              f"{limit:<12} left: {p['remaining_today']}")

    usage = status["usage_today"]
    if usage:
        print(f"\n  TODAY'S USAGE:")
        for provider, count in usage.items():
            print(f"    {provider}: {count} sent")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Send faxes using free local methods (SIP/T.38, Email, USB Modem)")
    sub = parser.add_subparsers(dest="command")

    # send
    p_send = sub.add_parser("send", help="Send a fax")
    p_send.add_argument("--to", required=True, help="Recipient fax number or email")
    p_send.add_argument("--file", required=True, help="Document to fax (PDF, image, text)")
    p_send.add_argument("--to-name", help="Recipient name")
    p_send.add_argument("--from-number", help="Sender fax number")
    p_send.add_argument("--from-name", help="Sender name")
    p_send.add_argument("--from-email", help="Sender email")
    p_send.add_argument("--message", "-m", help="Cover page message")
    p_send.add_argument("--provider", "-p", help="Force specific provider")

    # status
    p_status = sub.add_parser("status", help="Check fax status")
    p_status.add_argument("id", help="Fax ID")

    # history
    p_hist = sub.add_parser("history", help="Fax history")
    p_hist.add_argument("--limit", type=int, default=20)

    # providers
    sub.add_parser("providers", help="Show available providers")

    # contacts
    sub.add_parser("contacts", help="List contacts")

    # contact-add
    p_ca = sub.add_parser("contact-add", help="Add a contact")
    p_ca.add_argument("--name", required=True)
    p_ca.add_argument("--number", required=True)
    p_ca.add_argument("--company", default="")
    p_ca.add_argument("--email", default="")
    p_ca.add_argument("--sip", default="")

    # retry
    sub.add_parser("retry", help="Process pending retries")

    # dashboard
    sub.add_parser("dashboard", help="System dashboard")

    # mesh
    sub.add_parser("mesh", help="P2P mesh network status")

    args = parser.parse_args()

    commands = {
        "send": cmd_send,
        "status": cmd_status,
        "history": cmd_history,
        "providers": cmd_providers,
        "contacts": cmd_contacts,
        "contact-add": cmd_contact_add,
        "retry": cmd_retry,
        "dashboard": cmd_dashboard,
        "mesh": cmd_mesh,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
