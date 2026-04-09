"""
Slack notification service.
Sends lead notifications to #fleet-sales-bot when order info is collected.
"""
import os
import logging
import httpx
from typing import Dict, Optional
from google.cloud import secretmanager

logger = logging.getLogger(__name__)

SLACK_SECRET_NAME = "fleet-sales-agent-slack-webhook"


class SlackService:
    """Sends Slack notifications to #fleet-sales-bot."""

    def __init__(self):
        self._webhook_url: Optional[str] = None

    def _get_webhook_url(self) -> Optional[str]:
        """Get Slack webhook URL from Secret Manager (cached)."""
        if self._webhook_url:
            return self._webhook_url

        # Try Secret Manager first
        try:
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "nexar-corp-systems")
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{SLACK_SECRET_NAME}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            self._webhook_url = response.payload.data.decode("UTF-8").strip()
            logger.info("Slack webhook loaded from Secret Manager")
            return self._webhook_url
        except Exception as e:
            logger.warning(f"Secret Manager unavailable: {e}")

        # Fallback to env var (for local dev)
        url = os.environ.get("SLACK_WEBHOOK_URL")
        if url:
            self._webhook_url = url
            logger.info("Slack webhook loaded from env var")
        return url

    async def notify_new_lead(self, session_id: str, lead: Dict) -> bool:
        """
        Send a new lead notification to #fleet-sales-bot.
        Triggered when a customer completes the order info collection.
        """
        webhook_url = self._get_webhook_url()
        if not webhook_url:
            logger.warning("No Slack webhook configured - skipping notification")
            return False

        # Build Slack message blocks
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚗 New Fleet Sales Lead",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Business:*\n{lead.get('business_name', 'Not provided')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Fleet Size:*\n{lead.get('fleet_size', 'Not provided')} vehicles"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Contact:*\n{lead.get('contact_name', 'Not provided')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Phone:*\n{lead.get('contact_phone', 'Not provided')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Email:*\n{lead.get('contact_email', 'Not provided')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Cameras Needed:*\n{lead.get('num_cameras', 'Not provided')}"
                    }
                ]
            }
        ]

        # Add camera model / memory / subscription plan if collected
        if lead.get("subscription_plan") or lead.get("camera_model"):
            fields = []
            if lead.get("camera_model"):
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*Camera Model:*\n{lead.get('camera_model')}"
                })
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*Memory:*\n{lead.get('memory_option', 'Not specified')}"
                })
            if lead.get("subscription_plan"):
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*Plan:*\n{lead.get('subscription_plan')}"
                })
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*Billing Email:*\n{lead.get('billing_email', lead.get('contact_email', 'Not provided'))}"
                })
            if fields:
                blocks.append({"type": "section", "fields": fields})

        # Add shipping address if collected
        if lead.get("shipping_address"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Shipping Address:*\n{lead.get('shipping_address')}"
                }
            })

        # Add pain points / CTA intent
        if lead.get("pain_points") or lead.get("cta_type"):
            blocks.append({
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Pain Points:*\n{lead.get('pain_points', 'Not captured')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Intent Signal:*\n{lead.get('cta_type', 'Unknown').upper()}"
                    }
                ]
            })

        # Add "Review & Sign Quote" button when DocuSign URL is available
        if lead.get("quote_url"):
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Review & Sign Quote", "emoji": True},
                        "url": lead["quote_url"],
                        "style": "primary",
                    }
                ]
            })

        # Add session link for Firestore
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Session ID: `{session_id}` | View full conversation in Firestore > fleet_conversations"
                }
            ]
        })

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json={"blocks": blocks},
                    timeout=10.0
                )
                if response.status_code == 200:
                    logger.info(f"Slack notification sent for session {session_id}")
                    return True
                else:
                    logger.error(f"Slack webhook returned {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

    async def notify_high_intent_lead(self, session_id: str, lead: Dict) -> bool:
        """
        Send urgent notification for high-intent leads (large fleet + clear pain points).
        """
        webhook_url = self._get_webhook_url()
        if not webhook_url:
            return False

        fleet_size = lead.get("fleet_size", 0) or 0
        message = {
            "text": f"🔥 *High-Intent Lead Alert!* Fleet of {fleet_size} vehicles - {lead.get('contact_name', 'Unknown')} from {lead.get('business_name', 'Unknown')}. Session: `{session_id}`",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"🔥 *High-Intent Lead!*\n*{lead.get('business_name', 'Unknown')}* - {fleet_size} vehicles\nContact: {lead.get('contact_name')} | {lead.get('contact_phone')} | {lead.get('contact_email')}\nSession: `{session_id}`"
                    }
                }
            ]
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(webhook_url, json=message, timeout=10.0)
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send high-intent Slack notification: {e}")
            return False
