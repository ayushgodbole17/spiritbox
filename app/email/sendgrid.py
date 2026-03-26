"""
SendGrid email wrapper for Spiritbox reminder emails.

Provides send_reminder_email() which is called by both the Cloud Function
and can be called directly during local development.
"""
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


async def send_reminder_email(
    to_email: str,
    subject: str,
    body_html: str,
    body_text: Optional[str] = None,
) -> bool:
    """
    Send a reminder email via SendGrid.

    Args:
        to_email:   Recipient email address.
        subject:    Email subject line.
        body_html:  HTML body of the email.
        body_text:  Plain-text fallback body (auto-generated from HTML if None).

    Returns:
        True if the email was sent (or logged in local dev), False on failure.
    """
    if not settings.SENDGRID_API_KEY:
        logger.info(
            "[LocalDev] Would send email via SendGrid:\n"
            f"  to     : {to_email}\n"
            f"  from   : {settings.REMINDER_FROM_EMAIL}\n"
            f"  subject: {subject}\n"
            f"  body   : {body_text or body_html[:200]}"
        )
        return True

    try:
        from sendgrid import SendGridAPIClient  # type: ignore
        from sendgrid.helpers.mail import Mail, Content, MimeType  # type: ignore

        message = Mail(
            from_email=settings.REMINDER_FROM_EMAIL,
            to_emails=to_email,
            subject=subject,
        )
        message.add_content(Content(MimeType.html, body_html))
        if body_text:
            message.add_content(Content(MimeType.text, body_text))

        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)

        if response.status_code in (200, 202):
            logger.info(f"Email sent to {to_email} (status={response.status_code})")
            return True
        else:
            logger.error(
                f"SendGrid returned unexpected status {response.status_code}: {response.body}"
            )
            return False

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}", exc_info=True)
        return False


def build_reminder_html(description: str, event_time: str, user_timezone: str) -> str:
    """
    Build a simple HTML reminder email body.

    Args:
        description:   Human-readable event description.
        event_time:    Formatted event time string.
        user_timezone: User's local timezone string.

    Returns:
        HTML string.
    """
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 24px;">
  <h2 style="color: #4F46E5;">Spiritbox Reminder</h2>
  <p>You have an upcoming event:</p>
  <div style="background: #F3F4F6; border-radius: 8px; padding: 16px; margin: 16px 0;">
    <strong>{description}</strong><br/>
    <span style="color: #6B7280;">{event_time} ({user_timezone})</span>
  </div>
  <p style="color: #9CA3AF; font-size: 12px;">
    Sent by <a href="https://spiritbox.app">Spiritbox</a>.
    To manage your reminders, open the Spiritbox app.
  </p>
</body>
</html>
""".strip()
