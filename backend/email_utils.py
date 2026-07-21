"""
email_utils.py — AWS SES email delivery for the admin forgot-password flow.

SES requires domain/sender verification done in the AWS console before it
can actually send mail in production — that setup happens outside this
repo. Until SES_FROM_EMAIL is configured, send_reset_email() no-ops (logs
a warning, returns False) rather than raising, so the rest of the
forgot-password flow — including the admin-generated reset-link fallback,
which needs no email infrastructure at all — keeps working regardless of
whether SES is set up yet.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("battery_finder.admin")

SES_FROM_EMAIL = os.environ.get("SES_FROM_EMAIL", "")
SES_REGION = os.environ.get("SES_REGION", "us-east-1")


def send_reset_email(to_email: str, reset_url: str) -> bool:
    """
    Best-effort SES send. Never raises — callers should treat a False
    return the same as a successful send from the caller's perspective
    (the forgot-password route must not leak whether delivery actually
    worked, only that a token exists to try to deliver).
    """
    if not SES_FROM_EMAIL:
        logger.warning("send_reset_email: SES_FROM_EMAIL not configured, skipping send to %s", to_email)
        return False

    try:
        import boto3

        client = boto3.client("ses", region_name=SES_REGION)
        client.send_email(
            Source=SES_FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": "Reset your Battery Finder admin password"},
                "Body": {
                    "Text": {
                        "Data": (
                            "A password reset was requested for your Battery Finder "
                            "admin account.\n\n"
                            f"Reset your password: {reset_url}\n\n"
                            "This link expires in 1 hour. If you didn't request this, "
                            "you can safely ignore this email."
                        )
                    }
                },
            },
        )
        return True
    except Exception:
        logger.exception("send_reset_email: SES send failed for %s", to_email)
        return False
