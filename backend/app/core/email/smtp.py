import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote

from app.config import get_settings


class EmailDeliveryNotConfiguredError(Exception):
    pass


class EmailDeliveryError(Exception):
    pass


def ensure_email_delivery_configured() -> None:
    if not get_settings().email_delivery_configured:
        raise EmailDeliveryNotConfiguredError


def send_verification_email(*, recipient: str, raw_token: str) -> None:
    settings = get_settings()
    ensure_email_delivery_configured()
    assert settings.smtp_host is not None
    assert settings.email_from is not None
    assert settings.frontend_base_url is not None

    verification_url = (
        f"{str(settings.frontend_base_url).rstrip('/')}/verify-email"
        f"#token={quote(raw_token, safe='')}"
    )
    message = EmailMessage()
    message["Subject"] = "Verify your Auron email"
    message["From"] = str(settings.email_from)
    message["To"] = recipient
    message.set_content(
        "Someone requested Auron account access for this email.\n\n"
        "Finish setup and choose your password using this link:\n"
        f"{verification_url}\n\n"
        f"This link expires in {settings.email_verification_ttl_hours} hours. "
        "If you did not request it, you can ignore this email."
    )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
            if settings.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                password = (
                    settings.smtp_password.get_secret_value()
                    if settings.smtp_password is not None
                    else ""
                )
                client.login(settings.smtp_username, password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError from error
