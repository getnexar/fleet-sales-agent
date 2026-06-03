import { useState, useCallback } from 'react'
import type {
  ConversationSummary,
  ConversationDetail,
  FeedbackItem,
  FeedbackSuggestion,
  AdminConfig,
  AgentContext,
  AdminStats,
  LeadRecord,
} from '../types'

// ─── Current User ─────────────────────────────────────────────────────────────

export function useCurrentUser() {
  const [email, setEmail] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    if (email) return email
    setLoading(true)
    try {
      const res = await fetch('/api/admin/me')
      if (!res.ok) return null
      const data = await res.json()
      setEmail(data.email)
      return data.email as string
    } catch {
      return null
    } finally {
      setLoading(false)
    }
  }, [email])

  return { email, loading, load }
}

// ─── Stats ────────────────────────────────────────────────────────────────────

export function useAdminStats() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/stats')
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      setStats(await res.json())
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  return { stats, loading, error, load }
}

// ─── Leads (for dashboard list) ───────────────────────────────────────────────

export function useLeads() {
  const [leads, setLeads] = useState<LeadRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (limit = 200) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/admin/leads?limit=${limit}`)
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      const data = await res.json()
      setLeads(data.leads)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  return { leads, loading, error, load }
}

// ─── Conversations ────────────────────────────────────────────────────────────

export function useConversations() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (limit = 50) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/admin/conversations?limit=${limit}`)
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      const data = await res.json()
      setConversations(data.conversations)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  return { conversations, loading, error, load }
}

export function useConversationDetail() {
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (sessionId: string) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/admin/conversations/${sessionId}`)
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      setDetail(await res.json())
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const rate = useCallback(async (
    sessionId: string,
    rating: 'thumbs_up' | 'thumbs_down',
    notes: string,
    question: string,
    answer: string,
  ) => {
    const res = await fetch(`/api/admin/conversations/${sessionId}/rate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, notes, question, answer }),
    })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json()
  }, [])

  return { detail, loading, error, load, rate }
}

// ─── Feedback ─────────────────────────────────────────────────────────────────

export function useThumbsDownFeedback() {
  const [feedback, setFeedback] = useState<FeedbackItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (limit = 100) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`/api/admin/feedback/thumbs-down?limit=${limit}`)
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      const data = await res.json()
      setFeedback(data.feedback)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  return { feedback, loading, error, load }
}

// ─── Agent Context ────────────────────────────────────────────────────────────

export function useAgentContext() {
  const [context, setContext] = useState<AgentContext | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/config/context')
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      setContext(await res.json())
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const save = useCallback(async (ctx: AgentContext) => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/config/context', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(ctx),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `${res.status} ${res.statusText}`)
      }
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [])

  return { context, loading, saving, saved, error, load, save }
}

// ─── Config (FAQs + Raw Prompts) ──────────────────────────────────────────────

export function useAdminConfig() {
  const [config, setConfig] = useState<AdminConfig | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/config')
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      setConfig(await res.json())
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const saveFaqs = useCallback(async (faqs: AdminConfig['faqs']) => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/config/faqs', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ faqs }),
      })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [])

  const savePrompts = useCallback(async (
    corePrompt: string,
    phasePrompts: Record<string, string>,
    changeReason: string,
    confirmedBy: string,
  ) => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/config/prompts', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          core_prompt: corePrompt,
          phase_prompts: phasePrompts,
          change_reason: changeReason,
          confirmed_by: confirmedBy,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `${res.status} ${res.statusText}`)
      }
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [])

  return { config, loading, saving, saved, error, load, saveFaqs, savePrompts }
}

// ─── Feedback → Agent Suggestion ──────────────────────────────────────────────

export function useFeedbackSuggest() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const suggest = useCallback(async (
    type: 'instruction' | 'faq',
    notes: string,
    question: string,
    answer: string,
  ): Promise<FeedbackSuggestion> => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/feedback/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, notes, question, answer }),
      })
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
      return await res.json()
    } catch (e) {
      setError(String(e))
      throw e
    } finally {
      setLoading(false)
    }
  }, [])

  return { loading, error, suggest }
}
