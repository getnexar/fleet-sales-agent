"""
Fleet Sales AI Agent API

FastAPI backend serving a React chat widget and providing AI-powered
sales assistance using Gemini via Vertex AI.
"""
import os
import logging
from pathlib import Path

import asyncio
import re
import uuid
from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


def require_corp(request: Request) -> str:
    """Dependency: only allow verified corp users (@getnexar.com) via sidecar-set X-Nexar-User."""
    user = request.headers.get("X-Nexar-User", "")
    if not user.endswith("@getnexar.com"):
        raise HTTPException(status_code=403, detail="Corp access required")
    return user


_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

def _validate_public_request(session_id: str, question: str) -> None:
    """
    Validate inputs on public endpoints (chat, feedback).
    These endpoints are intentionally unauthenticated — this is a public-facing
    customer sales agent (public_api: true). Validation prevents abuse.
    """
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session")
    if not question or len(question) > 2000:
        raise HTTPException(status_code=400, detail="Invalid input")

from backend.models import (
    ChatRequest, ChatResponse,
    FeedbackRequest, FeedbackResponse,
    HealthResponse, LeadData,
)
from backend.chat_service import ChatService
from backend.firestore_service import FirestoreService
from backend.slack_service import SlackService
from backend.storage_service import StorageService
from backend.docusign_service import DocuSignService

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Initialize app
app = FastAPI(
    title="Fleet Sales AI Agent",
    description="AI-powered sales assistant for Nexar Fleet",
    version="1.0.0",
)

_ALLOWED_ORIGINS = ["https://fleet-sales-agent.corp.nexars.ai", "https://fleet.getnexar.com"]
# Local development: add origins via EXTRA_CORS_ORIGINS env var (comma-separated)
_extra = [o.strip() for o in os.environ.get("EXTRA_CORS_ORIGINS", "").split(",") if o.strip()]
if _extra:
    _ALLOWED_ORIGINS += _extra

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "X-Nexar-User", "X-Nexar-User-Type"],
)

# Allow fleet.getnexar.com to embed this app in an iframe (for GTM widget injection).
# frame-ancestors takes precedence over X-Frame-Options in modern browsers.
@app.middleware("http")
async def set_embedding_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors https://fleet.getnexar.com https://fleet-sales-agent.corp.nexars.ai"
    )
    return response

# Initialize services
storage = StorageService()
chat_service = ChatService(storage=storage)
firestore_service = FirestoreService()
slack_service = SlackService()
docusign_service = DocuSignService()

STATIC_DIR = Path(__file__).parent / "static"

# Lead completeness threshold - notify Slack when we have these contact fields
LEAD_NOTIFY_FIELDS = {"contact_name", "contact_email", "contact_phone", "business_name"}

# Fields required before submitting to HubSpot (fleet_size is required by the form)
HUBSPOT_REQUIRED_FIELDS = {"contact_name", "contact_email", "contact_phone", "business_name", "fleet_size"}

# HubSpot form details — set via environment variables
# Form: inbound_smb_fleets
HUBSPOT_PORTAL_ID = os.environ.get("HUBSPOT_PORTAL_ID", "")
HUBSPOT_FORM_ID = os.environ.get("HUBSPOT_FORM_ID", "")

_SUBSCRIPTION_LABELS = {
    "no-contract": "$25/mo (no contract)",
    "1-year": "1-year plan ($19.99/mo)",
    "2-year": "2-year plan ($17.99/mo)",
    "3-year": "3-year plan ($14.99/mo)",
}


_REDACT_PATTERNS = [
    (re.compile(r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b'), '[SSN REDACTED]'),          # SSN
    (re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'), '[CARD REDACTED]'),               # credit card
    (re.compile(r'\b\d{9}\b'), '[ID REDACTED]'),                                    # 9-digit IDs
]

_PHONE_RE = re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
_FLEET_SIZE_RE = re.compile(r'\b(\d+)\s*(?:vehicle|truck|van|car|fleet|unit|bus|bike)', re.IGNORECASE)


def _extract_contact_from_text(text: str) -> dict:
    """
    Fallback: parse contact signals directly from user message text.
    Used when Claude returns non-JSON (plain text) during CLOSE_QUOTE so signals
    aren't lost and the Firestore upsert still happens.
    """
    extracted = {}
    email_match = _EMAIL_RE.search(text)
    if email_match:
        extracted["contact_email"] = email_match.group(0)
    phone_match = _PHONE_RE.search(text)
    if phone_match:
        extracted["contact_phone"] = phone_match.group(0).strip()
    fleet_match = _FLEET_SIZE_RE.search(text)
    if fleet_match:
        extracted["fleet_size"] = fleet_match.group(1)
    return extracted

def _redact_sensitive(text: str) -> str:
    """Redact accidental sensitive data (SSN, credit card numbers) from transcript."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _build_chatbot_summary(lead: dict, messages: list) -> str:
    """Build the structured summary + full transcript for HubSpot chatbot_summary field."""
    lines = ["=== LEAD SUMMARY ==="]

    if lead.get("fleet_size"):
        lines.append(f"Fleet size: {lead['fleet_size']} vehicles")
    if lead.get("industry"):
        lines.append(f"Industry: {lead['industry']}")
    if lead.get("pain_points"):
        lines.append(f"Reason: {lead['pain_points']}")
    if lead.get("business_name"):
        lines.append(f"Business: {lead['business_name']}")
    if lead.get("camera_model"):
        cam = lead["camera_model"]
        mem = lead.get("memory_option", "")
        lines.append(f"Camera: {cam}" + (f" ({mem})" if mem else ""))
    if lead.get("subscription_plan"):
        lines.append(f"Subscription: {_SUBSCRIPTION_LABELS.get(lead['subscription_plan'], lead['subscription_plan'])}")

    lines.append("")
    lines.append("=== FULL TRANSCRIPT ===")

    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        label = "Customer" if role == "user" else "Alex"
        lines.append(f"[{label}] {_redact_sensitive(content)}")

    return "\n".join(lines)


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="healthy", service="fleet-sales-agent", version="1.0.0")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Handle a chat message and return an AI-generated response.
    Public endpoint (public_api: true) — intentionally unauthenticated for customer access.
    Also extracts lead signals and triggers Slack notifications when appropriate.
    """
    _validate_public_request(request.session_id, request.question)
    try:
        # Sanitize user input to prevent prompt injection
        clean_question = chat_service._sanitize_input(request.question)

        # Sanitize conversation history: only allow known roles, cap length, strip injection patterns
        _ALLOWED_ROLES = {"user", "assistant"}
        clean_history = [
            msg for msg in (request.conversation_history or [])
            if getattr(msg, "role", None) in _ALLOWED_ROLES
        ][-40:]  # cap at last 40 messages to limit context manipulation surface

        # Get AI response
        result = await chat_service.get_response(
            question=clean_question,
            conversation_history=clean_history,
        )

        answer = result.get("answer", "")
        follow_up = result.get("follow_up")
        cta_type = result.get("cta_type")
        lead_signals = result.get("lead_signals", {})

        # Build suggested follow-ups list
        follow_ups = [follow_up] if follow_up else []

        # Save both messages to Firestore conversation log
        await firestore_service.save_message(
            session_id=request.session_id,
            role="user",
            content=request.question,
        )
        await firestore_service.save_message(
            session_id=request.session_id,
            role="assistant",
            content=answer,
            metadata={"cta_type": cta_type, "lead_signals": lead_signals},
        )

        # Update lead data in Firestore if signals detected
        lead_collected = False
        quote_url = None
        phase_str = result.get("_phase", "CONNECT")

        # Fallback: if Claude returned non-JSON (empty lead_signals) during CLOSE_QUOTE,
        # extract contact info directly from the user's raw message so the Firestore
        # upsert still happens and the HubSpot gate can fire.
        if phase_str == "CLOSE_QUOTE" and not any(lead_signals.values()):
            fallback = _extract_contact_from_text(request.question)
            if fallback:
                logger.info(f"Fallback signal extraction: {list(fallback.keys())}")
                for k, v in fallback.items():
                    if not lead_signals.get(k):
                        lead_signals[k] = v

        if any(lead_signals.values()) or phase_str == "CLOSE_QUOTE":
            lead_update = {
                k: v for k, v in {
                    "fleet_size":        int(lead_signals["fleet_size"]) if lead_signals.get("fleet_size") is not None else None,
                    "industry":          lead_signals.get("industry"),
                    "pain_points":       lead_signals.get("pain_points"),
                    "contact_name":      lead_signals.get("contact_name"),
                    "contact_email":     lead_signals.get("contact_email"),
                    "contact_phone":     lead_signals.get("contact_phone"),
                    "business_name":     lead_signals.get("business_name"),
                    "num_cameras":       int(lead_signals["num_cameras"]) if lead_signals.get("num_cameras") is not None else None,
                    "camera_model":      lead_signals.get("camera_model"),
                    "memory_option":     lead_signals.get("memory_option"),
                    "subscription_plan": lead_signals.get("subscription_plan"),
                    "cta_type":          cta_type,
                }.items() if v is not None
            }
            # Always upsert in CLOSE_QUOTE even if lead_update is empty — ensures the
            # Firestore document exists so current_lead is never None and the HubSpot gate runs.
            await firestore_service.upsert_lead(request.session_id, lead_update or {"_last_phase": phase_str})

        # Always fetch current lead state — needed for Slack + HubSpot checks regardless of new signals
        current_lead = await firestore_service.get_lead(request.session_id)

        if current_lead:
            # Check if we have enough info to notify Slack
            if not current_lead.get("slack_notified"):
                collected = {f for f in LEAD_NOTIFY_FIELDS if current_lead.get(f)}
                if collected >= LEAD_NOTIFY_FIELDS:
                    sent = await slack_service.notify_new_lead(
                        request.session_id, current_lead
                    )
                    if sent:
                        await firestore_service.mark_lead_slack_notified(request.session_id)
                        lead_collected = True
                elif lead_signals.get("order_intent") == "HIGH" or (
                    int(current_lead.get("fleet_size") or 0) >= 50
                ):
                    await slack_service.notify_high_intent_lead(
                        request.session_id, current_lead
                    )

            # Log what's missing so we can debug gate failures
            if phase_str == "CLOSE_QUOTE" and not current_lead.get("hubspot_submitted"):
                missing = [f for f in HUBSPOT_REQUIRED_FIELDS if not current_lead.get(f)]
                if missing:
                    logger.info(f"HubSpot gate: missing fields {missing} for session {request.session_id}")

            # HubSpot: submit to inbound_smb_fleets form when all required fields present
            if (
                phase_str == "CLOSE_QUOTE"
                and not current_lead.get("hubspot_submitted")
                and all(current_lead.get(f) for f in HUBSPOT_REQUIRED_FIELDS)
                and HUBSPOT_PORTAL_ID
                and HUBSPOT_FORM_ID
            ):
                try:
                    import httpx as _httpx

                    # Build summary + transcript from Firestore conversation
                    convo = await firestore_service.get_conversation(request.session_id)
                    messages_for_summary = (convo or {}).get("messages", [])
                    chatbot_summary = _build_chatbot_summary(current_lead, messages_for_summary)

                    # Split full name into first / last
                    name_parts = (current_lead.get("contact_name") or "").split()
                    firstname = name_parts[0] if name_parts else ""
                    lastname = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

                    hs_fields = [
                        {"name": "firstname",           "value": firstname},
                        {"name": "lastname",            "value": lastname},
                        {"name": "email",               "value": current_lead.get("contact_email", "")},
                        {"name": "phone",               "value": current_lead.get("contact_phone", "")},
                        {"name": "company",             "value": current_lead.get("business_name", "")},
                        {"name": "contact_channel",     "value": "Chat Bot"},
                        {"name": "chatbot_summary",     "value": chatbot_summary},
                    ]
                    # how_many_vehicles_ = fleet size; fall back to num_cameras if not separately captured
                    vehicle_count = current_lead.get("fleet_size") or current_lead.get("num_cameras")
                    hs_fields.append({"name": "how_many_vehicles_", "value": str(vehicle_count)})
                    # Optional fields
                    if current_lead.get("industry"):
                        hs_fields.append({"name": "industry", "value": current_lead["industry"]})

                    hubspot_payload = {
                        "fields": hs_fields,
                        "context": {
                            "pageUri": "https://fleet-sales-agent.corp.nexars.ai",
                            "pageName": "Fleet Sales Chat",
                        },
                    }

                    async with _httpx.AsyncClient(timeout=10) as _hclient:
                        _hr = await _hclient.post(
                            f"https://api.hsforms.com/submissions/v3/integration/submit/{HUBSPOT_PORTAL_ID}/{HUBSPOT_FORM_ID}",
                            json=hubspot_payload,
                        )
                        if _hr.status_code in (200, 204):
                            await firestore_service.upsert_lead(request.session_id, {"hubspot_submitted": True})
                            logger.info(f"HubSpot contact submitted for session {request.session_id}")
                        else:
                            logger.warning(f"HubSpot submission failed: {_hr.status_code} {_hr.text[:200]}")
                except Exception as hs_err:
                    logger.error(f"HubSpot error for session {request.session_id}: {hs_err}")
                    # Fall through — don't break the conversation on HubSpot failure

        return ChatResponse(
            answer=answer,
            session_id=request.session_id,
            suggested_follow_ups=follow_ups,
            lead_collected=lead_collected,
            cta_type=cta_type,
            quote_url=quote_url,
        )

    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """
    Save user feedback (thumbs up/down) for a message.
    Public endpoint (public_api: true) — intentionally unauthenticated for customer access.
    """
    _validate_public_request(request.session_id, request.answer or "")
    try:
        feedback_id = await firestore_service.save_feedback(
            session_id=request.session_id,
            message_id=request.message_id,
            question=request.question,
            answer=request.answer,
            rating=request.rating,
            feedback_text=request.feedback_text,
        )
        if feedback_id:
            return FeedbackResponse(success=True, message="Thanks for your feedback!", feedback_id=feedback_id)
        return FeedbackResponse(success=False, message="Feedback received but not saved.")
    except Exception as e:
        logger.error(f"Feedback error: {e}")
        return FeedbackResponse(success=False, message="Unable to save feedback.")




@app.post("/api/admin/reload-config")
async def reload_config(user: str = Depends(require_corp)):
    """Force reload of FAQ/instructions from GCS (no redeployment needed)."""
    storage.reload()
    return {"status": "ok", "message": "Config cache cleared. Will reload from GCS on next request."}


@app.get("/api/admin/leads")
async def get_leads(limit: int = Query(default=50, ge=1, le=500), user: str = Depends(require_corp)):
    """Get recent leads for admin monitoring."""
    leads = await firestore_service.get_recent_leads(limit=limit)
    return {"leads": leads, "count": len(leads)}


@app.get("/api/admin/feedback")
async def get_feedback(limit: int = Query(default=100, ge=1, le=500), user: str = Depends(require_corp)):
    """Get recent feedback for admin monitoring."""
    feedback = await firestore_service.get_recent_feedback(limit=limit)
    return {"feedback": feedback, "count": len(feedback)}


# ─── Admin: Conversations ─────────────────────────────────────────────────────

@app.get("/api/admin/conversations")
async def list_conversations(limit: int = Query(default=50, ge=1, le=500), user: str = Depends(require_corp)):
    """List recent conversation sessions with summary metadata."""
    try:
        conversations = await firestore_service.list_conversations(limit=limit)
        return {"conversations": conversations, "count": len(conversations)}
    except RuntimeError as e:
        logger.error(f"List conversations error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/admin/conversations/export")
async def export_conversations(limit: int = Query(default=50, ge=1, le=500), user: str = Depends(require_corp)):
    """Export full conversation sessions (with lead data) as a downloadable JSON file."""
    import json as _json
    from fastapi.responses import Response

    sessions = []
    summaries = await firestore_service.list_conversations(limit=limit)
    for s in summaries:
        detail = await firestore_service.get_conversation(s["session_id"])
        if detail:
            # Serialize Firestore timestamps to strings
            def _serialize(obj):
                if hasattr(obj, 'seconds'):
                    from datetime import datetime
                    return datetime.utcfromtimestamp(obj.seconds).strftime('%Y-%m-%d %H:%M:%S UTC')
                return str(obj)

            sessions.append(_json.loads(_json.dumps(detail, default=_serialize)))

    payload = _json.dumps(sessions, indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=fleet_conversations.json"},
    )


@app.get("/api/admin/conversations/{session_id}")
async def get_conversation(session_id: str, user: str = Depends(require_corp)):
    """Get full conversation history and associated lead data."""
    conversation = await firestore_service.get_conversation(session_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


class ConversationRatingRequest(BaseModel):
    rating: str  # "thumbs_up" | "thumbs_down"
    notes: str = ""
    # For thumbs_down: include a representative Q&A pair to run triage against
    question: str = ""
    answer: str = ""


@app.post("/api/admin/conversations/{session_id}/rate")
async def rate_conversation(
    session_id: str,
    request: ConversationRatingRequest,
    user: str = Depends(require_corp),
):
    """Rate a conversation and (for thumbs_down) trigger async Gemini triage."""
    await firestore_service.rate_conversation(
        session_id=session_id,
        rating=request.rating,
        notes=request.notes,
        rated_by=user,
    )

    feedback_id = None
    if request.rating == "thumbs_down" and (request.question or request.notes):
        # Save admin feedback doc immediately (triage filled in async)
        feedback_id = await firestore_service.save_admin_feedback(
            session_id=session_id,
            question=request.question,
            answer=request.answer,
            notes=request.notes,
        )

        # Run triage in background — don't block the response
        if feedback_id:
            faqs = storage.get_faqs()
            faq_titles = [f.get("question", "") for f in faqs]
            from backend.conversation_router import ConversationPhase
            phase_names = [p.value for p in ConversationPhase]

            async def _run_triage():
                try:
                    result = await chat_service.triage_feedback(
                        question=request.question,
                        answer=request.answer,
                        admin_notes=request.notes,
                        faq_titles=faq_titles,
                        phase_names=phase_names,
                    )
                    await firestore_service.update_feedback_triage(
                        feedback_id=feedback_id,
                        triage_resource=result.get("resource", "unknown"),
                        triage_detail=result.get("detail", ""),
                        triage_reasoning=result.get("reasoning", ""),
                    )
                    logger.info(f"Triage complete for {feedback_id}: {result}")
                except Exception as e:
                    logger.error(f"Triage background task failed: {e}")

            asyncio.create_task(_run_triage())

    return {"status": "ok", "feedback_id": feedback_id}


# ─── Admin: Thumbs-down feedback with triage ─────────────────────────────────

@app.get("/api/admin/feedback/thumbs-down")
async def get_thumbs_down_feedback(limit: int = Query(default=100, ge=1, le=500), user: str = Depends(require_corp)):
    """Get all thumbs-down feedback with triage classification."""
    feedback = await firestore_service.get_thumbs_down_feedback(limit=limit)
    return {"feedback": feedback, "count": len(feedback)}


# ─── Admin: Config (FAQ + prompts) ───────────────────────────────────────────

@app.get("/api/admin/config")
async def get_config(user: str = Depends(require_corp)):
    """Get all editable bot config: FAQs, core prompt, and phase prompts."""
    from backend.chat_service import CORE_PROMPT_TEMPLATE
    from backend.conversation_router import PHASE_PROMPTS, ConversationPhase

    config = storage.get_all_config()
    # Fill in hardcoded fallbacks if GCS files don't exist yet
    if config["core_prompt"] is None:
        config["core_prompt"] = CORE_PROMPT_TEMPLATE
    if config["phase_prompts"] is None:
        config["phase_prompts"] = {phase.value: prompt for phase, prompt in PHASE_PROMPTS.items()}
    return config


class ConfigFaqsUpdate(BaseModel):
    faqs: list


class ConfigPromptsUpdate(BaseModel):
    core_prompt: str
    phase_prompts: dict


@app.put("/api/admin/config/faqs")
async def update_faqs(request: ConfigFaqsUpdate, user: str = Depends(require_corp)):
    """Overwrite FAQ JSON in GCS and reload cache."""
    try:
        storage.save_faqs(request.faqs)
        return {"status": "ok", "message": f"Saved {len(request.faqs)} FAQs and reloaded cache."}
    except RuntimeError as e:
        logger.error(f"Config update error: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@app.put("/api/admin/config/prompts")
async def update_prompts(request: ConfigPromptsUpdate, user: str = Depends(require_corp)):
    """Overwrite core prompt and phase prompts in GCS and reload cache."""
    try:
        storage.save_prompts(request.core_prompt, request.phase_prompts)
        return {"status": "ok", "message": "Prompts saved and cache reloaded."}
    except RuntimeError as e:
        logger.error(f"Config update error: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


# Serve React frontend
if STATIC_DIR.exists():
    if (STATIC_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Resolve and validate path is within STATIC_DIR to prevent directory traversal
        try:
            resolved = (STATIC_DIR / full_path).resolve()
            if not str(resolved).startswith(str(STATIC_DIR.resolve()) + "/") and resolved != STATIC_DIR.resolve():
                return FileResponse(STATIC_DIR / "index.html")
            if resolved.exists() and resolved.is_file():
                return FileResponse(resolved)
        except Exception:
            pass
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/")
    async def root():
        return {
            "service": "Fleet Sales AI Agent",
            "status": "API running - build frontend with: cd frontend && npm run build",
            "endpoints": {
                "chat": "POST /api/chat",
                "feedback": "POST /api/feedback",
                "health": "GET /api/health",
                "admin_leads": "GET /api/admin/leads",
                "admin_feedback": "GET /api/admin/feedback",
                "reload_config": "POST /api/admin/reload-config",
            }
        }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port)
