"""
Pydantic models for the Fleet Sales AI Agent API.
"""
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum
from datetime import datetime


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    role: MessageRole
    content: str


class ChatRequest(BaseModel):
    question: str
    session_id: str
    # conversation_history is intentionally omitted — the server loads history
    # from Firestore to prevent client-side manipulation of prior messages.


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    suggested_follow_ups: Optional[List[str]] = []
    lead_collected: bool = False
    cta_type: Optional[str] = None  # "demo", "trial", "quote", "info"
    quote_url: Optional[str] = None


class LeadData(BaseModel):
    session_id: str
    business_name: Optional[str] = None
    num_cameras: Optional[int] = None
    subscription_plan: Optional[str] = None
    shipping_address: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    billing_email: Optional[str] = None
    fleet_size: Optional[int] = None
    pain_points: Optional[str] = None
    cta_type: Optional[str] = None
    camera_model: Optional[str] = None
    memory_option: Optional[str] = None
    envelope_id: Optional[str] = None
    quote_url: Optional[str] = None
    quote_sent: bool = False
    quote_sent_at: Optional[datetime] = None
    status: str = "new"  # "new", "contacted", "converted"


class FeedbackRequest(BaseModel):
    session_id: str
    message_id: str
    question: str
    answer: str
    rating: str  # "thumbs_up" or "thumbs_down"
    feedback_text: Optional[str] = None


class FeedbackResponse(BaseModel):
    success: bool
    message: str
    feedback_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
