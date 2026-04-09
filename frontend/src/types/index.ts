export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  cta_type?: string | null
  showFeedback?: boolean
  quote_url?: string | null
}

export interface ChatResponse {
  answer: string
  session_id: string
  suggested_follow_ups: string[]
  lead_collected: boolean
  cta_type: string | null
  quote_url?: string | null
}

export interface FeedbackRequest {
  session_id: string
  message_id: string
  question: string
  answer: string
  rating: 'thumbs_up' | 'thumbs_down'
  feedback_text?: string
}

// ─── Admin types ──────────────────────────────────────────────────────────────

export interface ConversationSummary {
  session_id: string
  created_at: unknown
  updated_at: unknown
  status: string
  message_count: number
  user_message_count: number
  last_message_preview: string
  last_message_role: string
  rating?: 'thumbs_up' | 'thumbs_down'
  rating_notes?: string
  rated_by?: string
}

export interface ConversationMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: unknown
  cta_type?: string
  lead_signals?: Record<string, unknown>
}

export interface LeadData {
  session_id?: string
  contact_name?: string
  contact_email?: string
  business_name?: string
  num_cameras?: number
  fleet_size?: number
  camera_model?: string
  memory_option?: string
  subscription_plan?: string
  cta_type?: string
  status?: string
  pain_points?: string
  slack_notified?: boolean
}

export interface ConversationDetail {
  session_id: string
  messages: ConversationMessage[]
  created_at: unknown
  updated_at: unknown
  status: string
  rating?: 'thumbs_up' | 'thumbs_down'
  rating_notes?: string
  rated_by?: string
  lead: LeadData | null
}

export interface FeedbackItem {
  feedback_id: string
  session_id: string
  question: string
  answer: string
  rating: string
  feedback_text?: string
  source?: string
  timestamp: unknown
  triage_resource?: string
  triage_detail?: string
  triage_reasoning?: string
}

export interface FaqEntry {
  question: string
  answer: string
  category?: string
  source?: string
}

export interface AdminConfig {
  faqs: FaqEntry[]
  core_prompt: string
  phase_prompts: Record<string, string>
}
