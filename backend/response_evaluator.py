"""
Rule-based response evaluator for the Nexar Fleet sales agent.
Runs after Gemini generates a response, before it's returned to the user.
Auto-corrects simple violations; flags complex ones for regeneration.
"""
import re
import logging
from typing import Dict, List, Optional

from .conversation_router import ConversationPhase

logger = logging.getLogger(__name__)


FORBIDDEN_OPENERS = [
    "absolutely!", "certainly!", "great!", "sure!", "of course!",
    "happy to help", "good question", "thanks for clarifying",
    "excellent!", "perfect!", "wonderful!", "awesome!", "fantastic!",
    "of course,", "great,", "sure,", "absolutely,",
]

# Patterns that indicate a CTA push (sales team reach out) in the answer text
_CTA_PUSH_PATTERNS = [
    r"want me to.{0,50}(reach out|get back|follow up|team reach)",
    r"have someone.{0,40}reach out",
    r"have our (sales )?team.{0,40}(reach out|follow up|contact)",
    r"our (sales )?team.{0,40}(reach out|will be in touch|get back to you)",
    r"want me to put together a.{0,40}quote",
    r"put together a.{0,20}quote",
    r"should i put together",
    r"i can get you a quote",
]

# Patterns for known fields — if user already provided these, bot shouldn't ask again
_KNOWN_INFO_QUESTION_PATTERNS = {
    "fleet_size": [
        r"\bhow many vehicles\b",
        r"\bhow large is your fleet\b",
        r"\bfleet size\b",
        r"\bhow many (cars|trucks|vans|units)\b",
    ],
    "contact_email": [
        r"\bbest email\b",
        r"\bwhat.{0,10}(your )?email\b",
        r"\beach you\b",
    ],
    "contact_name": [
        r"\bwhat.{0,10}(your )?name\b",
        r"\bfull name\b",
    ],
}


class EvaluationResult:
    def __init__(self):
        self.issues: List[str] = []
        self.auto_corrections: Dict[str, str] = {}
        self.needs_regeneration: bool = False
        self.regeneration_hint: Optional[str] = None

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    def __repr__(self):
        return f"EvaluationResult(issues={self.issues}, needs_regen={self.needs_regeneration})"


def evaluate_response(
    parsed: Dict,
    phase: ConversationPhase,
    conversation_history: Optional[List],
) -> EvaluationResult:
    """
    Evaluate a parsed Gemini response for rule violations.
    Returns EvaluationResult describing what (if anything) needs fixing.
    """
    result = EvaluationResult()
    answer: str = parsed.get("answer", "")

    # --- Check 1: Forbidden opener ---
    answer_stripped = answer.lstrip()
    answer_lower = answer_stripped.lower()
    for opener in FORBIDDEN_OPENERS:
        if answer_lower.startswith(opener.lower()):
            result.issues.append(f"forbidden_opener:{opener}")
            # Strip the opener and leading punctuation/whitespace
            tail = answer_stripped[len(opener):]
            tail = re.sub(r'^[\s,!.—\-]+', '', tail)
            if tail:
                tail = tail[0].upper() + tail[1:]
            result.auto_corrections["answer"] = tail
            logger.info(f"Evaluator: stripped forbidden opener '{opener}'")
            break

    # Work on the answer after any opener correction
    working_answer = result.auto_corrections.get("answer", answer)

    # --- Check 2: CTA push during camera selection ---
    if phase == ConversationPhase.QUALIFY_CAMERA_SELECTION:
        working_lower = working_answer.lower()
        for pattern in _CTA_PUSH_PATTERNS:
            if re.search(pattern, working_lower):
                result.issues.append("cta_during_camera_selection")
                result.auto_corrections["cta_type"] = None

                # Try to strip the CTA if it's isolated in the last sentence
                sentences = re.split(r'(?<=[.!?])\s+', working_answer.strip())
                last_sentence_lower = sentences[-1].lower() if sentences else ""
                if len(sentences) > 1 and re.search(pattern, last_sentence_lower):
                    cleaned = " ".join(sentences[:-1]).strip()
                    result.auto_corrections["answer"] = cleaned
                    logger.info("Evaluator: stripped trailing CTA from camera selection response")
                else:
                    # CTA embedded in body — regenerate
                    result.needs_regeneration = True
                    result.regeneration_hint = (
                        "You are in the camera selection qualifying flow (Q1 or Q2). "
                        "Do NOT push a quote or demo CTA. The qualifying question is the "
                        "forward-moving question. End with Q1 or Q2 only. Set cta_type to null."
                    )
                    logger.info("Evaluator: flagged CTA mid-camera-selection for regeneration")
                break

    # Re-read working answer after CTA correction
    working_answer = result.auto_corrections.get("answer", answer)

    # --- Check 3: Repeating known info ---
    if conversation_history and not result.needs_regeneration:
        known = _extract_known_fields(conversation_history)
        working_lower = working_answer.lower()

        for field, patterns in _KNOWN_INFO_QUESTION_PATTERNS.items():
            if not known.get(field):
                continue  # field not known yet — no issue
            for pat in patterns:
                if re.search(pat, working_lower):
                    # Only flag if the repeated question is in the last sentence
                    # (i.e., it's the primary ask, not a passing mention)
                    sentences = re.split(r'(?<=[.!?])\s+', working_lower.strip())
                    if sentences and re.search(pat, sentences[-1]):
                        result.issues.append(f"repeated_known_field:{field}")
                        result.needs_regeneration = True
                        result.regeneration_hint = (
                            f"The customer already told you their {field.replace('_', ' ')}. "
                            f"Do not ask for it again. Ask something new that moves the "
                            f"conversation forward."
                        )
                        logger.info(f"Evaluator: flagged repeat of known field '{field}'")
                    break

    # --- Check 3b: Repeating a question the user just ignored ---
    # If the last assistant message ended with a question and the user's reply didn't answer it
    # (i.e., they changed topic), don't ask the same question again.
    if conversation_history and len(conversation_history) >= 2 and not result.needs_regeneration:
        # Find the last assistant message
        last_assistant_msg = None
        for msg in reversed(conversation_history):
            if msg.role == "assistant":
                last_assistant_msg = msg.content
                break

        if last_assistant_msg:
            # Extract the question from the last assistant message (last sentence ending in ?)
            last_sentences = re.split(r'(?<=[.!?])\s+', last_assistant_msg.strip())
            last_question = None
            for s in reversed(last_sentences):
                if s.strip().endswith('?'):
                    last_question = s.strip().lower()
                    break

            # Check if the new answer repeats that same question
            if last_question and len(last_question) > 20:
                new_sentences = re.split(r'(?<=[.!?])\s+', working_answer.strip())
                new_question = None
                for s in reversed(new_sentences):
                    if s.strip().endswith('?'):
                        new_question = s.strip().lower()
                        break

                if new_question and _questions_are_similar(last_question, new_question):
                    result.issues.append("repeated_ignored_question")
                    result.needs_regeneration = True
                    result.regeneration_hint = (
                        "You already asked that question in your previous message and the customer "
                        "responded with something else — they're not engaging with it. Drop it and "
                        "move forward. Ask something different or answer what they said."
                    )
                    logger.info(f"Evaluator: flagged repeated ignored question")

    # --- Check 4: Shipping address asked during contact collection ---
    if phase == ConversationPhase.CLOSE_QUOTE and not result.needs_regeneration:
        working_answer = result.auto_corrections.get("answer", answer)
        if "shipping address" in working_answer.lower():
            result.issues.append("shipping_address_in_close")
            result.needs_regeneration = True
            result.regeneration_hint = (
                "You are collecting contact details so the sales team can reach out. "
                "NEVER ask for a shipping address. Ask for the next missing field instead "
                "(full name, email address, phone number, or business name)."
            )
            logger.info("Evaluator: flagged shipping address request in CLOSE_QUOTE for regeneration")

    # --- Check 5: CTA redirect asked during contact collection ---
    if phase == ConversationPhase.CLOSE_QUOTE and not result.needs_regeneration:
        working_answer = result.auto_corrections.get("answer", answer)
        working_lower = working_answer.lower()
        for pattern in _CTA_PUSH_PATTERNS:
            if re.search(pattern, working_lower):
                result.issues.append("cta_redirect_during_contact_collection")
                result.needs_regeneration = True
                result.regeneration_hint = (
                    "The customer has already agreed to have the sales team reach out. "
                    "Do not ask again if they want a quote or demo. Stay focused: ask for the next missing field "
                    "(full name, email address, phone number, or business name)."
                )
                logger.info("Evaluator: flagged CTA redirect during CLOSE_QUOTE for regeneration")
                break

    return result


def _questions_are_similar(q1: str, q2: str) -> bool:
    """
    Returns True if two questions are substantially the same.
    Uses word overlap — if 60%+ of meaningful words match, they're similar.
    """
    stopwords = {'a', 'an', 'the', 'is', 'are', 'do', 'you', 'your', 'me', 'for',
                 'to', 'of', 'in', 'on', 'at', 'what', 'how', 'can', 'i', 'it',
                 'this', 'that', 'and', 'or', 'with', 'about', 'any', 'just', 'e.g'}
    words1 = {w for w in re.findall(r'\b\w+\b', q1) if w not in stopwords and len(w) > 2}
    words2 = {w for w in re.findall(r'\b\w+\b', q2) if w not in stopwords and len(w) > 2}
    if not words1 or not words2:
        return False
    overlap = len(words1 & words2)
    smaller = min(len(words1), len(words2))
    return overlap / smaller >= 0.6


def _extract_known_fields(history: List) -> Dict[str, Optional[str]]:
    """
    Scan conversation history for fields the user has already provided.
    Returns dict of field -> truthy value if known, None if unknown.
    """
    known: Dict[str, Optional[str]] = {
        "fleet_size": None,
        "contact_email": None,
        "contact_name": None,
    }

    user_text = " ".join(m.content for m in history if m.role == "user")
    assistant_text = " ".join(m.content for m in history if m.role == "assistant")

    # Email: look for email pattern in user messages
    if re.search(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b', user_text):
        known["contact_email"] = "provided"

    # Fleet size: number followed by vehicle type
    if re.search(
        r'\b\d+\s*(vehicle|truck|van|car|fleet|unit|bus|bike)',
        user_text,
        re.IGNORECASE,
    ):
        known["fleet_size"] = "provided"

    # Name: check if assistant has already addressed the customer by name
    # Pattern: "Thanks, [Name]" or "Hi, [Name]" in assistant messages
    name_match = re.search(
        r'\b(thanks|thank you|hi|hey|great),?\s+([A-Z][a-z]{1,20})\b',
        assistant_text,
    )
    if name_match:
        known["contact_name"] = name_match.group(2)

    return known
