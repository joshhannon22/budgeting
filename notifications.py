"""
Notification system for budget reports using Pushover API.
Sends report summaries to devices.
"""

import os
import requests
from typing import Optional


class Notifier:
    """Handles sending notifications via Pushover API."""

    def __init__(self):
        """Initialize Notifier with API credentials from environment variables."""
        self.app_token = os.environ.get("PUSHOVER_APP_TOKEN")
        self.user_key = os.environ.get("PUSHOVER_USER_KEY")
        self.enabled = self.app_token and self.user_key

    def is_enabled(self) -> bool:
        """Check if notification system is properly configured."""
        return self.enabled

    def send(self, message: str, title: Optional[str] = None) -> bool:
        """
        Send a notification via Pushover.

        Args:
            message: The notification message body
            title: Optional title for the notification

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            return False

        try:
            payload = {
                "token": self.app_token,
                "user": self.user_key,
                "message": message,
            }

            if title:
                payload["title"] = title

            response = requests.post(
                "https://api.pushover.net/1/messages.json",
                data=payload,
                timeout=10
            )

            success = response.status_code == 200
            if success:
                print("✓ Notification sent via Pushover")
            else:
                print(f"⚠ Pushover notification failed (status {response.status_code})")

            return success

        except Exception as e:
            print(f"⚠ Error sending Pushover notification: {e}")
            return False


def build_tldr_prompt(report_type: str, data_summary: str) -> str:
    """
    Build a prompt for Claude to generate a TLDR summary.

    Args:
        report_type: "weekly" or "monthly"
        data_summary: The structured data summary to analyze

    Returns:
        Prompt string for Claude
    """
    return f"""Given the following {report_type} spending report data, write a VERY BRIEF 2-3 sentence TL;DR summary.

Focus on:
1. The key metric (on pace/over/under budget)
2. The biggest spending category
3. One actionable takeaway

Keep it punchy and actionable. This will be sent as a push notification, so keep it under 200 characters.

---

{data_summary}
"""
