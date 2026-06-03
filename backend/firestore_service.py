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

    async def count_stats(self) -> Dict:
        """Return aggregate counts and distributions for the admin dashboard."""
        try:
            import asyncio
            from datetime import timezone
            loop = asyncio.get_event_loop()

            def _query():
                total_convos = sum(1 for _ in self.db.collection("fleet_conversations").limit(5000).stream())
                lead_docs = [d.to_dict() for d in self.db.collection("fleet_leads").limit(5000).stream()]

                contact_fields = {"contact_name", "contact_email", "contact_phone", "business_name"}
                leads_with_contact = sum(1 for d in lead_docs if any(d.get(f) for f in contact_fields))
                hs_submitted = sum(1 for d in lead_docs if d.get("hubspot_submitted"))

                # Fleet size distribution
                size_bins: Dict[str, int] = {"1–10": 0, "11–25": 0, "26–50": 0, "51–100": 0, "100+": 0}
                for d in lead_docs:
                    fs = d.get("fleet_size")
                    if fs is None:
                        continue
                    try:
                        n = int(float(str(fs)))
                    except (ValueError, TypeError):
                        continue
                    if n <= 10:
                        size_bins["1–10"] += 1
                    elif n <= 25:
                        size_bins["11–25"] += 1
                    elif n <= 50:
                        size_bins["26–50"] += 1
                    elif n <= 100:
                        size_bins["51–100"] += 1
                    else:
                        size_bins["100+"] += 1
                fleet_size_dist = [{"range": k, "count": v} for k, v in size_bins.items() if v > 0]

                # Camera model interest
                camera_counts: Dict[str, int] = {}
                for d in lead_docs:
                    m = d.get("camera_model")
                    if m:
                        camera_counts[m] = camera_counts.get(m, 0) + 1
                camera_interest = [{"model": k, "count": v} for k, v in sorted(camera_counts.items(), key=lambda x: -x[1])]

                # Plan type interest
                plan_labels = {"no-contract": "No Contract", "1-year": "1 Year", "2-year": "2 Years", "3-year": "3 Years"}
                plan_counts: Dict[str, int] = {}
                for d in lead_docs:
                    p = d.get("subscription_plan")
                    if p:
                        label = plan_labels.get(p, p)
                        plan_counts[label] = plan_counts.get(label, 0) + 1
                plan_interest = [{"plan": k, "count": v} for k, v in sorted(plan_counts.items(), key=lambda x: -x[1])]

                # Monthly leads — last 6 calendar months
                now = datetime.now(timezone.utc)
                months: Dict[str, int] = {}
                for i in range(5, -1, -1):
                    m = now.month - i
                    y = now.year
                    while m <= 0:
                        m += 12
                        y -= 1
                    key = datetime(y, m, 1).strftime("%b %Y")
                    months[key] = 0

                for d in lead_docs:
                    created = d.get("created_at")
                    if not created:
                        continue
                    try:
                        if hasattr(created, 'seconds'):
                            dt = datetime.fromtimestamp(created.seconds, tz=timezone.utc)
                        elif isinstance(created, datetime):
                            dt = created.astimezone(timezone.utc)
                        else:
                            continue
                        key = dt.strftime("%b %Y")
                        if key in months:
                            months[key] += 1
                    except Exception:
                        pass

                monthly_leads = [{"month": k, "count": v} for k, v in months.items()]

                return {
                    "total_conversations": total_convos,
                    "leads_with_contact": leads_with_contact,
                    "hubspot_submitted": hs_submitted,
                    "fleet_size_distribution": fleet_size_dist,
                    "camera_interest": camera_interest,
                    "plan_interest": plan_interest,
                    "monthly_leads": monthly_leads,
                }

            return await loop.run_in_executor(None, _query)
        except Exception as e:
            logger.error(f"Failed to count stats: {e}")
            return {
                "total_conversations": 0, "leads_with_contact": 0, "hubspot_submitted": 0,
                "fleet_size_distribution": [], "camera_interest": [], "plan_interest": [], "monthly_leads": [],
            }

    # ─── Distributed Rate Limiting ────────────────────────────────────────────

    async def check_and_increment_rate_limit(
        self,
        session_id: str,
        window_key: int,
        max_count: int,
    ) -> bool:
        """
        Distributed per-session rate limit using Firestore atomic increment.
        Effective across all Cloud Run instances (unlike in-memory dicts).
        Returns True if the request is within the limit, False if exceeded.

        Documents are stored in fleet_rate_limits/{session_id}_{window_key}
        and are naturally sparse (one per session per time window).
        """
        import asyncio
        doc_id = f"{session_id}_{window_key}"
        doc_ref = self.db.collection("fleet_rate_limits").document(doc_id)

        def _increment_and_check() -> int:
            # Atomic server-side increment — consistent across concurrent instances
            doc_ref.set({"count": firestore.Increment(1), "window": window_key}, merge=True)
            snap = doc_ref.get()
            return snap.get("count") or 1

        try:
            loop = asyncio.get_event_loop()
            count = await loop.run_in_executor(None, _increment_and_check)
            return count <= max_count
        except Exception as e:
            logger.warning(f"Rate limit check failed for session {session_id[:8]}: {e} — allowing request")
            return True  # Fail open: don't block users if Firestore is unavailable
