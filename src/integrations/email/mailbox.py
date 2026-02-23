"""
integrations.email.mailbox
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Email notification and reporting integration for the OpenClaw system.

Provides the :class:`MailboxManager` class for sending alert emails,
periodic performance reports, and general notifications.  Supports SMTP
delivery with TLS, HTML/plain-text multipart messages, and template-based
content rendering.

Design references:
    - ARCHITECTURE.md  Section 4 (Integration Layer)
    - config/providers.yaml  ``email`` section
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

from src.core.constants import DEFAULT_REQUEST_TIMEOUT
from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.email.mailbox")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class EmailMessage:
    """An email message ready for delivery.

    Attributes
    ----------
    to:
        List of recipient email addresses.
    subject:
        Email subject line.
    body_text:
        Plain-text body content.
    body_html:
        HTML body content (optional; if provided, the email is sent
        as multipart/alternative).
    cc:
        Carbon-copy recipients.
    bcc:
        Blind carbon-copy recipients.
    reply_to:
        Reply-to address.
    headers:
        Additional custom email headers.
    sent_at:
        UTC timestamp when the message was sent (populated after delivery).
    message_id:
        SMTP message ID (populated after delivery).
    """

    to: List[str] = field(default_factory=list)
    subject: str = ""
    body_text: str = ""
    body_html: str = ""
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    reply_to: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    sent_at: Optional[datetime] = None
    message_id: str = ""


@dataclass
class DeliveryResult:
    """Result of an email delivery attempt.

    Attributes
    ----------
    success:
        Whether the delivery was accepted by the SMTP server.
    message_id:
        SMTP message ID.
    recipients_accepted:
        Number of recipients the server accepted.
    recipients_rejected:
        Number of recipients the server rejected.
    error:
        Error message if delivery failed.
    sent_at:
        UTC timestamp of the delivery attempt.
    """

    success: bool = False
    message_id: str = ""
    recipients_accepted: int = 0
    recipients_rejected: int = 0
    error: str = ""
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# MailboxManager
# ---------------------------------------------------------------------------


class MailboxManager:
    """Manages email delivery for alerts, reports, and notifications.

    Connects to an SMTP server with TLS and sends multipart emails.
    Supports different message types (alerts, reports, notifications)
    with appropriate formatting.

    Parameters
    ----------
    smtp_host:
        SMTP server hostname.
    smtp_port:
        SMTP server port (typically 587 for STARTTLS, 465 for SMTPS).
    username:
        SMTP authentication username.
    password:
        SMTP authentication password.
    from_address:
        Default sender address.
    from_name:
        Default sender display name.
    use_tls:
        Whether to use STARTTLS (default ``True``).
    timeout:
        SMTP connection timeout in seconds.

    Raises
    ------
    IntegrationError
        If required parameters are missing.
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        from_address: str = "",
        from_name: str = "OpenClaw System",
        use_tls: bool = True,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        if not smtp_host:
            raise IntegrationError("smtp_host is required for MailboxManager")
        if not from_address:
            raise IntegrationError("from_address is required for MailboxManager")

        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._from_name = from_name
        self._use_tls = use_tls
        self._timeout = timeout
        self._send_count: int = 0
        self.logger: logging.Logger = get_logger("integrations.email.mailbox")

        log_event(
            logger,
            "mailbox.init",
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            from_address=from_address,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_mime(self, message: EmailMessage) -> MIMEMultipart:
        """Build a MIME message from an EmailMessage.

        Parameters
        ----------
        message:
            The email message to convert.

        Returns
        -------
        MIMEMultipart
            A MIME-formatted email ready for SMTP delivery.
        """
        mime = MIMEMultipart("alternative")
        mime["From"] = f"{self._from_name} <{self._from_address}>"
        mime["To"] = ", ".join(message.to)
        mime["Subject"] = message.subject

        if message.cc:
            mime["Cc"] = ", ".join(message.cc)
        if message.reply_to:
            mime["Reply-To"] = message.reply_to

        for key, value in message.headers.items():
            mime[key] = value

        # Attach plain-text body
        if message.body_text:
            mime.attach(MIMEText(message.body_text, "plain", "utf-8"))

        # Attach HTML body
        if message.body_html:
            mime.attach(MIMEText(message.body_html, "html", "utf-8"))

        return mime

    def _deliver(self, message: EmailMessage) -> DeliveryResult:
        """Send an email via SMTP.

        Parameters
        ----------
        message:
            The message to deliver.

        Returns
        -------
        DeliveryResult
            Delivery status and metadata.
        """
        all_recipients = message.to + message.cc + message.bcc
        if not all_recipients:
            return DeliveryResult(success=False, error="No recipients specified")

        mime = self._build_mime(message)

        try:
            server: smtplib.SMTP | smtplib.SMTP_SSL
            if self._smtp_port == 465:
                # Direct SSL connection
                server = smtplib.SMTP_SSL(
                    self._smtp_host, self._smtp_port, timeout=self._timeout
                )
            else:
                server = smtplib.SMTP(
                    self._smtp_host, self._smtp_port, timeout=self._timeout
                )
                if self._use_tls:
                    server.starttls()

            if self._username and self._password:
                server.login(self._username, self._password)

            rejected = server.sendmail(
                self._from_address,
                all_recipients,
                mime.as_string(),
            )
            server.quit()

            self._send_count += 1
            message.sent_at = datetime.now(timezone.utc)

            return DeliveryResult(
                success=True,
                recipients_accepted=len(all_recipients) - len(rejected),
                recipients_rejected=len(rejected),
                sent_at=message.sent_at,
            )

        except Exception as exc:
            self.logger.error("Email delivery failed: %s", str(exc), exc_info=True)
            return DeliveryResult(
                success=False,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_alert(
        self,
        recipients: List[str],
        subject: str,
        alert_message: str,
        *,
        severity: str = "warning",
        site_id: str = "",
    ) -> DeliveryResult:
        """Send an alert notification email.

        Parameters
        ----------
        recipients:
            Email addresses to send the alert to.
        subject:
            Alert subject line.
        alert_message:
            Alert body text describing the issue.
        severity:
            Alert severity level (``"info"``, ``"warning"``, ``"critical"``).
        site_id:
            Identifier of the affected site (if applicable).

        Returns
        -------
        DeliveryResult
            Delivery status.
        """
        severity_emoji = {
            "info": "[INFO]",
            "warning": "[WARNING]",
            "critical": "[CRITICAL]",
        }
        prefix = severity_emoji.get(severity, "[ALERT]")

        body_text = (
            f"{prefix} Alert for {site_id or 'system'}\n\n"
            f"{alert_message}\n\n"
            f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"Severity: {severity}\n"
        )

        body_html = (
            f"<h2>{prefix} Alert</h2>"
            f"<p><strong>Site:</strong> {site_id or 'system'}</p>"
            f"<p><strong>Severity:</strong> {severity}</p>"
            f"<p>{alert_message}</p>"
            f"<p><em>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</em></p>"
        )

        message = EmailMessage(
            to=recipients,
            subject=f"{prefix} {subject}",
            body_text=body_text,
            body_html=body_html,
        )

        log_event(
            logger,
            "mailbox.send_alert",
            recipients=len(recipients),
            severity=severity,
            site_id=site_id,
        )

        return self._deliver(message)

    def send_report(
        self,
        recipients: List[str],
        subject: str,
        report_html: str,
        *,
        report_text: str = "",
        period: str = "daily",
    ) -> DeliveryResult:
        """Send a performance report email.

        Parameters
        ----------
        recipients:
            Email addresses to send the report to.
        subject:
            Report subject line.
        report_html:
            HTML-formatted report body.
        report_text:
            Plain-text fallback of the report.
        period:
            Report period label for logging.

        Returns
        -------
        DeliveryResult
            Delivery status.
        """
        message = EmailMessage(
            to=recipients,
            subject=subject,
            body_text=report_text
            or "Please view this report in an HTML-capable email client.",
            body_html=report_html,
        )

        log_event(
            logger,
            "mailbox.send_report",
            recipients=len(recipients),
            period=period,
        )

        return self._deliver(message)

    def send_notification(
        self,
        recipients: List[str],
        subject: str,
        body: str,
        *,
        body_html: str = "",
    ) -> DeliveryResult:
        """Send a general notification email.

        Parameters
        ----------
        recipients:
            Email addresses to send to.
        subject:
            Email subject line.
        body:
            Plain-text message body.
        body_html:
            Optional HTML version of the body.

        Returns
        -------
        DeliveryResult
            Delivery status.
        """
        message = EmailMessage(
            to=recipients,
            subject=subject,
            body_text=body,
            body_html=body_html,
        )

        log_event(
            logger,
            "mailbox.send_notification",
            recipients=len(recipients),
        )

        return self._deliver(message)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def send_count(self) -> int:
        """Return the total number of emails successfully sent."""
        return self._send_count

    def __repr__(self) -> str:
        return (
            f"MailboxManager(host={self._smtp_host!r}, "
            f"port={self._smtp_port}, sent={self._send_count})"
        )
