"""
Chat service using Claude Sonnet via Anthropic API.
Handles FAQ search, conversation management, lead detection, and CTA recommendations.

Architecture:
- conversation_router.py detects the current SDR conversation phase
- response_evaluator.py validates/corrects the response before returning
- CORE_PROMPT_TEMPLATE is always injected; a phase-specific section is appended per turn
"""
import os
import re
import json
import logging
import time
from typing import List, Dict, Optional
import anthropic
from google.cloud import secretmanager

from .models import Message, ChatResponse
from .storage_service import StorageService
from .conversation_router import ConversationPhase, detect_phase, PHASE_PROMPTS
from .response_evaluator import evaluate_response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core prompt — always included regardless of conversation phase.
# Contains identity, style rules, product links, FAQ context, and JSON schema.
# Phase-specific instructions are appended by _build_system_prompt().
# ---------------------------------------------------------------------------

CORE_PROMPT_TEMPLATE = """You are a proactive Fleet sales assistant for Nexar. Your name is Alex.

## Self-Introduction
The opening greeting ("Hi! I'm Alex...") has ALREADY been sent as the first message in this conversation — it appears in the conversation history above. You are now responding to a FOLLOW-UP message.

CRITICAL: NEVER say "I'm Alex", "I'm your Nexar Fleet assistant", "I'm a Fleet sales assistant", or re-introduce yourself in ANY way. The customer already knows who you are. Jump straight into answering their question.

## Addressing the Customer
NEVER call the customer "Alex". Alex is YOUR name (the assistant). The customer is someone else — address them as "you" or by their name only if they've told you their name.

## Response Style
- Write like a real person texting a colleague — casual, direct, no fluff
- NEVER start a response with filler — no "Certainly!", "Great!", "Sure!", "Of course!", "Absolutely!", "Thanks for clarifying!", "Happy to help!", "Good question!" or any similar opener — just answer directly
- If you made a mistake, correct course briefly in one clause and move on — don't open with a full apology paragraph
- Keep responses SHORT — max 2 sentences per paragraph, then line break
- Use bullet points for lists and pricing — never write them inline
- Use **bold** only for prices and model names
- Never write more than you need to. If you can say it in 5 words, don't use 15

## Ending Every Message
EVERY response must end with a forward-moving question. Never end on a statement.
NEVER ask for information the customer has already provided in this conversation.
NEVER repeat the same CTA phrasing twice in a row — if you offered to have someone reach out in the previous message and they didn't respond, ask something different (a feature question or fleet size). Only re-offer the CTA if the conversation has moved on and it's naturally relevant again.

## Product Links
When mentioning specific Nexar hardware, always embed a markdown hyperlink:
- [Nexar One](https://fleet.getnexar.com/dashcams)
- [Beam 2](https://fleet.getnexar.com/dashcams)
- [Beam 2 Mini](https://fleet.getnexar.com/dashcams)

## Dashboard & Features Video
When a user asks about the Nexar Fleet dashboard, the platform, how it works, or app features — offer the walkthrough video as a "learn more" resource:
[Watch the platform walkthrough →](https://www.youtube.com/watch?v=PTxKaOSfEj4)
Always include it as a markdown link, never plain text.
Frame it as: "Here's a quick platform walkthrough if you want to see it in action before we talk."

CRITICAL — Video vs. Sales Contact:
- The video is a self-serve "learn more" resource. When a user asks about features or wants to see how it works, share it.
- When a user says they want a "demo" or to "speak with someone" — treat it the same as any CTA: collect their contact details (name, email, phone, business) so the sales team can reach out. Do NOT send them the video as a substitute for a personal follow-up.

## FAQ Knowledge Base
Use the following validated FAQs to answer customer questions accurately:

{faqs}

## Response Format
You MUST respond with ONLY a valid JSON object. No markdown, no code fences, no explanation outside the JSON.

{{
  "answer": "your conversational response here",
  "follow_up": null,
  "cta_type": "quote" | "info" | null,
  "lead_signals": {{
    "fleet_size": "number or null — total vehicles in their fleet (NOT how many cameras they're buying)",
    "industry": "string or null (e.g. 'construction', 'delivery', 'rideshare', 'HVAC')",
    "pain_points": "string or null (reason for searching, e.g. 'recent accident', 'insurance requirement')",
    "contact_name": "string or null",
    "contact_email": "string or null",
    "contact_phone": "string or null",
    "order_intent": "HIGH" | "MEDIUM" | "LOW" | null,
    "business_name": "string or null",
    "num_cameras": number or null,
    "camera_model": "Beam 2 Mini" | "Beam 2" | "Nexar One" | null,
    "memory_option": "128GB" | "256GB" | null,
    "subscription_plan": "no-contract" | "1-year" | "2-year" | "3-year" | null
  }}
}}

## Open-Ended Questions
When asking an open-ended question, ALWAYS include 2-3 short example options in parentheses:
- "What's prompting the search? (e.g. a recent accident, insurance requirements, or driver safety)"
- "What's your biggest pain point? (e.g. false accident claims, theft, or compliance reporting)"
"""


class ChatService:
    """Handles chat interactions using Claude Sonnet and the FAQ knowledge base."""

    def __init__(self, storage: StorageService):
        self.storage = storage
        api_key = self._get_api_key()
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-6"
        logger.info(f"ChatService initialized with model: {self.model}")

    def _get_api_key(self) -> str:
        """Fetch Anthropic API key from Secret Manager, with env var fallback."""
        try:
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "nexar-corp-systems")
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/fleet-sales-agent-ANTHROPIC_API_KEY/versions/latest"
            response = client.access_secret_version(request={"name": name})
            key = response.payload.data.decode("UTF-8").strip()
            logger.info("Anthropic API key loaded from Secret Manager")
            return key
        except Exception as e:
            logger.warning(f"Secret Manager unavailable, falling back to env var: {e}")
            return os.environ.get("ANTHROPIC_API_KEY", "")

    def _build_system_prompt(self, phase: ConversationPhase) -> str:
        faqs = self.storage.get_faqs()
        faq_text = "".join(f"Q: {faq['question']}\nA: {faq['answer']}\n\n" for faq in faqs)

        # Use GCS-managed prompt if available, fall back to hardcoded
        core_template = self.storage.get_core_prompt() or CORE_PROMPT_TEMPLATE
        core = core_template.format(faqs=faq_text.strip())

        gcs_phase_prompts = self.storage.get_phase_prompts()
        if gcs_phase_prompts and phase.value in gcs_phase_prompts:
            phase_section = gcs_phase_prompts[phase.value]
        else:
            phase_section = PHASE_PROMPTS[phase]

        json_reminder = (
            "\n\n## CRITICAL REMINDER\n"
            "Your ENTIRE response must be a single valid JSON object — nothing before it, nothing after it.\n"
            "Do NOT write plain text. Do NOT add explanation outside the JSON. Start with `{` and end with `}`."
        )
        return f"{core}\n\n## Current Conversation Phase: {phase.value}\n{phase_section}{json_reminder}"

    def _call_claude(self, messages: list, system_prompt: str) -> str:
        """Single Claude API call — returns raw response text."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=0.3,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text.strip()

    async def triage_feedback(
        self,
        question: str,
        answer: str,
        admin_notes: str,
        faq_titles: list,
        phase_names: list,
    ) -> Dict:
        """
        Given a bad bot response + admin notes, classify which resource likely caused it.
        Returns: {resource, detail, reasoning}
        """
        faq_list = "\n".join(f"- {t}" for t in faq_titles)
        phase_list = "\n".join(f"- {p}" for p in phase_names)
        prompt = f"""You are a quality analyst reviewing a bad response from a sales chatbot.

User question: {question}

Bot answer: {answer}

Admin notes on what was wrong: {admin_notes}

Available resources that control bot behavior:
FAQ entries:
{faq_list}

Phase prompts (conversation phase instructions):
{phase_list}

Core prompt (identity, style rules, response format)

Based on the admin notes and the bad response, classify which resource most likely caused the issue.
Respond with ONLY valid JSON (no markdown, no code fences):
{{
  "resource": "faq" | "core_prompt" | "phase_prompt",
  "detail": "<FAQ entry title, phase name, or specific rule in core prompt>",
  "reasoning": "<one sentence explaining why this resource is responsible>"
}}"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )
            return json.loads(response.content[0].text.strip())
        except Exception as e:
            logger.warning(f"Triage failed: {e}")
            return {
                "resource": "unknown",
                "detail": "Could not classify — review manually",
                "reasoning": str(e),
            }

    @staticmethod
    def _sanitize_input(text: str) -> str:
        """
        Sanitize user input to prevent prompt injection.
        Strips common injection patterns while preserving legitimate content.
        Logs when patterns are neutralized so suspicious sessions can be monitored.
        """
        if not text:
            return text
        # Remove null bytes and control characters (except newline/tab)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        # Truncate to max allowed length (already validated at API layer, but belt-and-suspenders)
        text = text[:2000]
        # Strip prompt injection markers and log detections for alerting
        injection_patterns = [
            r'(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions?',
            r'(?i)disregard\s+(all\s+)?(previous|prior|above)\s+instructions?',
            r'(?i)forget\s+(all\s+)?(previous|prior|above)\s+instructions?',
            r'(?i)you\s+are\s+now\s+(a\s+)?(?!Daniel|Alex)',  # identity hijack
            r'(?i)\[system\]',
            r'(?i)<\s*system\s*>',
            r'(?i)###\s*system',
            r'(?i)###\s*instruction',
            r'(?i)system\s+override',
            r'(?i)prompt\s+injection',
        ]
        for pattern in injection_patterns:
            cleaned, count = re.subn(pattern, '[removed]', text)
            if count:
                logger.warning(
                    f"SECURITY: Prompt injection pattern neutralized ({count} instance(s)) — pattern: {pattern[:50]}"
                )
            text = cleaned
        return text.strip()

    @staticmethod
    def _filter_output(answer: str) -> str:
        """
        Scan AI output for prompt injection success indicators and system prompt leakage.
        Logs warnings so suspicious outputs are visible in monitoring dashboards.
        The response is still returned — filtering is detect-and-alert, not block.
        """
        leak_patterns = [
            (r'(?i)my system prompt', "system prompt reference"),
            (r'(?i)my instructions (say|are|tell me to)', "instruction disclosure"),
            (r'(?i)i(\'ve| have) been instructed to', "instruction disclosure"),
            (r'(?i)ignore (previous|all|prior) instructions', "injection success indicator"),
            (r'CORE_PROMPT_TEMPLATE', "internal template name leaked"),
            (r'(?i)## current conversation phase', "system prompt section leaked"),
        ]
        for pattern, label in leak_patterns:
            if re.search(pattern, answer):
                logger.warning(f"SECURITY: AI output filter triggered — {label} detected in response")
        return answer

    async def get_response(
        self,
        question: str,
        conversation_history: Optional[List[Message]] = None
    ) -> Dict:
        """
        Get AI response for user question.
        Returns dict with answer, follow_up, cta_type, and lead_signals.
        """
        # Detect conversation phase and build phase-aware system prompt
        phase = detect_phase(conversation_history)
        system_prompt = self._build_system_prompt(phase)
        logger.info(f"Conversation phase: {phase.value}")

        # Sanitize user input before passing to AI
        clean_question = self._sanitize_input(question)

        # Build conversation history for Anthropic (role: user/assistant)
        messages = []
        if conversation_history:
            for msg in conversation_history:
                sanitized_content = self._sanitize_input(msg.content) if msg.role == "user" else msg.content
                messages.append({
                    "role": "user" if msg.role == "user" else "assistant",
                    "content": sanitized_content,
                })
        messages.append({"role": "user", "content": clean_question})

        max_retries = 3
        eval_regenerated = False  # only allow one evaluator-triggered regeneration per call

        for attempt in range(max_retries):
            try:
                response_text = self._call_claude(messages, system_prompt)
                parsed = json.loads(response_text)

                # --- Evaluator pass ---
                # Run after successful JSON parse, skip on evaluator-triggered re-call
                if not eval_regenerated:
                    eval_result = evaluate_response(parsed, phase, conversation_history)

                    if eval_result.needs_regeneration:
                        eval_regenerated = True
                        hint_prompt = (
                            system_prompt
                            + f"\n\n## Correction Required\n{eval_result.regeneration_hint}"
                        )
                        logger.warning(
                            f"Evaluator triggered regeneration: {eval_result.issues}"
                        )
                        try:
                            retry_text = self._call_claude(messages, hint_prompt)
                            parsed = json.loads(retry_text)
                        except (json.JSONDecodeError, Exception) as regen_err:
                            logger.warning(
                                f"Evaluator regeneration failed ({regen_err}), using original"
                            )
                            # Fall through with original parsed

                    elif eval_result.has_issues:
                        logger.info(f"Evaluator auto-corrected: {eval_result.issues}")
                        if "answer" in eval_result.auto_corrections:
                            parsed["answer"] = eval_result.auto_corrections["answer"]
                        if "cta_type" in eval_result.auto_corrections:
                            parsed["cta_type"] = eval_result.auto_corrections["cta_type"]

                # --- Safety net: ensure response ends with a question ---
                # Checks last 150 chars to handle responses ending with "(e.g. ...)"
                answer = parsed.get("answer", "")
                stripped = answer.rstrip()
                if stripped and "?" not in stripped[-150:]:
                    lead = parsed.get("lead_signals", {})
                    fleet_size = lead.get("fleet_size") if lead else None
                    # Vary fallback by phase to avoid always repeating the same CTA
                    if phase == ConversationPhase.CLOSE_QUOTE:
                        fallback = None  # mid-collection — no fallback needed, just wait
                    elif phase == ConversationPhase.PRESENT and fleet_size:
                        fallback = "Is there anything else you'd like to know before we move forward?"
                    elif fleet_size:
                        fallback = "Want me to have someone from our team reach out to you?"
                    else:
                        fallback = "How many vehicles are in your fleet?"
                    if fallback:
                        parsed["answer"] = stripped + f"\n\n{fallback}"

                parsed["_phase"] = phase.value
                # Output filter: log if response shows signs of injection success or leakage
                self._filter_output(parsed.get("answer", ""))
                return parsed

            except json.JSONDecodeError:
                raw = response_text if 'response_text' in dir() else ""
                logger.warning(f"Claude returned non-JSON, attempting regex extraction. Raw: {raw[:200]}")

                # Layer 1a: try fixing truncated JSON by appending closing brackets
                for suffix in ['"}', '"}}', '"}}}']:
                    try:
                        patched = json.loads(raw + suffix)
                        answer_text = patched.get("answer", "")
                        if answer_text:
                            return {
                                "answer": answer_text,
                                "follow_up": None,
                                "cta_type": patched.get("cta_type"),
                                "lead_signals": patched.get("lead_signals", {})
                            }
                    except json.JSONDecodeError:
                        pass

                # Layer 1b: extract "answer" field via regex
                match = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
                if match:
                    answer_text = (
                        match.group(1)
                        .replace('\\"', '"')
                        .replace('\\n', '\n')
                        .replace('\\\\', '\\')
                    )
                    return {
                        "answer": answer_text,
                        "follow_up": None,
                        "cta_type": None,
                        "lead_signals": {}
                    }

                # Layer 2: return raw text if it doesn't look like JSON
                if raw and not raw.startswith('{'):
                    return {
                        "answer": raw,
                        "follow_up": None,
                        "cta_type": None,
                        "lead_signals": {}
                    }

                # Layer 3: safe fallback
                logger.error(f"Could not extract answer from malformed JSON: {raw[:500]}")
                return {
                    "answer": "I'm having a moment — could you rephrase that? I want to make sure I give you the right answer.",
                    "follow_up": None,
                    "cta_type": None,
                    "lead_signals": {}
                }

            except Exception as e:
                error_str = str(e)
                is_rate_limit = "429" in error_str or "rate_limit" in error_str.lower() or "overloaded" in error_str.lower()

                if is_rate_limit and attempt < max_retries - 1:
                    delay = 2 * (2 ** attempt)
                    logger.warning(f"Rate limit hit, retrying in {delay}s")
                    time.sleep(delay)
                    continue

                logger.error(f"Claude error: {error_str}")
                return {
                    "answer": "I'm having trouble right now. Please try again in a moment, or contact us directly at fleethelp@getnexar.com or (929) 447-2317.",
                    "follow_up": None,
                    "cta_type": None,
                    "lead_signals": {}
                }
