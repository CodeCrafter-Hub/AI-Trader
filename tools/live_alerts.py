import json
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def _alert_log_path() -> Path:
    base_dir = Path(__file__).resolve().parents[1]
    return base_dir / "data" / "live_alerts.jsonl"


def _write_alert_log(entry: Dict[str, Any]) -> None:
    path = _alert_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _send_webhook(message: str, details: Dict[str, Any]) -> Optional[str]:
    url = os.getenv("ALERT_WEBHOOK_URL")
    if not url:
        return None
    try:
        response = requests.post(url, json={"message": message, "details": details}, timeout=10)
        if not response.ok:
            return f"Webhook error {response.status_code}: {response.text}"
        return None
    except Exception as exc:
        return f"Webhook exception: {exc}"


def _send_email(subject: str, body: str) -> Optional[str]:
    host = os.getenv("ALERT_SMTP_HOST")
    port = int(os.getenv("ALERT_SMTP_PORT", "587"))
    user = os.getenv("ALERT_SMTP_USER")
    password = os.getenv("ALERT_SMTP_PASS")
    to_addr = os.getenv("ALERT_EMAIL_TO")
    from_addr = os.getenv("ALERT_EMAIL_FROM")
    use_tls = os.getenv("ALERT_SMTP_TLS", "true").lower() == "true"

    if not host or not to_addr or not from_addr:
        return None

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            if use_tls:
                server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return None
    except Exception as exc:
        return f"Email exception: {exc}"


def notify_alert(event: str, details: Dict[str, Any]) -> None:
    timestamp = datetime.utcnow().isoformat()
    entry = {
        "timestamp": timestamp,
        "event": event,
        "details": details,
    }
    _write_alert_log(entry)

    message = f"[AI-Trader Alert] {event}"
    webhook_error = _send_webhook(message, details)
    email_error = _send_email(message, json.dumps(details, ensure_ascii=False, indent=2))

    if webhook_error or email_error:
        _write_alert_log(
            {
                "timestamp": timestamp,
                "event": "alert_delivery_error",
                "details": {
                    "webhook_error": webhook_error,
                    "email_error": email_error,
                },
            }
        )
