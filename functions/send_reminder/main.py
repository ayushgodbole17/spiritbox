"""
GCP Cloud Function: send_reminder

Triggered by Cloud Scheduler via HTTP POST.

Expected request body (JSON):
    {
        "event_id":    "<Firestore document ID>",
        "description": "<event description>",
        "event_time":  "<ISO 8601 datetime string>",
        "user_email":  "<recipient email>"
    }

On success:
    - Sends a reminder email via SendGrid.
    - Marks the Firestore event document as reminded=True.
    - Returns HTTP 200.

On failure:
    - Returns HTTP 500 with an error message (does NOT mark as reminded).
"""
import json
import logging
import os
import functions_framework  # type: ignore
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@functions_framework.http
def send_reminder(request):
    """Cloud Function entry point."""
    # Parse request body
    try:
        data = request.get_json(force=True) or {}
    except Exception as e:
        logger.error(f"Failed to parse request JSON: {e}")
        return ("Bad Request: invalid JSON", 400)

    event_id = data.get("event_id")
    description = data.get("description", "Upcoming event")
    event_time_str = data.get("event_time", "")
    user_email = data.get("user_email") or os.environ.get("USER_EMAIL", "")

    if not event_id:
        return ("Bad Request: event_id is required", 400)
    if not user_email:
        return ("Bad Request: user_email is required", 400)

    logger.info(f"Processing reminder for event_id={event_id}, to={user_email}")

    # Build email content
    from_email = os.environ.get("REMINDER_FROM_EMAIL", "noreply@spiritbox.app")
    user_tz = os.environ.get("USER_TIMEZONE", "Asia/Kolkata")

    body_html = _build_html(description, event_time_str, user_tz)
    body_text = f"Spiritbox Reminder\n\n{description}\n{event_time_str} ({user_tz})"
    subject = f"Reminder: {description}"

    # Send email
    success = _send_email(
        api_key=os.environ.get("SENDGRID_API_KEY", ""),
        from_email=from_email,
        to_email=user_email,
        subject=subject,
        body_html=body_html,
        body_text=body_text,
    )

    if not success:
        logger.error(f"Email send failed for event_id={event_id}")
        return ("Internal Server Error: email send failed", 500)

    # Mark reminded in Firestore
    try:
        _mark_reminded(event_id)
    except Exception as e:
        logger.error(f"Failed to mark event {event_id} as reminded: {e}")
        # Non-fatal — email was sent; Firestore update can be retried.

    return (json.dumps({"status": "ok", "event_id": event_id}), 200, {"Content-Type": "application/json"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_email(api_key, from_email, to_email, subject, body_html, body_text):
    if not api_key:
        logger.info(f"[LocalDev] Would send email to {to_email}: {subject}")
        return True
    try:
        from sendgrid import SendGridAPIClient  # type: ignore
        from sendgrid.helpers.mail import Mail, Content, MimeType  # type: ignore

        message = Mail(from_email=from_email, to_emails=to_email, subject=subject)
        message.add_content(Content(MimeType.html, body_html))
        message.add_content(Content(MimeType.text, body_text))

        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        return response.status_code in (200, 202)
    except Exception as e:
        logger.error(f"SendGrid error: {e}")
        return False


def _mark_reminded(event_id):
    from google.cloud import firestore  # type: ignore
    collection = os.environ.get("FIRESTORE_COLLECTION_EVENTS", "events")
    db = firestore.Client()
    db.collection(collection).document(event_id).update({"reminded": True})
    logger.info(f"Marked event {event_id} as reminded in Firestore.")


def _build_html(description, event_time, user_tz):
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;">
  <h2 style="color:#4F46E5;">Spiritbox Reminder</h2>
  <p>You have an upcoming event:</p>
  <div style="background:#F3F4F6;border-radius:8px;padding:16px;margin:16px 0;">
    <strong>{description}</strong><br/>
    <span style="color:#6B7280;">{event_time} ({user_tz})</span>
  </div>
  <p style="color:#9CA3AF;font-size:12px;">Sent by Spiritbox.</p>
</body>
</html>
""".strip()
