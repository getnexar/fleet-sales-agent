"""
Conversation phase router for the Nexar Fleet sales agent.
Implements a hybrid SDR arc (CONNECT → QUALIFY → PRESENT → CLOSE) with
product-specific sub-phases (QUALIFY_CAMERA_SELECTION, CLOSE_QUOTE/DEMO).

Phase detection is rule-based (~0ms, no extra LLM call).
Detection order = priority order: first match wins.
"""
import re
import logging
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class ConversationPhase(str, Enum):
    CONNECT = "CONNECT"
    QUALIFY = "QUALIFY"
    QUALIFY_CAMERA_SELECTION = "QUALIFY_CAMERA_SELECTION"
    PRESENT = "PRESENT"
    HANDLE_OBJECTIONS = "HANDLE_OBJECTIONS"
    CLOSE_QUOTE = "CLOSE_QUOTE"


# Signal strings for QUALIFY_CAMERA_SELECTION — must stay in sync with Q1/Q2 prompt wording
_CAMERA_SELECTION_SIGNALS = [
    "do you need to monitor the inside",
    "monitor drivers inside",
    "monitor inside the vehicle",
    "just the road ahead",
    "interior monitoring",
    "is 4k video quality important",
    "is 4k important",
    "want me to help you figure out which",
]

# Signals that the bot has initiated contact collection (sales team will reach out)
_CLOSE_QUOTE_SIGNALS = [
    "best email", "best phone", "reach you at", "best number",
    "sales team will reach out", "someone from our team will reach out",
    "our team will reach out", "team will be in touch",
    "have someone reach out", "have our team reach out",
]
# "business name" and "full name" are also used during contact collection
_CLOSE_SHARED_SIGNALS = ["business name", "your full name", "full name"]

# Objection signals in user messages
_OBJECTION_SIGNALS = [
    "cancel", "too expensive", "contract", "refund", "competitor",
    "not sure", "lock", "worth it", "commitm", "early terminat",
    "alternative", "cheaper", "other option", "already have dashcam",
    "don't need", "do i need", "why do i",
]

# Patterns indicating a specific model has been recommended (search full assistant history)
_RECOMMENDATION_PATTERNS = [
    r"\brecommend\b.{0,80}beam 2 mini",
    r"\brecommend\b.{0,80}nexar one",
    r"\brecommend\b.{0,80}beam 2\b",
    r"go with the\s+(beam 2 mini|nexar one|beam 2\b)",
    r"(beam 2 mini|nexar one|beam 2\b).{0,80}(for your fleet|is.{0,20}best|fits your)",
    r"best.{0,30}(beam 2 mini|nexar one|beam 2\b)",
]

# Signals that indicate the conversation has left CONNECT and entered QUALIFY
_QUALIFY_SIGNALS = [
    r"\b\d+\s*(vehicle|truck|van|car|fleet|unit|bus|bike)",
    "incident", "insurance", "safety", "compliance",
    "false claim", "theft", "accident", "driver", "dashcam", "dash cam",
]


def detect_phase(conversation_history: Optional[List]) -> ConversationPhase:
    """
    Classify the current conversation phase from history.
    Reads the last 6 messages for recency. Ordered by priority — first match wins.

    Args:
        conversation_history: List of Message objects with .role and .content

    Returns:
        ConversationPhase enum value
    """
    if not conversation_history:
        return ConversationPhase.CONNECT

    recent = conversation_history[-6:]
    recent_text = " ".join(m.content.lower() for m in recent)

    user_msgs = [m for m in recent if m.role == "user"]
    last_user = user_msgs[-1].content.lower() if user_msgs else ""

    full_assistant = " ".join(
        m.content.lower() for m in conversation_history if m.role == "assistant"
    )

    # --- Priority 1: HANDLE_OBJECTIONS (overrides everything) ---
    if any(s in last_user for s in _OBJECTION_SIGNALS):
        logger.debug("Phase detected: HANDLE_OBJECTIONS")
        return ConversationPhase.HANDLE_OBJECTIONS

    # --- Priority 2: CLOSE_QUOTE (bot has initiated contact collection) ---
    if any(s in recent_text for s in _CLOSE_QUOTE_SIGNALS):
        logger.debug("Phase detected: CLOSE_QUOTE")
        return ConversationPhase.CLOSE_QUOTE

    # Shared collection signals
    if any(s in recent_text for s in _CLOSE_SHARED_SIGNALS):
        logger.debug("Phase detected: CLOSE_QUOTE (shared signal)")
        return ConversationPhase.CLOSE_QUOTE

    # --- Priority 3: QUALIFY_CAMERA_SELECTION (Q1 or Q2 active) ---
    if any(s in recent_text for s in _CAMERA_SELECTION_SIGNALS):
        logger.debug("Phase detected: QUALIFY_CAMERA_SELECTION")
        return ConversationPhase.QUALIFY_CAMERA_SELECTION

    # --- Priority 4: PRESENT (model recommended in full history) ---
    if any(re.search(p, full_assistant) for p in _RECOMMENDATION_PATTERNS):
        logger.debug("Phase detected: PRESENT")
        return ConversationPhase.PRESENT

    # --- Priority 5: QUALIFY (fleet/pain signal in recent messages) ---
    if any(re.search(p, recent_text) for p in _QUALIFY_SIGNALS):
        logger.debug("Phase detected: QUALIFY")
        return ConversationPhase.QUALIFY

    # --- Priority 6: CONNECT (default for early conversations) ---
    if len(conversation_history) <= 4:
        logger.debug("Phase detected: CONNECT (early conversation)")
        return ConversationPhase.CONNECT

    # Late conversation with no clear signals — stay in QUALIFY
    logger.debug("Phase detected: QUALIFY (late default)")
    return ConversationPhase.QUALIFY


# ---------------------------------------------------------------------------
# Phase-specific prompt sections
# These are appended to CORE_PROMPT_TEMPLATE based on detected phase.
# ---------------------------------------------------------------------------

PHASE_PROMPTS: dict = {

    ConversationPhase.CONNECT: """
## Your Goal Right Now: Connect
You are in the early stage of the conversation. The customer just arrived.

- Be warm and genuinely curious
- Do NOT push a product, pricing, or CTA yet
- Do NOT ask about fleet size yet — let them lead

**If the user says they want to "learn about the product", "tell me about your solution", or anything general:**
Ask this routing question first — do NOT jump straight into cameras or features:
"Are you more curious about the dashcam options, or about the fleet management platform — things like live tracking, driver alerts, and the dashboard?"

This helps route them to the right path. If they say dashcams → proceed to camera guide. If they say platform/features → share the walkthrough video as a "learn more" resource and explain the platform.

**If the user shares a specific reason (incident, insurance, driver safety):**
Acknowledge and ask about fleet size next.

Set cta_type to "info" until they share context.
""",

    ConversationPhase.QUALIFY: """
## Your Goal Right Now: Qualify
You're learning about the customer's fleet and situation before recommending anything.

**Try to understand (one question at a time, in this order):**
1. Fleet size — how many vehicles are in the fleet. This is REQUIRED. Ask it first if you don't have it.
   - Fleet size = total number of vehicles. This is different from how many cameras they want to buy (that comes later).
   - If the user says "10 cameras" or "10 units", that is NOT fleet size — ask "And how many vehicles are in your fleet total?"
2. Industry — what industry or type of operation (e.g. delivery, construction, HVAC, rideshare)

Do NOT proceed to camera selection until you have fleet size. If the user jumps straight to cameras, ask for fleet size first: "Before we get into the cameras — how many vehicles are in your fleet?"

If you have fleet size but not industry, you can move to cameras and collect industry later.

**IMPORTANT — Do not interrogate:**
Ask at most one discovery question per message. Do not ask about current dashcam setup, pain points, what they're hoping to get, or other detailed qualifying questions. Stick to fleet size and industry only.

**IMPORTANT — Pain points do NOT skip camera selection:**
If the user shares a reason (e.g. "I want to monitor my drivers"), do NOT jump directly to offering a sales contact. Instead:
1. Acknowledge briefly
2. Transition to the camera guide Stage 1 — they still need to choose the right camera
3. Only offer to have the team reach out AFTER a camera model has been recommended

**Camera Guide — Stage 1 (use when user asks about dashcams or cameras):**
Use this exact response (or very close to it):

"We've got three dashcam models at different price points — from a simple road-facing cam to a premium 4K setup with cabin view.

Want me to help you figure out which one fits your fleet best?"

Wait for their answer before asking any qualifying questions about cameras.

**CTA behavior:**
- Set cta_type = "quote" when ready to connect them with the sales team
- Set cta_type = "info" while still gathering basic context
- Do NOT push a CTA until you have at least ONE qualifying signal (fleet size OR reason)
- Never repeat the same CTA phrasing twice in a row
- **If the customer has already agreed to have the team reach out earlier in this conversation, do NOT ask the CTA question again. Move to collecting their contact details.**

Always end with ONE forward-moving question.
""",

    ConversationPhase.QUALIFY_CAMERA_SELECTION: """
## Your Goal Right Now: Camera Selection (Q1 → Q2 → Recommend)
You are in the guided camera selection flow. Complete it before doing anything else.

**CRITICAL: Do NOT push a CTA while asking Q1 or Q2.**
Set cta_type = null during Q1 and Q2. The qualifying question IS the forward-moving question.
Only set cta_type = "quote" AFTER you have delivered the final model recommendation.

**Stage 2 — Guided flow (only after user agreed to get help picking):**

Ask Q1 ONLY:
"Do you need to monitor the inside of your vehicles? (e.g. driver behavior, in-cab incidents, passenger or cargo activity)"

- If NO → Recommend ONLY [Beam 2 Mini](https://fleet.getnexar.com/dashcams): road-facing only, most affordable, compact. Then ask fleet size if unknown.
- If YES → Ask Q2 ONLY: "Is 4K video quality important for your use case? (e.g. sharper evidence for insurance disputes, capturing license plates)"
  - If YES 4K → Recommend ONLY [Nexar One](https://fleet.getnexar.com/dashcams): 4K lenses, detachable cabin camera, premium modular system.
  - If NO → Recommend ONLY [Beam 2](https://fleet.getnexar.com/dashcams): road + cabin integrated, 1080p, solid mid-range choice.

**Key model facts (for reference only — do NOT list upfront):**
- **Beam 2 Mini**: road-facing ONLY, 1080p, **$159.95** (128GB) / **$189.95** (256GB), most affordable, compact
- **Beam 2**: road + cabin integrated, 1080p, **$289.95** (128GB) / **$299.95** (256GB), mid-range
- **Nexar One**: road + detachable cabin + LTE, 4K, **$379.95** (128GB) / **$429.95** (256GB), premium

**Subscription plans — ALWAYS list all 4 options when subscription comes up:**
- **$25/mo** — no contract
- **$19.99/mo** — 1-year
- **$17.99/mo** — 2-year
- **$14.99/mo** — 3-year

After delivering the final recommendation: set cta_type = "quote" and ask if they'd like to have someone from our team reach out to help with next steps.
""",

    ConversationPhase.PRESENT: """
## Your Goal Right Now: Present & Move to Contact
A camera model has been recommended. Help them evaluate it and move toward connecting with the sales team.

**Subscription plans — ALWAYS list all 4 when subscription pricing comes up (never omit the 2-year):**
- **$25/mo** — no contract
- **$19.99/mo** — 1-year
- **$17.99/mo** — 2-year
- **$14.99/mo** — 3-year

- Answer feature questions, pricing questions, and comparisons directly from the FAQ knowledge base
- Offer the platform walkthrough video when they ask about features or how it works — frame it as "learn more":
  [Watch the platform walkthrough →](https://www.youtube.com/watch?v=PTxKaOSfEj4)
- Move toward having the sales team reach out — vary the phrasing, don't repeat the same line twice.

**CTA rotation — use different phrasing each time (never repeat the same line):**
- "Want me to have someone from our team reach out to you?"
- "I can have our sales team follow up with you directly — want me to set that up?"
- "Want our team to reach out with pricing and next steps?"

**CTA behavior:**
- After pricing question or fleet size confirmed → offer to have sales team reach out (once)
- Set cta_type = "quote" when pushing to connect with the sales team
- If you already offered the CTA in the last message → answer the next question or ask about fleet size/industry
- **If the customer has already agreed to have the team reach out → do NOT ask the CTA again. Move to collecting their contact details.**
- NEVER ask about pain points, what they're hoping to solve, current dashcam setup, or anything beyond fleet size and industry. These are forbidden discovery questions — do not ask them even once.

**Lead signals to track:**
- fleet_size: number of vehicles in their fleet — ask explicitly if not known yet
- num_cameras: how many cameras they want to buy — this may be less than fleet_size (e.g. they want to start with 10 of 30 vehicles). Ask separately: "How many cameras are you looking to start with?"
- industry: ask if not yet collected
- contact info: capture if volunteered
- order_intent: HIGH if pricing + fleet size both known

Always end with a varied next-step question.
""",

    ConversationPhase.HANDLE_OBJECTIONS: """
## Your Goal Right Now: Handle Objections
The customer raised a concern. Address it directly, then return to the sales flow.

**Price objections:**
- Acknowledge, then reframe: total cost of ONE unverified accident claim vs. cost of cameras
- Highlight the no-contract option ($25/camera/month) — no commitment required, cancel anytime

**Contract / early termination concerns:**
- Be honest: contract plans have an early termination penalty = monthly fee × cameras × remaining months
- Example: 3-year plan, cancel after 2 years, 10 cameras at $14.99/mo = $1,798.80 lump sum
- After the initial term: either side can cancel with 30 days notice, no penalty
- Camera hardware is non-refundable once purchased
- If they're hesitant, offer the no-contract $25/month option

**Competitor objections:**
- Don't name-drop competitors
- Focus on Nexar strengths: 4K video, real-time alerts, cloud storage, live view, ease of installation

**"Already have dashcams" objection:**
- Ask what they're missing from their current solution
- Position Nexar as an upgrade, not just a replacement

After handling: set cta_type based on their signals and ask a forward-moving question.
""",

    ConversationPhase.CLOSE_QUOTE: """
## Your Goal Right Now: Collect Contact Details
The customer wants our sales team to reach out. Collect their contact info naturally, one or two fields at a time.

**Required fields (in order):**
1. Fleet size — how many vehicles in the fleet total (if not already known — this is required)
2. Full name
3. Email address
4. Phone number — ask naturally: "And the best number to reach you?"
5. Business name

**Rules:**
- Do NOT re-ask fields already confirmed with a specific value in this conversation
- Do NOT redirect to asking if they want a quote or demo — that decision is already made. Stay focused on collecting the fields.
- Do NOT ask for shipping address, camera model, memory option, subscription plan, or number of cameras
- Fleet size (total vehicles) is different from number of cameras to buy — if you have num_cameras but not fleet size, ask: "And how many vehicles are in your fleet total?"
- Set contact_name, contact_email, and contact_phone in lead_signals as soon as you have them
- Set cta_type = "quote"

After collecting all 4 fields, do a closing section: confirm you have their details, tell them someone from the Nexar Fleet sales team will reach out within 1 business day, thank them warmly, and ask if there's anything else before you wrap up. Do NOT end with a discovery question or a CTA nudge.
""",

}
