"""
Fleet Sales AI Agent API

FastAPI backend serving a React chat widget and providing AI-powered
sales assistance using Gemini via Vertex AI.
"""
import os
import logging
from pathlib import Path

import asyncio
import hashlib
import re
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Literal
from pydantic import BaseModel, Field
import httpx as _httpx


_CORP_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+\-]+@getnexar\.com$')


def require_corp(request: Request) -> str:
    """Dependency: only allow verified corp users (@getnexar.com) via sidecar-set X-Nexar-User.

    The platform sidecar injects X-Nexar-User after verifying the corp identity token,
    so this header is authoritative for authenticated corp sessions. The application
    adds a defense-in-depth layer by validating the full email format (not just the
    domain suffix) to reject malformed or crafted values even if the sidecar is
    misconfigured.
    """
    user = request.headers.get("X-Nexar-User", "")
    if not _CORP_EMAIL_RE.match(user):
        raise HTTPException(status_code=403, detail="Corp access required")
    return user


def _prompt_admin_emails() -> set[str]:
    return {
        e.strip().lower()
        for e in os.environ.get("PROMPT_ADMIN_EMAILS", "").split(",")
        if e.strip()
    }


def require_prompt_admin(request: Request) -> str:
    """Restrict sensitive bot configuration to explicitly allowlisted admins."""
    user = require_corp(request)
    admins = _prompt_admin_emails()
    if not admins or user.lower() not in admins:
        raise HTTPException(status_code=403, detail="Bot config access restricted to designated admins")
    return user


def require_corp_export(request: Request) -> str:
    """
    Stricter dependency for data-export endpoints.
    By default any @getnexar.com account is allowed; set EXPORT_ALLOWED_EMAILS (comma-separated)
    to restrict export access to specific accounts for granular data access control.
    """
    user = require_corp(request)
    _allowed = {e.strip() for e in os.environ.get("EXPORT_ALLOWED_EMAILS", "").split(",") if e.strip()}
    if _allowed and user not in _allowed:
        raise HTTPException(status_code=403, detail="Export access restricted to authorised accounts")
    return user


def _safe_log_value(value: str, limit: int = 100) -> str:
    """Remove control characters before writing untrusted header values to audit logs."""
    return re.sub(r'[\x00-\x1f\x7f]', '', value or '')[:limit]


def _sid(session_id: str) -> str:
    """Return first 8 chars of session ID for log correlation without full identifier exposure."""
    return (session_id or "")[:8]


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
# Local development: add origins via EXTRA_CORS_ORIGINS env var (comma-separated).
# Only origins matching trusted domains are accepted — others are silently ignored.
# Single-level subdomain only (no dots allowed) to prevent subdomain-takeover escalation
_ORIGIN_PATTERN = re.compile(r'^https://[a-z0-9-]+\.(?:nexar\.app|getnexar\.com)$')

# Per-session rate limit: max 30 messages per 60-second window.
# Implemented via Firestore so it is effective across all Cloud Run instances.
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 30
_IP_RATE_LIMIT_MAX = int(os.environ.get("IP_RATE_LIMIT_MAX", "120"))
_extra = [
    o.strip() for o in os.environ.get("EXTRA_CORS_ORIGINS", "").split(",")
    if o.strip() and _ORIGIN_PATTERN.match(o.strip())
]
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
SLACK_NOTIFICATIONS_ENABLED = os.environ.get("SLACK_NOTIFICATIONS_ENABLED", "true").lower() == "true"

STATIC_DIR = Path(__file__).parent / "static"

# Lead completeness threshold - notify Slack when we have these contact fields
LEAD_NOTIFY_FIELDS = {"contact_name", "contact_email", "contact_phone", "business_name"}

# Fields required before submitting to HubSpot (fleet_size is required by the form)
HUBSPOT_REQUIRED_FIELDS = {"contact_name", "contact_email", "contact_phone", "business_name", "fleet_size"}

# HubSpot form details — set via environment variables
# Form: inbound_smb_fleets
HUBSPOT_PORTAL_ID = os.environ.get("HUBSPOT_PORTAL_ID", "")
HUBSPOT_FORM_ID = os.environ.get("HUBSPOT_FORM_ID", "")
HUBSPOT_PAGE_URI = os.environ.get("HUBSPOT_PAGE_URI", "")
if HUBSPOT_PORTAL_ID and not re.fullmatch(r'[0-9]{1,32}', HUBSPOT_PORTAL_ID):
    raise ValueError("Invalid HUBSPOT_PORTAL_ID")
if HUBSPOT_FORM_ID and not re.fullmatch(r'[0-9A-Za-z_-]{1,80}', HUBSPOT_FORM_ID):
    raise ValueError("Invalid HUBSPOT_FORM_ID")
HUBSPOT_RETRY_LIMIT = max(1, min(10, int(os.environ.get("HUBSPOT_RETRY_LIMIT", "3"))))
HUBSPOT_RETRY_COOLDOWN_SECONDS = max(60, min(86400, int(os.environ.get("HUBSPOT_RETRY_COOLDOWN_SECONDS", "900"))))

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

# Maximum byte size for admin-managed prompt content
_MAX_PROMPT_BYTES = 50_000

_LEAD_TEXT_LIMITS = {
    "contact_name": 100,
    "business_name": 200,
    "industry": 100,
    "pain_points": 300,
    "camera_model": 50,
    "memory_option": 20,
    "subscription_plan": 30,
    "cta_type": 20,
    "shipping_address": 300,
    "billing_email": 254,
}

_TRUSTED_PAGE_ORIGINS = {
    "https://fleet.getnexar.com",
    "https://fleet-sales-agent.corp.nexars.ai",
}


def _validate_lead_signals(signals: dict) -> dict:
    """
    Validate and sanitize AI-extracted lead signal values.
    Ensures contact data meets expected formats/ranges before writing to Firestore,
    preventing prompt injection from producing arbitrary CRM data.
    """
    validated = {}
    for k, v in signals.items():
        if v is None:
            continue
        if k == "contact_email":
            if isinstance(v, str) and re.fullmatch(
                r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', v.strip()
            ):
                validated[k] = v.strip()[:254]
        elif k == "contact_phone":
            digits = re.sub(r'\D', '', str(v))
            if 7 <= len(digits) <= 15:
                validated[k] = str(v)[:20]
        elif k == "fleet_size":
            try:
                fs = int(float(str(v)))
                if 1 <= fs <= 100_000:
                    validated[k] = fs
            except (ValueError, TypeError):
                pass
        elif k == "num_cameras":
            try:
                count = int(float(str(v)))
                if 1 <= count <= 100_000:
                    validated[k] = count
            except (ValueError, TypeError):
                pass
        elif k == "camera_model":
            if v in {"Beam 2 Mini", "Beam 2", "Nexar One"}:
                validated[k] = v
        elif k == "memory_option":
            if v in {"128GB", "256GB"}:
                validated[k] = v
        elif k == "subscription_plan":
            if v in _SUBSCRIPTION_LABELS:
                validated[k] = v
        elif k == "order_intent":
            if v in {"HIGH", "MEDIUM", "LOW"}:
                validated[k] = v
        elif k in ("contact_name", "business_name"):
            if isinstance(v, str) and v.strip():
                # Normalize, strip control characters, remove known injection markers,
                # and bound name fields before storage/downstream propagation.
                _clean = _sanitize_downstream_text(v, _LEAD_TEXT_LIMITS[k])
                if _clean:
                    validated[k] = _clean
        elif isinstance(v, str):
            # Normalize, strip control characters and injection override patterns,
            # then apply field-specific length limits before Firestore/Slack/HubSpot use.
            _clean = _sanitize_downstream_text(v, _LEAD_TEXT_LIMITS.get(k, 200))
            if _clean:
                validated[k] = _clean
        else:
            validated[k] = v
    return validated


def _sanitize_downstream_text(value: str, max_len: int) -> str:
    """
    Normalize and bound LLM-originated text before it leaves the app boundary.
    This is used for Firestore lead fields, Slack notifications, and HubSpot form
    payloads so a prompt-injected extraction cannot propagate long or disguised
    instruction text into downstream systems.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    for pattern in _PROMPT_FORBIDDEN_PATTERNS:
        text = pattern.sub('[removed]', text)
    return text[:max_len].strip()


def _sanitize_lead_for_downstream(lead: dict) -> dict:
    """Apply field-specific bounds to all lead strings before Slack/HubSpot use."""
    clean = {}
    for key, value in (lead or {}).items():
        if isinstance(value, str):
            clean[key] = _sanitize_downstream_text(value, _LEAD_TEXT_LIMITS.get(key, 200))
        else:
            clean[key] = value
    return clean


def _client_rate_limit_key(request: Request) -> str:
    """Hash client IP into a stable, non-reversible key for public endpoint limits."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    client_ip = forwarded_for.split(",")[0].strip()
    if not client_ip and request.client:
        client_ip = request.client.host or ""
    digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:24]
    return f"ip_{digest}"


def _hubspot_page_uri(request: Request) -> str:
    """Prefer configured/observed trusted public page context over internal app URL."""
    if HUBSPOT_PAGE_URI:
        return HUBSPOT_PAGE_URI[:500]

    referer = request.headers.get("Referer", "")
    for trusted_origin in _TRUSTED_PAGE_ORIGINS:
        if referer.startswith(trusted_origin):
            return referer[:500]

    origin = request.headers.get("Origin", "")
    if origin in _TRUSTED_PAGE_ORIGINS:
        return origin

    return "https://fleet.getnexar.com"


def _hubspot_retry_due(lead: dict) -> bool:
    """Return False while a prior transient HubSpot failure is cooling down."""
    try:
        return time.time() >= float((lead or {}).get("hubspot_next_retry_at") or 0)
    except (TypeError, ValueError):
        return True


def _hubspot_failure_update(lead: dict, *, permanent: bool = False) -> dict:
    retry_count = int((lead or {}).get("hubspot_retry_count") or 0) + 1
    update = {
        "hubspot_retry_count": retry_count,
        "hubspot_last_failure_at": datetime.now(timezone.utc).isoformat(),
    }
    if permanent or retry_count >= HUBSPOT_RETRY_LIMIT:
        update["hubspot_permanently_failed"] = True
    else:
        update["hubspot_next_retry_at"] = time.time() + HUBSPOT_RETRY_COOLDOWN_SECONDS
    return update


def _redact_sensitive(text: str) -> str:
    """Redact accidental sensitive data (SSN, credit card numbers) from transcript."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_transcript_pii(text: str) -> str:
    """
    Redact contact PII (email, phone) from raw transcript content before sending to third parties.
    Structured contact fields are submitted separately via HubSpot named fields;
    redacting here prevents duplicate raw PII transmission in the free-text transcript.
    """
    text = _redact_sensitive(text)
    text = _EMAIL_RE.sub('[email]', text)
    text = _PHONE_RE.sub('[phone]', text)
    return text


_TRANSCRIPT_CHAR_LIMIT = 3000


def _build_chatbot_summary(lead: dict, messages: list) -> str:
    """Build the structured summary + truncated transcript for HubSpot chatbot_summary field.
    Contact PII is redacted from the transcript — it's already submitted in structured fields."""
    lead = _sanitize_lead_for_downstream(lead)
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
    lines.append("=== CONVERSATION SUMMARY ===")

    transcript_lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        label = "Customer" if role == "user" else "Alex"
        # Strip injection patterns from both user and AI-generated content before
        # including in the HubSpot CRM record — prevents prompt-injected text from
        # being stored in CRM if the LLM was manipulated into outputting it.
        content = _sanitize_downstream_text(content, 1000)
        transcript_lines.append(f"[{label}] {_redact_transcript_pii(content)}")

    transcript = "\n".join(transcript_lines)
    lines.append(transcript[:_TRANSCRIPT_CHAR_LIMIT])

    return "\n".join(lines)


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(status="healthy", service="fleet-sales-agent", version="1.0.0")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request):
    """
    Handle a chat message and return an AI-generated response.
    Public endpoint (public_api: true) — intentionally unauthenticated for customer access.
    Also extracts lead signals and triggers Slack notifications when appropriate.
    """
    _validate_public_request(request.session_id, request.question)
    window_key = int(time.time() // _RATE_LIMIT_WINDOW)
    if not await firestore_service.check_and_increment_rate_limit(
        request.session_id, window_key, _RATE_LIMIT_MAX
    ):
        raise HTTPException(status_code=429, detail="Too many requests")
    if not await firestore_service.check_and_increment_rate_limit(
        _client_rate_limit_key(http_request), window_key, _IP_RATE_LIMIT_MAX
    ):
        raise HTTPException(status_code=429, detail="Too many requests")
    try:
        # Sanitize user input to prevent prompt injection
        clean_question = chat_service._sanitize_input(request.question)

        # Load conversation history from server-side Firestore instead of trusting
        # client-supplied history, which an attacker could manipulate to inject
        # arbitrary prior messages and bypass sales guardrails.
        from backend.models import Message as _Message
        _prior_convo = await firestore_service.get_conversation(request.session_id)
        _prior_messages = (_prior_convo or {}).get("messages", [])
        clean_history = []
        for _m in _prior_messages[-40:]:
            _role = _m.get("role", "")
            _content = (_m.get("content") or "").strip()
            if _role in ("user", "assistant") and _content:
                clean_history.append(_Message(role=_role, content=_content))

        # Build the messages array with explicit role separation.
        # User-supplied content is placed ONLY in user-role messages; the system prompt
        # is assembled separately by ChatService and passed via the Anthropic system= param.
        _llm_messages: list = []
        for _m in clean_history:
            _llm_messages.append({
                "role": "user" if _m.role == "user" else "assistant",
                "content": chat_service._sanitize_input(_m.content) if _m.role == "user" else _m.content,
            })
        _llm_messages.append({"role": "user", "content": clean_question})

        result = await chat_service.get_response(
            question=clean_question,
            conversation_history=clean_history,
            messages=_llm_messages,
        )

        # Sanitize AI-generated answer before returning to client.
        # Caps length and strips control characters; does not block content — the
        # _filter_output() call in chat_service already logs suspicious patterns.
        _raw_answer = result.get("answer", "") or ""
        answer = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', _raw_answer)[:8000]
        follow_up = result.get("follow_up")
        cta_type = result.get("cta_type")
        if cta_type not in {"quote", "info", "demo", "trial", None}:
            cta_type = None
        # Validate AI-extracted lead signals against expected formats/ranges.
        # Prevents prompt injection from producing arbitrary contact data in the CRM.
        lead_signals = _validate_lead_signals(result.get("lead_signals", {}) or {})

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

        # Pre-fetch existing lead for Slack + HubSpot checks
        _existing_lead = await firestore_service.get_lead(request.session_id)

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
            if SLACK_NOTIFICATIONS_ENABLED and not current_lead.get("slack_notified"):
                collected = {f for f in LEAD_NOTIFY_FIELDS if current_lead.get(f)}
                if collected >= LEAD_NOTIFY_FIELDS:
                    # Sanitize free-text fields before including in Slack notification
                    # to prevent stored prompt injection from appearing in team channels.
                    _slack_lead = _sanitize_lead_for_downstream(current_lead)
                    sent = await slack_service.notify_new_lead(
                        request.session_id, _slack_lead
                    )
                    if sent:
                        await firestore_service.mark_lead_slack_notified(request.session_id)
                        lead_collected = True
                elif lead_signals.get("order_intent") == "HIGH" or (
                    int(current_lead.get("fleet_size") or 0) >= 50
                ):
                    _slack_lead = _sanitize_lead_for_downstream(current_lead)
                    await slack_service.notify_high_intent_lead(
                        request.session_id, _slack_lead
                    )

            # Log what's missing so we can debug gate failures
            if phase_str == "CLOSE_QUOTE" and not current_lead.get("hubspot_submitted"):
                missing = [f for f in HUBSPOT_REQUIRED_FIELDS if not current_lead.get(f)]
                if missing:
                    logger.info(f"HubSpot gate: missing fields {missing} for session {_sid(request.session_id)}")

            # HubSpot: submit to inbound_smb_fleets form when all required fields present
            if (
                phase_str == "CLOSE_QUOTE"
                and not current_lead.get("hubspot_submitted")
                and not current_lead.get("hubspot_permanently_failed")
                and _hubspot_retry_due(current_lead)
                and all(current_lead.get(f) for f in HUBSPOT_REQUIRED_FIELDS)
                and HUBSPOT_PORTAL_ID
                and HUBSPOT_FORM_ID
            ):
                try:
                    # Build summary + transcript from Firestore conversation
                    convo = await firestore_service.get_conversation(request.session_id)
                    messages_for_summary = (convo or {}).get("messages", [])
                    safe_lead = _sanitize_lead_for_downstream(current_lead)
                    if not all(safe_lead.get(f) for f in HUBSPOT_REQUIRED_FIELDS):
                        logger.warning(
                            f"HubSpot skipped after downstream sanitization removed required field "
                            f"for session {_sid(request.session_id)}"
                        )
                        return ChatResponse(
                            answer=answer,
                            session_id=request.session_id,
                            suggested_follow_ups=follow_ups,
                            lead_collected=lead_collected,
                            cta_type=cta_type,
                            quote_url=quote_url,
                        )
                    chatbot_summary = _build_chatbot_summary(safe_lead, messages_for_summary)

                    # Split full name into first / last; enforce field length limits
                    # before transmission to prevent oversized data reaching HubSpot.
                    name_parts = (safe_lead.get("contact_name") or "").split()
                    firstname = (name_parts[0] if name_parts else "")[:100]
                    lastname = (" ".join(name_parts[1:]) if len(name_parts) > 1 else "")[:100]
                    hs_email = (safe_lead.get("contact_email") or "")[:254]
                    hs_phone = (safe_lead.get("contact_phone") or "")[:20]
                    hs_company = (safe_lead.get("business_name") or "")[:200]

                    hs_fields = [
                        {"name": "firstname",           "value": firstname},
                        {"name": "lastname",            "value": lastname},
                        {"name": "email",               "value": hs_email},
                        {"name": "phone",               "value": hs_phone},
                        {"name": "company",             "value": hs_company},
                        {"name": "contact_channel",     "value": "Chat Bot"},
                        {"name": "chatbot_summary",     "value": chatbot_summary},
                    ]
                    # how_many_vehicles_ = fleet size; fall back to num_cameras if not separately captured
                    vehicle_count = safe_lead.get("fleet_size") or safe_lead.get("num_cameras")
                    hs_fields.append({"name": "how_many_vehicles_", "value": str(vehicle_count)})
                    # Optional fields
                    if safe_lead.get("industry"):
                        hs_fields.append({"name": "industry", "value": safe_lead["industry"]})

                    hubspot_payload = {
                        "fields": hs_fields,
                        "context": {
                            "pageUri": _hubspot_page_uri(http_request),
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
                            logger.info(f"HubSpot contact submitted for session {_sid(request.session_id)}")
                        elif _hr.status_code in (400, 401, 403, 404, 422):
                            # Permanent failure — misconfigured portal/form ID or invalid field data.
                            # Mark as permanently failed in Firestore so we don't retry on every message.
                            # Body not logged to avoid potential PII echo; check portal/form ID config.
                            await firestore_service.upsert_lead(
                                request.session_id, {"hubspot_permanently_failed": True}
                            )
                            logger.error(
                                f"HubSpot permanent error {_hr.status_code} for session {_sid(request.session_id)}: "
                                f"form submission rejected — check integration configuration"
                            )
                        elif _hr.status_code == 429 or 500 <= _hr.status_code < 600:
                            # Transient failure — rate limit or HubSpot/server issue.
                            # Cool down between attempts so every chat turn doesn't call HubSpot.
                            _update = _hubspot_failure_update(current_lead)
                            if _update.get("hubspot_permanently_failed"):
                                logger.error(
                                    f"HubSpot giving up after {_update['hubspot_retry_count']} transient failures "
                                    f"for session {_sid(request.session_id)}"
                                )
                            else:
                                logger.warning(
                                    f"HubSpot transient failure {_hr.status_code} "
                                    f"(attempt {_update['hubspot_retry_count']}/{HUBSPOT_RETRY_LIMIT}) "
                                    f"for session {_sid(request.session_id)}"
                                )
                            await firestore_service.upsert_lead(request.session_id, _update)
                        else:
                            await firestore_service.upsert_lead(
                                request.session_id, {"hubspot_permanently_failed": True}
                            )
                            logger.error(
                                f"HubSpot unexpected permanent error {_hr.status_code} "
                                f"for session {_sid(request.session_id)}"
                            )
                except Exception as hs_err:
                    is_transient = isinstance(
                        hs_err, (_httpx.TimeoutException, _httpx.NetworkError, _httpx.TransportError)
                    )
                    _update = _hubspot_failure_update(current_lead, permanent=not is_transient)
                    if _update.get("hubspot_permanently_failed"):
                        logger.error(
                            f"HubSpot giving up after {_update['hubspot_retry_count']} "
                            f"{'transient exceptions' if is_transient else 'non-transient exception'} "
                            f"for session {_sid(request.session_id)}: {hs_err}"
                        )
                    else:
                        logger.error(
                            f"HubSpot transient exception "
                            f"(attempt {_update['hubspot_retry_count']}/{HUBSPOT_RETRY_LIMIT}) "
                            f"for session {_sid(request.session_id)}: {hs_err}"
                        )
                    await firestore_service.upsert_lead(request.session_id, _update)

        return ChatResponse(
            answer=answer,
            session_id=request.session_id,
            suggested_follow_ups=follow_ups,
            lead_collected=lead_collected,
            cta_type=cta_type,
            quote_url=quote_url,
        )

    except Exception as e:
        logger.error(f"Chat error: {type(e).__name__}: {str(e)[:200]}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """
    Save user feedback (thumbs up/down) for a message.
    Public endpoint (public_api: true) — intentionally unauthenticated for customer access.
    """
    _validate_public_request(request.session_id, request.question)
    # Validate optional fields: answer and feedback_text can be empty but must be bounded
    if request.answer and len(request.answer) > 2000:
        raise HTTPException(status_code=400, detail="Invalid input")
    if request.feedback_text and len(request.feedback_text) > 1000:
        raise HTTPException(status_code=400, detail="Invalid input")
    try:
        feedback_id = await firestore_service.save_feedback(
            session_id=request.session_id,
            message_id=_safe_log_value(request.message_id, 100),
            question=_sanitize_downstream_text(request.question, 2000),
            answer=_sanitize_downstream_text(request.answer or "", 2000),
            rating=request.rating,
            feedback_text=_sanitize_downstream_text(request.feedback_text or "", 1000),
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
    logger.warning(f"CONFIG_CHANGE: {user} triggered config cache reload")
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
async def export_conversations(request: Request, limit: int = Query(default=25, ge=1, le=100), user: str = Depends(require_corp_export)):
    """Export full conversation sessions (with lead data) as a downloadable JSON file."""
    import json as _json
    from fastapi.responses import Response

    sessions = []
    summaries = await firestore_service.list_conversations(limit=limit)
    # Use X-Forwarded-For to get real client IP behind Cloud Run / load balancer
    client_ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown").split(",")[0].strip()
    client_ip = _safe_log_value(client_ip, 45)
    logger.warning(f"DATA_EXPORT: {user} from {client_ip} exported up to {limit} conversation records ({len(summaries)} found)")
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
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    conversation = await firestore_service.get_conversation(session_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


class ConversationRatingRequest(BaseModel):
    rating: Literal["thumbs_up", "thumbs_down"]
    notes: str = Field(default="", max_length=2000)
    # For thumbs_down: include a representative Q&A pair to run triage against
    question: str = Field(default="", max_length=2000)
    answer: str = Field(default="", max_length=5000)


@app.post("/api/admin/conversations/{session_id}/rate")
async def rate_conversation(
    session_id: str,
    request: ConversationRatingRequest,
    user: str = Depends(require_corp),
):
    """Rate a conversation and (for thumbs_down) trigger async Gemini triage."""
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
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
                    # Sanitize user-originated content before passing to triage LLM
                    # to prevent stored prompt injection from manipulating triage results.
                    result = await chat_service.triage_feedback(
                        question=chat_service._sanitize_input(request.question),
                        answer=chat_service._sanitize_input(request.answer),
                        admin_notes=chat_service._sanitize_input(request.notes),
                        faq_titles=faq_titles,
                        phase_names=phase_names,
                    )
                    # Validate triage output before writing to Firestore.
                    # Prevents stored prompt injection in the answer field from producing
                    # arbitrary data in the classification result.
                    _VALID_TRIAGE_RESOURCES = {"faq", "routing", "prompt", "behavior", "unknown"}
                    _triage_resource = result.get("resource", "unknown")
                    if _triage_resource not in _VALID_TRIAGE_RESOURCES:
                        _triage_resource = "unknown"
                    _triage_detail = str(result.get("detail") or "")[:500]
                    _triage_reasoning = str(result.get("reasoning") or "")[:1000]
                    await firestore_service.update_feedback_triage(
                        feedback_id=feedback_id,
                        triage_resource=_triage_resource,
                        triage_detail=_triage_detail,
                        triage_reasoning=_triage_reasoning,
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
async def get_config(user: str = Depends(require_prompt_admin)):
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


class FaqEntry(BaseModel):
    question: str = Field(max_length=500)
    answer: str = Field(max_length=5000)
    category: str = Field(default="", max_length=100)
    source: str = Field(default="", max_length=200)


class ConfigFaqsUpdate(BaseModel):
    faqs: list[FaqEntry]


class ConfigPromptsUpdate(BaseModel):
    core_prompt: str
    phase_prompts: dict
    # Explicit change-approval fields — required to prevent accidental/unauthorized changes.
    # The caller must state why they're changing the prompts and confirm their identity.
    change_reason: str = ""
    confirmed_by: str = ""  # Must match the authenticated user's email


@app.put("/api/admin/config/faqs")
async def update_faqs(request: ConfigFaqsUpdate, user: str = Depends(require_prompt_admin)):
    """Overwrite FAQ JSON in GCS and reload cache."""
    if len(request.faqs) > 500:
        raise HTTPException(status_code=400, detail="FAQ list exceeds maximum allowed entries (500)")
    for idx, faq in enumerate(request.faqs):
        _validate_prompt_content(faq.question or "", f"faqs[{idx}].question")
        _validate_prompt_content(faq.answer or "", f"faqs[{idx}].answer")
        _validate_prompt_content(faq.category or "", f"faqs[{idx}].category")
        _validate_prompt_content(faq.source or "", f"faqs[{idx}].source")
    try:
        logger.warning(f"CONFIG_CHANGE: {user} updated FAQs ({len(request.faqs)} entries)")
        storage.save_faqs(request.faqs)
        return {"status": "ok", "message": f"Saved {len(request.faqs)} FAQs and reloaded cache."}
    except RuntimeError as e:
        logger.error(f"Config update error: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


_PROMPT_FORBIDDEN_PATTERNS = [
    re.compile(r'<script[^>]*>', re.IGNORECASE),  # embedded script tags
    re.compile(r'javascript\s*:', re.IGNORECASE),  # JS protocol handlers
    re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]'),  # non-printable control characters
    # Prompt injection: classic override patterns that could subvert the sales agent
    re.compile(r'ignore\s+(all\s+)?(previous|prior|above)\s+instructions?', re.IGNORECASE),
    re.compile(r'disregard\s+(all\s+)?(previous|prior|above)\s+instructions?', re.IGNORECASE),
    re.compile(r'forget\s+(all\s+)?(previous|prior|above)\s+instructions?', re.IGNORECASE),
    re.compile(r'system\s+override', re.IGNORECASE),
    re.compile(r'you\s+are\s+now\s+(a\s+)?different', re.IGNORECASE),
    re.compile(r'new\s+persona\s*:', re.IGNORECASE),
]


def _validate_prompt_content(content: str, field_name: str) -> None:
    """Reject prompt content that contains binary data or known injection vectors."""
    if len(content.encode()) > _MAX_PROMPT_BYTES:
        raise HTTPException(status_code=400, detail=f"{field_name} exceeds maximum allowed size")
    for pattern in _PROMPT_FORBIDDEN_PATTERNS:
        if pattern.search(content):
            raise HTTPException(status_code=400, detail=f"{field_name} contains invalid content")


@app.put("/api/admin/config/prompts")
async def update_prompts(request: ConfigPromptsUpdate, user: str = Depends(require_prompt_admin)):
    """Overwrite core prompt and phase prompts in GCS and reload cache."""
    # Explicit change-approval gate: caller must acknowledge with a reason and their own email.
    if len(request.change_reason.strip()) < 10:
        raise HTTPException(status_code=400, detail="change_reason is required (minimum 10 characters)")
    if request.confirmed_by.strip().lower() != user.lower():
        raise HTTPException(status_code=400, detail="confirmed_by must match your authenticated user email")
    _validate_prompt_content(request.core_prompt, "core_prompt")
    # Validate phase keys to reject unknown/injected phase names
    from backend.conversation_router import ConversationPhase as _CP
    valid_phases = {p.value for p in _CP}
    for phase_key, phase_content in (request.phase_prompts or {}).items():
        if phase_key not in valid_phases:
            raise HTTPException(status_code=400, detail=f"Unknown phase: {phase_key}")
        _validate_prompt_content(phase_content or "", f"phase_prompt[{phase_key}]")
    try:
        logger.warning(f"CONFIG_CHANGE: {user} updated core prompt and phase prompts")
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
