#!/usr/bin/env python3
"""Flask web UI for the fax management system."""

import os
from pathlib import Path
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, send_from_directory)
from werkzeug.utils import secure_filename

import config
import database as db
from queue_manager import submit_fax, get_system_status, process_retries
from providers import ALL_PROVIDERS, get_available_providers

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".txt", ".bmp", ".gif"}


@app.route("/")
def dashboard():
    status = get_system_status()
    recent = db.list_faxes(limit=5)
    return render_template("dashboard.html", status=status, recent=recent)


@app.route("/send", methods=["GET", "POST"])
def send():
    if request.method == "POST":
        to_number = request.form.get("to_number", "").strip()
        if not to_number:
            flash("Recipient number/email is required", "error")
            return redirect(url_for("send"))

        file = request.files.get("document")
        if not file or not file.filename:
            flash("Document file is required", "error")
            return redirect(url_for("send"))

        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXT:
            flash(f"Unsupported file type: {ext}", "error")
            return redirect(url_for("send"))

        filename = secure_filename(file.filename)
        filepath = str(config.UPLOAD_DIR / filename)
        file.save(filepath)

        result = submit_fax(
            to_number=to_number,
            file_path=filepath,
            to_name=request.form.get("to_name", ""),
            from_number=request.form.get("from_number", ""),
            from_name=request.form.get("from_name", ""),
            from_email=request.form.get("from_email", ""),
            cover_message=request.form.get("cover_message", ""),
            provider_name=request.form.get("provider") or None,
        )

        if "error" in result:
            flash(result["error"], "error")
        else:
            flash(f"Fax #{result['id']} — {result['status']} via {result['provider']}", "success")

        return redirect(url_for("history"))

    providers = get_available_providers()
    contacts = db.list_contacts()
    return render_template("send.html", providers=providers, contacts=contacts, config=config)


@app.route("/history")
def history():
    status_filter = request.args.get("status")
    faxes = db.list_faxes(status=status_filter, limit=50)
    return render_template("history.html", faxes=faxes, current_filter=status_filter)


@app.route("/fax/<fax_id>/delete", methods=["POST"])
def delete_fax(fax_id):
    db.delete_fax(fax_id)
    flash(f"Fax #{fax_id} deleted", "info")
    return redirect(url_for("history"))


@app.route("/contacts", methods=["GET", "POST"])
def contacts():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        number = request.form.get("fax_number", "").strip()
        if name and number:
            db.create_contact(
                name=name, fax_number=number,
                company=request.form.get("company", ""),
                email=request.form.get("email", ""),
                sip_uri=request.form.get("sip_uri", ""),
            )
            flash(f"Contact '{name}' added", "success")
        return redirect(url_for("contacts"))

    all_contacts = db.list_contacts()
    return render_template("contacts.html", contacts=all_contacts)


@app.route("/contact/<int:contact_id>/delete", methods=["POST"])
def delete_contact(contact_id):
    db.delete_contact(contact_id)
    flash("Contact deleted", "info")
    return redirect(url_for("contacts"))


@app.route("/audit")
def audit():
    logs = db.get_audit_log(limit=100)
    return render_template("audit.html", logs=logs)


# ── API endpoints (for programmatic use) ──

@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.json or {}
    to_number = data.get("to_number")
    file_path = data.get("file_path")
    if not to_number or not file_path:
        return jsonify({"error": "to_number and file_path required"}), 400

    result = submit_fax(
        to_number=to_number, file_path=file_path,
        to_name=data.get("to_name", ""),
        from_number=data.get("from_number", ""),
        from_name=data.get("from_name", ""),
        from_email=data.get("from_email", ""),
        cover_message=data.get("cover_message", ""),
        provider_name=data.get("provider"),
    )
    code = 200 if "error" not in result else 400
    return jsonify(result), code


@app.route("/api/status")
def api_status():
    return jsonify(get_system_status())


@app.route("/api/faxes")
def api_faxes():
    return jsonify(db.list_faxes(limit=50))


@app.route("/api/retry", methods=["POST"])
def api_retry():
    process_retries()
    return jsonify({"message": "Retries processed"})


if __name__ == "__main__":
    print(f"\n  Fax Management System")
    print(f"  http://localhost:{config.PORT}\n")
    available = get_available_providers()
    if available:
        print(f"  Available providers: {', '.join(p.name for p in available)}")
    else:
        print("  WARNING: No providers configured. Edit .env to set up at least one.")
    print()
    app.run(host="0.0.0.0", port=config.PORT, debug=True)
