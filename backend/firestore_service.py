"""
Firestore service - stores conversations, leads, and feedback.
Collections:
  - fleet_conversations: full chat history per session
  - fleet_leads: captured lead/order information
  - fleet_feedback: thumbs up/down per message
"""
import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore

logger = logging.getLogger(__name__)


class FirestoreService:
    """Manages all Firestore interactions for the Fleet Sales Agent."""

    def __init__(self):
        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "nexar-corp-systems")
            firebase_admin.initialize_app(cred, {"projectId": project_id})

        self.db = firestore.client()

    # ─── Conversations ────────────────────────────────────────────────────────

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None
    ) -> None:
        """Append a message to the conversation log."""
        try:
            doc_ref = self.db.collection("fleet_conversations").document(session_id)
            doc = doc_ref.get()

            message = {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **(metadata or {})
            }

            if doc.exists:
                doc_ref.update({
                    "messages": firestore.ArrayUnion([message]),
                    "updated_at": firestore.SERVER_TIMESTAMP,
                })
            else:
                doc_ref.set({
                    "session_id": session_id,
                    "messages": [message],
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "status": "active",
                })
        except Exception as e:
            logger.error(f"Failed to save message: {e}")

    # ─── Leads ────────────────────────────────────────────────────────────────

    async def upsert_lead(self, session_id: str, lead_data: Dict) -> Optional[str]:
        """Create or update lead data for a session."""
        try:
            doc_ref = self.db.collection("fleet_leads").document(session_id)
            doc = doc_ref.get()

            # Remove None values
            clean_data = {k: v for k, v in lead_data.items() if v is not None}

            if doc.exists:
                doc_ref.update({
                    **clean_data,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                })
            else:
                doc_ref.set({
                    "session_id": session_id,
                    **clean_data,
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "status": "new",
                    "slack_notified": False,
                })

            return doc_ref.id
        except Exception as e:
            logger.error(f"Failed to upsert lead: {e}")
            return None

    async def get_lead(self, session_id: str) -> Optional[Dict]:
        """Get lead data for a session."""
        try:
            doc = self.db.collection("fleet_leads").document(session_id).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            logger.error(f"Failed to get lead: {e}")
            return None

    async def mark_lead_slack_notified(self, session_id: str) -> None:
        """Mark lead as notified in Slack."""
        try:
            self.db.collection("fleet_leads").document(session_id).update({
                "slack_notified": True,
                "slack_notified_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception as e:
            logger.error(f"Failed to mark lead notified: {e}")

    async def mark_quote_sent(
        self,
        session_id: str,
        envelope_id: str,
        quote_url: str,
    ) -> None:
        """Record DocuSign envelope details and mark quote as sent."""
        try:
            self.db.collection("fleet_leads").document(session_id).update({
                "envelope_id":   envelope_id,
                "quote_url":     quote_url,
                "quote_sent":    True,
                "quote_sent_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception as e:
            logger.error(f"Failed to mark quote sent: {e}")

    # ─── Feedback ─────────────────────────────────────────────────────────────

    async def save_feedback(
        self,
        session_id: str,
        message_id: str,
        question: str,
        answer: str,
        rating: str,
        feedback_text: Optional[str] = None,
    ) -> Optional[str]:
        """Save user feedback (thumbs up/down) for a message."""
        try:
            doc_ref = self.db.collection("fleet_feedback").document()
            doc_ref.set({
                "session_id": session_id,
                "message_id": message_id,
                "question": question,
                "answer": answer,
                "rating": rating,
                "feedback_text": feedback_text,
                "timestamp": firestore.SERVER_TIMESTAMP,
                "status": "pending",
            })
            return doc_ref.id
        except Exception as e:
            logger.error(f"Failed to save feedback: {e}")
            return None

    # ─── Admin / Monitoring ───────────────────────────────────────────────────

    async def get_recent_leads(self, limit: int = 50) -> List[Dict]:
        """Get recent leads for admin dashboard."""
        try:
            docs = (
                self.db.collection("fleet_leads")
                .order_by("created_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Failed to get leads: {e}")
            return []

    async def get_recent_feedback(self, limit: int = 100) -> List[Dict]:
        """Get recent feedback for admin dashboard."""
        try:
            docs = (
                self.db.collection("fleet_feedback")
                .order_by("timestamp", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            logger.error(f"Failed to get feedback: {e}")
            return []

    async def list_conversations(self, limit: int = 50) -> List[Dict]:
        """List recent conversation sessions with summary metadata."""
        # Try ordered query first; fall back to unordered if index missing
        try:
            docs = (
                self.db.collection("fleet_conversations")
                .order_by("updated_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            return self._build_conversation_summaries(docs)
        except Exception as e:
            logger.warning(f"Ordered conversation query failed ({e}), trying unordered fallback")
            try:
                docs = (
                    self.db.collection("fleet_conversations")
                    .limit(limit)
                    .stream()
                )
                results = self._build_conversation_summaries(docs)
                # Sort in Python since we couldn't sort in Firestore
                results.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
                return results
            except Exception as e2:
                logger.error(f"Failed to list conversations: {e2}")
                raise RuntimeError(f"Firestore query failed: {e2}") from e2

    def _build_conversation_summaries(self, docs) -> List[Dict]:
        results = []
        for doc in docs:
            data = doc.to_dict()
            messages = data.get("messages", [])
            user_msgs = sum(1 for m in messages if m.get("role") == "user")
            last_msg = messages[-1] if messages else None
            results.append({
                "session_id": data.get("session_id", doc.id),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "status": data.get("status"),
                "message_count": len(messages),
                "user_message_count": user_msgs,
                "last_message_preview": (last_msg or {}).get("content", "")[:120] if last_msg else "",
                "last_message_role": (last_msg or {}).get("role"),
                "rating": data.get("rating"),
                "rating_notes": data.get("rating_notes"),
                "rated_by": data.get("rated_by"),
            })
        return results

    async def get_conversation(self, session_id: str) -> Optional[Dict]:
        """Get full conversation with messages and associated lead data."""
        try:
            doc = self.db.collection("fleet_conversations").document(session_id).get()
            if not doc.exists:
                return None
            data = doc.to_dict()
            # Attach lead data if available
            lead_doc = self.db.collection("fleet_leads").document(session_id).get()
            data["lead"] = lead_doc.to_dict() if lead_doc.exists else None
            return data
        except Exception as e:
            logger.error(f"Failed to get conversation: {e}")
            return None

    async def rate_conversation(
        self,
        session_id: str,
        rating: str,
        notes: Optional[str],
        rated_by: str,
    ) -> None:
        """Set admin rating on a conversation document."""
        try:
            self.db.collection("fleet_conversations").document(session_id).update({
                "rating": rating,
                "rating_notes": notes,
                "rated_by": rated_by,
                "rated_at": firestore.SERVER_TIMESTAMP,
            })
        except Exception as e:
            logger.error(f"Failed to rate conversation: {e}")

    async def save_admin_feedback(
        self,
        session_id: str,
        question: str,
        answer: str,
        notes: str,
        triage_resource: Optional[str] = None,
        triage_detail: Optional[str] = None,
        triage_reasoning: Optional[str] = None,
    ) -> Optional[str]:
        """Save admin-generated thumbs-down feedback with optional triage info."""
        try:
            doc_ref = self.db.collection("fleet_feedback").document()
            doc_ref.set({
                "session_id": session_id,
                "message_id": f"admin_{session_id}",
                "question": question,
                "answer": answer,
                "rating": "thumbs_down",
                "feedback_text": notes,
                "source": "admin",
                "triage_resource": triage_resource,
                "triage_detail": triage_detail,
                "triage_reasoning": triage_reasoning,
                "timestamp": firestore.SERVER_TIMESTAMP,
                "status": "pending",
            })
            return doc_ref.id
        except Exception as e:
            logger.error(f"Failed to save admin feedback: {e}")
            return None

    async def get_thumbs_down_feedback(self, limit: int = 100) -> List[Dict]:
        """Get thumbs-down feedback entries (from both users and admins) for triage review."""
        try:
            docs = (
                self.db.collection("fleet_feedback")
                .where("rating", "==", "thumbs_down")
                .order_by("timestamp", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            results = []
            for doc in docs:
                data = doc.to_dict()
                data["feedback_id"] = doc.id
                results.append(data)
            return results
        except Exception as e:
            logger.error(f"Failed to get thumbs-down feedback: {e}")
            return []

    async def update_feedback_triage(
        self,
        feedback_id: str,
        triage_resource: str,
        triage_detail: str,
        triage_reasoning: str,
    ) -> None:
        """Attach triage classification to an existing feedback document."""
        try:
            self.db.collection("fleet_feedback").document(feedback_id).update({
                "triage_resource": triage_resource,
                "triage_detail": triage_detail,
                "triage_reasoning": triage_reasoning,
            })
        except Exception as e:
            logger.error(f"Failed to update feedback triage: {e}")
