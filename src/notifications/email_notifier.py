"""SMTP email notifications for job alerts and application status."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog
from jinja2 import Environment, FileSystemLoader

from src.config import AppConfig
from src.models import Job

log = structlog.get_logger()


class EmailNotifier:
    def __init__(self, config: AppConfig, template_dir: str = "templates"):
        self.config = config
        self.env = Environment(loader=FileSystemLoader(template_dir))

    def notify_new_matches(self, jobs: list[Job]) -> None:
        """Send email about new matching jobs found."""
        if not jobs:
            return

        template = self.env.get_template("email_new_jobs.html.j2")
        html = template.render(jobs=jobs, count=len(jobs))
        self._send(
            subject=f"[Job Alert] {len(jobs)} new matching ML/AI jobs found",
            html_body=html,
        )

    def notify_applications(
        self,
        applied: list[dict],
        failed: list[dict],
    ) -> None:
        """Send email summarizing application results."""
        if not applied and not failed:
            return

        template = self.env.get_template("email_applied.html.j2")
        html = template.render(
            applied=applied,
            failed=failed,
            applied_count=len(applied),
            failed_count=len(failed),
        )
        self._send(
            subject=f"[Job Alert] {len(applied)} applied, {len(failed)} failed",
            html_body=html,
        )

    def notify_error(self, error_message: str, context: str = "") -> None:
        """Send email about a pipeline error."""
        template = self.env.get_template("email_error.html.j2")
        html = template.render(error=error_message, context=context)
        self._send(
            subject="[Job Alert] Pipeline Error",
            html_body=html,
        )

    def _send(self, subject: str, html_body: str) -> None:
        """Send an email via SMTP."""
        if not all([
            self.config.smtp_host,
            self.config.smtp_user,
            self.config.notification.email_to,
        ]):
            log.warning("email_not_configured", subject=subject)
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.notification.email_from or self.config.smtp_user
        msg["To"] = self.config.notification.email_to
        msg.attach(MIMEText(html_body, "html"))

        try:
            # Gmail app passwords are valid with or without spaces
            password = self.config.smtp_password.replace(" ", "")
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                server.starttls()
                server.login(self.config.smtp_user, password)
                server.send_message(msg)
            log.info("email_sent", subject=subject, to=self.config.notification.email_to)
        except Exception as e:
            log.error("email_send_error", error=str(e), subject=subject)
