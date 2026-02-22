"""
integrations.email.mailbox
~~~~~~~~~~~~~~~~~~~~~~~~~~~

SMTP-based email notifications for the OpenClaw system.

Provides :class:`MailboxManager` which sends system alerts, periodic
reports, and operational notifications via SMTP.  Designed for internal
system communications (e.g. deployment failures, commission summaries,
health-check alerts) rather than bulk marketing email.

Design references:
    - config/providers.yaml  ``email`` section
    - ARCHITECTURE.md  Section 4 (Integration Layer)

Usage::

    from src.integrations.email.mailbox import MailboxManager

    mailer = MailboxManager(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="alerts@openclaw.example",
        password="app-password",
        from_address="alerts@openclaw.example",
    )
    await mailer.send_alert(
        to="ops@openclaw.example",
        subject="Deployment failed",
        body="Site xyz failed to deploy. See logs for details.",
    )
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

from src.core.errors import IntegrationError
from src.core.logger import get_logger, log_event

logger = get_logger("integrations.email.mailbox")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_SMTP_PORT = 587
_DEFAULT_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class EmailMessage:
    """Structured representation of an outgoing email.

    Attributes
    ----------
    to:
        Recipient email addresses.
    subject:
        Email subject line.
    body_text:
        Plain-text body content.
    body_html:
        Optional HTML body content.
    from_address:
        Sender email address.
    cc:
        CC recipient addresses.
    bcc:
        BCC recipient addresses.
    reply_to:
        Reply-to address.
    headers:
        Additional email headers.
    sent_at:
        UTC timestamp when the email was sent (set after sending).
    message_id:
        SMTP message ID (set after sending).
    """

    to: List[str]
    subject: str
    body_text: str
    body_html: str = ""
    from_address: str = ""
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    reply_to: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    sent_at: Optional[datetime] = None
    message_id: str = ""


@dataclass
class SendResult:
    """Result of an email send operation.

    Attributes
    ----------
    success:
        Whether the email was accepted by the SMTP server.
    message_id:
        SMTP message ID (if available).
    recipients_accepted:
        List of recipients the server accepted.
    recipients_rejected:
        Dict of rejected recipients and their error messages.
    error:
        Error description if the send failed.
    sent_at:
        UTC timestamp when the send was attempted.
    """

    success: bool = False
    message_id: str = ""
    recipients_accepted: List[str] = field(default_factory=list)
    recipients_rejected: Dict[str, str] = field(default_factory=dict)
    error: str = ""
    sent_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# MailboxManager
# ---------------------------------------------------------------------------

class MailboxManager:
    """SMTP email client for OpenClaw system notifications.

    Supports TLS/STARTTLS connections and sends plain-text and HTML
    multipart messages.  Connection pooling is not implemented; a new
    SMTP session is opened for each send operation to keep the design
    simple and robust for low-volume notification traffic.

    Parameters
    ----------
    smtp_host:
        SMTP server hostname.
    smtp_port:
        SMTP server port (587 for STARTTLS, 465 for implicit TLS).
    username:
        SMTP authentication username.
    password:
        SMTP authentication password or app-specific password.
    from_address:
        Default sender address for all outgoing messages.
    use_tls:
        Whether to use STARTTLS (port 587) or implicit TLS (port 465).
        Defaults to ``True`` (STARTTLS).
    timeout:
        Connection timeout in seconds.
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int = _DEFAULT_SMTP_PORT,
        username: str = "",
        password: str = "",
        from_address: str = "",
        use_tls: bool = True,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        if not smtp_host:
            raise IntegrationError("SMTP host is required for email integration")
        if not from_address:
            raise IntegrationError("from_address is required for email integration")

        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._use_tls = use_tls
        self._timeout = timeout
        self._send_count: int = 0
        self._error_count: int = 0

        log_event(
            logger,
            "email.init",
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            from_address=from_address,
            use_tls=use_tls,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Construct a MIME multipart email from an :class:`EmailMessage`.

        Parameters
        ----------
        message:
            Structured email message.

        Returns
        -------
        MIMEMultipart
            Ready-to-send MIME message.
        """
        msg = MIMEMultipart("alternative")
        msg["From"] = message.from_address or self._from_address
        msg["To"] = ", ".join(message.to)
        msg["Subject"] = message.subject

        if message.cc:
            msg["Cc"] = ", ".join(message.cc)
        if message.reply_to:
            msg["Reply-To"] = message.reply_to

        # Custom headers
        for header_name, header_value in message.headers.items():
            msg[header_name] = header_value

        # Always attach plain text
        msg.attach(MIMEText(message.body_text, "plain", "utf-8"))

        # Optionally attach HTML
        if message.body_html:
            msg.attach(MIMEText(message.body_html, "html", "utf-8"))

        return msg

    def _send_via_smtp(self, mime_msg: MIMEMultipart, all_recipients: List[str]) -> SendResult:
        """Open an SMTP connection and send a MIME message.

        Parameters
        ----------
        mime_msg:
            Constructed MIME message.
        all_recipients:
            Complete list of recipients (to + cc + bcc).

        Returns
        -------
        SendResult
            Outcome of the send operation.
        """
        result = SendResult(sent_at=datetime.now(timezone.utc))
        context = ssl.create_default_context()

        try:
            if self._smtp_port == 465:
                # Implicit TLS
                server = smtplib.SMTP_SSL(
                    self._smtp_host,
                    self._smtp_port,
                    timeout=self._timeout,
                    context=context,
                )
            else:
                # STARTTLS
                server = smtplib.SMTP(
                    self._smtp_host,
                    self._smtp_port,
                    timeout=self._timeout,
                )
                server.ehlo()
                if self._use_tls:
                    server.starttls(context=context)
                    server.ehlo()

            # Authenticate if credentials are provided
            if self._username and self._password:
                server.login(self._username, self._password)

            # Send the message
            rejected = server.sendmail(
                from_addr=mime_msg["From"],
                to_addrs=all_recipients,
                msg=mime_msg.as_string(),
            )

            server.quit()

            # Determine accepted/rejected recipients
            rejected_addrs = set(rejected.keys()) if rejected else set()
            accepted_addrs = [r for r in all_recipients if r not in rejected_addrs]

            result.success = len(accepted_addrs) > 0
            result.recipients_accepted = accepted_addrs
            result.recipients_rejected = {
                addr: str(err) for addr, err in (rejected or {}).items()
            }
            result.message_id = mime_msg.get("Message-ID", "")

            self._send_count += 1

        except smtplib.SMTPAuthenticationError as exc:
            result.error = f"SMTP authentication failed: {exc}"
            self._error_count += 1
            logger.error("SMTP auth error: %s", exc)

        except smtplib.SMTPException as exc:
            result.error = f"SMTP error: {exc}"
            self._error_count += 1
            logger.error("SMTP error: %s", exc)

        except (ConnectionError, TimeoutError, OSError) as exc:
            result.error = f"Connection error: {exc}"
            self._error_count += 1
            logger.error("SMTP connection error: %s", exc)

        return result

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def send_alert(
        self,
        to: str | List[str],
        subject: str,
        body: str,
        *,
        severity: str = "warning",
        html_body: str = "",
    ) -> SendResult:
        """Send a system alert email.

        Alert emails are prefixed with a severity tag in the subject line
        and include a timestamp in the body for quick triage.

        Parameters
        ----------
        to:
            Recipient address or list of addresses.
        subject:
            Alert subject line.
        body:
            Plain-text alert body.
        severity:
            Alert severity level (``"info"``, ``"warning"``, ``"critical"``).
            Prepended to the subject as ``[SEVERITY]``.
        html_body:
            Optional HTML body.

        Returns
        -------
        SendResult
            Outcome of the send operation.
        """
        recipients = [to] if isinstance(to, str) else list(to)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        prefixed_subject = f"[{severity.upper()}] {subject}"
        enriched_body = (
            f"OpenClaw System Alert\n"
            f"Severity: {severity.upper()}\n"
            f"Time: {timestamp}\n"
            f"{'=' * 50}\n\n"
            f"{body}"
        )

        message = EmailMessage(
            to=recipients,
            subject=prefixed_subject,
            body_text=enriched_body,
            body_html=html_body,
            headers={"X-OpenClaw-Alert-Severity": severity.upper()},
        )

        log_event(
            logger,
            "email.send_alert",
            severity=severity,
            recipient_count=len(recipients),
            subject=prefixed_subject,
        )

        mime_msg = self._build_mime_message(message)
        return self._send_via_smtp(mime_msg, recipients)

    async def send_report(
        self,
        to: str | List[str],
        subject: str,
        body: str,
        *,
        report_type: str = "daily",
        html_body: str = "",
        cc: Optional[List[str]] = None,
    ) -> SendResult:
        """Send a periodic report email.

        Report emails include a report-type header and are formatted for
        readability with clear section breaks.

        Parameters
        ----------
        to:
            Recipient address or list of addresses.
        subject:
            Report subject line.
        body:
            Plain-text report body.
        report_type:
            Report classification (``"daily"``, ``"weekly"``, ``"monthly"``,
            ``"commission"``, ``"performance"``).
        html_body:
            Optional HTML body with formatted tables/charts.
        cc:
            Optional CC recipients.

        Returns
        -------
        SendResult
            Outcome of the send operation.
        """
        recipients = [to] if isinstance(to, str) else list(to)
        cc_list = cc or []
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        prefixed_subject = f"[Report: {report_type.title()}] {subject}"
        enriched_body = (
            f"OpenClaw {report_type.title()} Report\n"
            f"Generated: {timestamp}\n"
            f"{'=' * 50}\n\n"
            f"{body}\n\n"
            f"{'=' * 50}\n"
            f"This is an automated report from the OpenClaw system.\n"
        )

        message = EmailMessage(
            to=recipients,
            subject=prefixed_subject,
            body_text=enriched_body,
            body_html=html_body,
            cc=cc_list,
            headers={
                "X-OpenClaw-Report-Type": report_type,
            },
        )

        log_event(
            logger,
            "email.send_report",
            report_type=report_type,
            recipient_count=len(recipients),
            subject=prefixed_subject,
        )

        mime_msg = self._build_mime_message(message)
        all_recipients = recipients + cc_list
        return self._send_via_smtp(mime_msg, all_recipients)

    async def send_notification(
        self,
        to: str | List[str],
        subject: str,
        body: str,
        *,
        category: str = "system",
        html_body: str = "",
    ) -> SendResult:
        """Send a general system notification email.

        Notifications are less urgent than alerts and are used for
        informational messages like successful deployments, new offers
        discovered, or configuration changes.

        Parameters
        ----------
        to:
            Recipient address or list of addresses.
        subject:
            Notification subject line.
        body:
            Plain-text notification body.
        category:
            Notification category for filtering (``"system"``,
            ``"deployment"``, ``"offers"``, ``"content"``).
        html_body:
            Optional HTML body.

        Returns
        -------
        SendResult
            Outcome of the send operation.
        """
        recipients = [to] if isinstance(to, str) else list(to)

        message = EmailMessage(
            to=recipients,
            subject=f"[OpenClaw] {subject}",
            body_text=body,
            body_html=html_body,
            headers={
                "X-OpenClaw-Notification-Category": category,
            },
        )

        log_event(
            logger,
            "email.send_notification",
            category=category,
            recipient_count=len(recipients),
            subject=subject,
        )

        mime_msg = self._build_mime_message(message)
        return self._send_via_smtp(mime_msg, recipients)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def send_count(self) -> int:
        """Return the total number of successfully sent emails."""
        return self._send_count

    @property
    def error_count(self) -> int:
        """Return the total number of send failures."""
        return self._error_count

    def __repr__(self) -> str:
        return (
            f"MailboxManager(host={self._smtp_host!r}, "
            f"port={self._smtp_port}, "
            f"from={self._from_address!r}, "
            f"sent={self._send_count}, errors={self._error_count})"
        )
