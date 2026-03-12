"""Smart fax queue: routes faxes through available providers with retry logic."""

import time
from datetime import datetime, timedelta

import database as db
import config
from documents import to_tiff, generate_cover_page
from providers import best_provider, get_provider, get_available_providers


RETRY_DELAYS = [120, 300, 900]  # 2min, 5min, 15min


def submit_fax(to_number: str, file_path: str, to_name: str = "",
               from_number: str = "", from_name: str = "",
               from_email: str = "", cover_message: str = "",
               provider_name: str = None) -> dict:
    """Submit a fax for delivery. Returns fax record."""

    from_number = from_number or config.FROM_NUMBER
    from_name = from_name or config.FROM_NAME
    from_email = from_email or config.FROM_EMAIL

    # Select provider
    if provider_name:
        provider = get_provider(provider_name)
        if not provider or not provider.is_available():
            return {"error": f"Provider '{provider_name}' is not available"}
    else:
        provider = best_provider(to_number)
        if not provider:
            return {"error": "No fax providers available. Configure at least one in .env"}

    # Convert document to fax-ready TIFF
    try:
        tiff_path = to_tiff(file_path)
    except Exception as e:
        return {"error": f"Document conversion failed: {e}"}

    # Generate cover page if message provided
    if cover_message:
        try:
            generate_cover_page(to_name, to_number, from_name, from_number, cover_message)
        except Exception:
            pass  # cover page is optional, continue without it

    # Create database record
    fax = db.create_fax(
        to_number=to_number, to_name=to_name,
        from_number=from_number, from_name=from_name,
        from_email=from_email, file_path=file_path,
        cover_message=cover_message, provider=provider.name
    )

    # Update with TIFF path
    db.update_fax(fax["id"], tiff_path=tiff_path, status="sending")

    # Attempt delivery
    result = provider.send(
        tiff_path=tiff_path,
        to_number=to_number,
        from_number=from_number,
        from_name=from_name,
        from_email=from_email,
        cover_message=cover_message
    )

    if result["success"]:
        db.update_fax(fax["id"],
                      status="sent",
                      provider_fax_id=result.get("provider_fax_id", ""))
        db.audit("fax_sent", "fax", fax["id"],
                 f"provider={provider.name} to={to_number}")
    else:
        # Schedule retry or mark failed
        retry_count = 0
        if retry_count < len(RETRY_DELAYS):
            next_retry = (datetime.utcnow() +
                          timedelta(seconds=RETRY_DELAYS[retry_count])).isoformat()
            db.update_fax(fax["id"],
                          status="retry_pending",
                          error_message=result["message"],
                          retry_count=1,
                          next_retry_at=next_retry)
        else:
            db.update_fax(fax["id"],
                          status="failed",
                          error_message=result["message"])

    return db.get_fax(fax["id"])


def process_retries():
    """Process any faxes waiting for retry. Call periodically."""
    now = datetime.utcnow().isoformat()
    faxes = db.list_faxes(status="retry_pending", limit=20)

    for fax in faxes:
        if not fax["next_retry_at"] or fax["next_retry_at"] > now:
            continue

        provider = get_provider(fax["provider"])
        if not provider or not provider.is_available():
            # Try another provider
            provider = best_provider(fax["to_number"])
            if not provider:
                continue

        tiff_path = fax.get("tiff_path") or fax.get("file_path", "")
        if not tiff_path:
            db.update_fax(fax["id"], status="failed",
                          error_message="No document file found for retry")
            continue

        db.update_fax(fax["id"], status="sending", provider=provider.name)

        result = provider.send(
            tiff_path=tiff_path,
            to_number=fax["to_number"],
            from_number=fax["from_number"],
            from_name=fax["from_name"],
            from_email=fax["from_email"],
            cover_message=fax["cover_message"]
        )

        if result["success"]:
            db.update_fax(fax["id"],
                          status="sent",
                          provider_fax_id=result.get("provider_fax_id", ""))
            db.audit("fax_retry_success", "fax", fax["id"],
                     f"provider={provider.name} attempt={fax['retry_count']+1}")
        else:
            retry_count = fax["retry_count"]
            if retry_count < len(RETRY_DELAYS):
                next_retry = (datetime.utcnow() +
                              timedelta(seconds=RETRY_DELAYS[retry_count])).isoformat()
                db.update_fax(fax["id"],
                              status="retry_pending",
                              error_message=result["message"],
                              retry_count=retry_count + 1,
                              next_retry_at=next_retry)
            else:
                db.update_fax(fax["id"],
                              status="failed",
                              error_message=result["message"])
                db.audit("fax_failed", "fax", fax["id"],
                         f"final failure after {retry_count+1} attempts")


def get_system_status() -> dict:
    """Return system status: available providers, usage, queue."""
    from providers import ALL_PROVIDERS
    providers_status = []
    for p in ALL_PROVIDERS:
        providers_status.append({
            "name": p.name,
            "available": p.is_available(),
            "daily_limit": p.daily_limit,
            "remaining_today": p.remaining_today() if p.is_available() else 0,
        })

    faxes = db.list_faxes(limit=100)
    stats = {"total": len(faxes), "sent": 0, "failed": 0, "queued": 0, "retry": 0}
    for f in faxes:
        if f["status"] in ("sent", "delivered"):
            stats["sent"] += 1
        elif f["status"] == "failed":
            stats["failed"] += 1
        elif f["status"] in ("queued", "sending"):
            stats["queued"] += 1
        elif f["status"] == "retry_pending":
            stats["retry"] += 1

    return {
        "providers": providers_status,
        "stats": stats,
        "usage_today": db.get_usage_today(),
    }
