"""Optional Telegram notifications for human review requests."""

import logging
from typing import Optional
import httpx
from qr_form_agent.config import settings

logger = logging.getLogger(__name__)


def notify_job_awaiting_approval(job_id: str, target_url: str, review_url: str) -> bool:
    """
    Sends a notification via Telegram bot when a job enters AWAITING_APPROVAL.
    Only executes if telegram_bot_token and telegram_chat_id are configured.
    """
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id

    if not token or not chat_id:
        logger.debug("Telegram credentials not configured; skipping notification.")
        return False

    message = (
        f"📋 *Form Ready for Human Review*\n\n"
        f"• *Job ID:* `{job_id}`\n"
        f"• *Target:* {target_url}\n"
        f"• *Review Link:* [Open Review Dashboard]({review_url})\n\n"
        f"Submission is strictly blocked until you explicitly approve this job."
    )

    api_endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(api_endpoint, json=payload)
            if resp.status_code == 200:
                logger.info("Successfully sent Telegram review notification for job %s", job_id)
                return True
            else:
                logger.warning("Telegram notification failed (status %s): %s", resp.status_code, resp.text)
                return False
    except Exception as e:
        logger.warning("Failed to send Telegram notification: %s", e)
        return False
