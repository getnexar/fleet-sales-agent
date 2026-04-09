import { useState, useCallback } from 'react'
import type {
  ConversationSummary,
  ConversationDetail,
  FeedbackItem,
  AdminConfig,
} from '../types'

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

// ─── Config ───────────────────────────────────────────────────────────────────

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
  ) => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/config/prompts', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ core_prompt: corePrompt, phase_prompts: phasePrompts }),
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

  return { config, loading, saving, saved, error, load, saveFaqs, savePrompts }
}
