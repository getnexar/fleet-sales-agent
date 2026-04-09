import { useState, useCallback, useRef, useEffect } from 'react'
import { v4 as uuidv4 } from 'uuid'
import type { Message, ChatResponse } from '../types'

const NUDGE_DELAY_MS = 50_000
const NUDGE_STILL_THERE = "Still there? Happy to keep going whenever you're ready."

// Patterns that indicate the bot is wrapping up — no nudge after these
const CLOSING_PATTERNS = [
  'is there anything else',
  'anything else i can help',
  'anything else you',
  'thank you for your time',
  'thanks for your time',
]

const SESSION_KEY = 'fleet_chat_session_id'

function getOrCreateSessionId(): string {
  let id = sessionStorage.getItem(SESSION_KEY)
  if (!id) {
    id = uuidv4()
    sessionStorage.setItem(SESSION_KEY, id)
  }
  return id
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: uuidv4(),
      role: 'assistant',
      content: "Hi! I'm Alex, your Nexar Fleet assistant. I can help you learn about our dash cam solutions, pricing, and get you set up. What brings you here today?",
      timestamp: new Date(),
    }
  ])
  const [isLoading, setIsLoading] = useState(false)
  const [followUps, setFollowUps] = useState<string[]>([])
  const sessionId = useRef(getOrCreateSessionId())
  const nudgeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // True once the nudge has fired — prevents repeat nudges until user replies
  const nudgeHasFiredRef = useRef(false)
  // True after the lead is captured or quote sent — stops nudges permanently
  const ctaCompletedRef = useRef(false)

  const clearNudgeTimer = useCallback(() => {
    if (nudgeTimer.current) {
      clearTimeout(nudgeTimer.current)
      nudgeTimer.current = null
    }
  }, [])

  const startNudgeTimer = useCallback(() => {
    clearNudgeTimer()

    // No nudges after the conversation is wrapped up, or if already nudged once
    if (ctaCompletedRef.current || nudgeHasFiredRef.current) return

    nudgeTimer.current = setTimeout(() => {
      setMessages(prev => {
        if (prev[prev.length - 1]?.role !== 'assistant') return prev
        return [...prev, {
          id: uuidv4(),
          role: 'assistant',
          content: NUDGE_STILL_THERE,
          timestamp: new Date(),
        }]
      })
      nudgeHasFiredRef.current = true
    }, NUDGE_DELAY_MS)
  }, [clearNudgeTimer])

  useEffect(() => () => clearNudgeTimer(), [clearNudgeTimer])

  const sendMessage = useCallback(async (text: string) => {
    clearNudgeTimer()
    // User replied — allow one fresh nudge on the next bot response
    nudgeHasFiredRef.current = false

    const userMsgId = uuidv4()
    const userMsg: Message = {
      id: userMsgId,
      role: 'user',
      content: text,
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMsg])
    setFollowUps([])
    setIsLoading(true)

    // Build history for API (include greeting so Gemini knows it already introduced itself)
    const history = messages
      .slice(0)
      .map(m => ({ role: m.role, content: m.content }))

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text,
          session_id: sessionId.current,
          conversation_history: history,
        }),
      })

      const data: ChatResponse = await res.json()

      const assistantMsg: Message = {
        id: uuidv4(),
        role: 'assistant',
        content: data.answer,
        timestamp: new Date(),
        cta_type: data.cta_type,
        showFeedback: true,
        quote_url: data.quote_url ?? null,
      }

      setMessages(prev => [...prev, assistantMsg])
      setFollowUps(data.suggested_follow_ups || [])

      // Track completion state — stop nudges once conversation is wrapping up
      const answerLower = data.answer.toLowerCase()
      const isClosing = CLOSING_PATTERNS.some(p => answerLower.includes(p))
      if (isClosing || data.lead_collected || data.quote_url) {
        ctaCompletedRef.current = true
      }

      startNudgeTimer()
    } catch {
      setMessages(prev => [
        ...prev,
        {
          id: uuidv4(),
          role: 'assistant',
          content: "Sorry, I'm having trouble connecting. Please try again or contact us at fleethelp@getnexar.com.",
          timestamp: new Date(),
        }
      ])
    } finally {
      setIsLoading(false)
    }
  }, [messages, clearNudgeTimer, startNudgeTimer])

  const submitFeedback = useCallback(async (
    messageId: string,
    question: string,
    answer: string,
    rating: 'thumbs_up' | 'thumbs_down',
    feedbackText?: string
  ) => {
    try {
      await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId.current,
          message_id: messageId,
          question,
          answer,
          rating,
          feedback_text: feedbackText,
        }),
      })
    } catch {
      // Silent fail - feedback is best-effort
    }
  }, [])

  return { messages, isLoading, followUps, sendMessage, submitFeedback, sessionId: sessionId.current }
}
