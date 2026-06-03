import { useEffect, useState } from 'react'
import { useFeedbackSuggest } from '../../hooks/useAdmin'
import type { FeedbackSuggestion, AgentContext } from '../../types'

interface Props {
  type: 'instruction' | 'faq'
  notes: string
  question: string
  answer: string
  onClose: () => void
  onSuccess: (type: 'instruction' | 'faq') => void
}

const FIELD_LABELS: Record<string, string> = {
  dos_donts: 'Dos & Don\'ts',
  tone_style: 'Tone & Style',
  escalations: 'Escalation Rules',
  business_context: 'Business Context',
}

export default function FeedbackSuggestionModal({ type, notes, question, answer, onClose, onSuccess }: Props) {
  const { suggest, loading: suggesting } = useFeedbackSuggest()
  const [suggestion, setSuggestion] = useState<FeedbackSuggestion | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)

  // Editable preview state
  const [editedAddition, setEditedAddition] = useState('')
  const [editedQuestion, setEditedQuestion] = useState('')
  const [editedAnswer, setEditedAnswer] = useState('')

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    suggest(type, notes, question, answer)
      .then(s => {
        setSuggestion(s)
        if (type === 'instruction') setEditedAddition(s.addition ?? '')
        else {
          setEditedQuestion(s.question ?? '')
          setEditedAnswer(s.answer ?? '')
        }
      })
      .catch(e => setFetchError(String(e)))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function handleConfirm() {
    if (!suggestion) return
    setSaving(true)
    setSaveError(null)
    try {
      if (type === 'instruction' && suggestion.field) {
        // Fetch current context, append, save
        const ctxRes = await fetch('/api/admin/config/context')
        if (!ctxRes.ok) throw new Error('Failed to load agent context')
        const rawCtx = await ctxRes.json()
        // Coerce null/undefined fields to "" — backend requires strings
        const ctx: AgentContext = {
          business_context: rawCtx.business_context || '',
          escalations: rawCtx.escalations || '',
          tone_style: rawCtx.tone_style || '',
          dos_donts: rawCtx.dos_donts || '',
        }
        const field = suggestion.field as keyof AgentContext
        ctx[field] = ctx[field] ? `${ctx[field]}\n${editedAddition}` : editedAddition
        const saveRes = await fetch('/api/admin/config/context', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(ctx),
        })
        if (!saveRes.ok) {
          const err = await saveRes.json().catch(() => ({}))
          throw new Error(err.detail || `Save failed (${saveRes.status})`)
        }
      } else {
        // Fetch current FAQs, append new entry, save
        const cfgRes = await fetch('/api/admin/config')
        if (!cfgRes.ok) throw new Error('Failed to load FAQ list')
        const cfg = await cfgRes.json()
        // Coerce null/undefined fields on existing FAQs — backend requires strings
        const faqs = (cfg.faqs ?? []).map((f: Record<string, unknown>) => ({
          question: f.question || '',
          answer: f.answer || '',
          category: f.category || '',
          source: f.source || '',
        }))
        faqs.push({
          question: editedQuestion,
          answer: editedAnswer,
          category: suggestion.category || '',
          source: 'admin-feedback',
        })
        const saveRes = await fetch('/api/admin/config/faqs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ faqs }),
        })
        if (!saveRes.ok) {
          const err = await saveRes.json().catch(() => ({}))
          throw new Error(err.detail || `Save failed (${saveRes.status})`)
        }
      }
      onSuccess(type)
    } catch (e) {
      setSaveError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const fieldLabel = suggestion?.field ? FIELD_LABELS[suggestion.field] ?? suggestion.field_label ?? suggestion.field : ''

  return (
    // Overlay
    <div
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
      style={{
        position: 'fixed', inset: 0,
        background: 'var(--overlay)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 50, padding: 24,
      }}
    >
      {/* Card */}
      <div style={{
        background: 'var(--card)',
        border: '1px solid var(--border)',
        borderRadius: 16,
        width: '100%', maxWidth: 520,
        padding: 28,
        display: 'flex', flexDirection: 'column', gap: 20,
        boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-heading)', color: 'var(--foreground)' }}>
              {type === 'instruction' ? 'Add to agent instructions' : 'Add as FAQ'}
            </h2>
            <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--muted-foreground)' }}>
              {type === 'instruction'
                ? 'Review and edit the suggested instruction before adding it.'
                : 'Review and edit the suggested Q&A before adding it to the knowledge base.'}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: 4,
              color: 'var(--muted-foreground)', fontSize: 18, lineHeight: 1, flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>

        {/* Loading state */}
        {suggesting && !suggestion && !fetchError && (
          <div style={{ textAlign: 'center', padding: '32px 0', color: 'var(--muted-foreground)', fontSize: 13 }}>
            <div style={{ marginBottom: 10, fontSize: 22 }}>✨</div>
            Generating suggestion…
          </div>
        )}

        {/* Error fetching suggestion */}
        {fetchError && (
          <div style={{ color: 'var(--destructive)', fontSize: 13, padding: '12px 16px', background: 'oklch(0.97 0.01 23)', borderRadius: 8 }}>
            {fetchError}
          </div>
        )}

        {/* Suggestion preview */}
        {suggestion && (
          <>
            {/* Duplicate warning */}
            {suggestion.is_duplicate && suggestion.duplicate_hint && (
              <div style={{
                padding: '10px 14px', borderRadius: 8,
                background: 'oklch(0.98 0.04 80)', border: '1px solid oklch(0.88 0.08 80)',
                fontSize: 12, color: 'oklch(0.45 0.12 70)',
              }}>
                <strong>Similar content may already exist:</strong><br />
                <span style={{ opacity: 0.85 }}>{suggestion.duplicate_hint}</span>
              </div>
            )}

            {type === 'instruction' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)' }}>
                  Adding to: <span style={{ color: 'var(--foreground)' }}>{fieldLabel}</span>
                </label>
                <textarea
                  value={editedAddition}
                  onChange={e => setEditedAddition(e.target.value)}
                  rows={5}
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    padding: '10px 12px', borderRadius: 8,
                    border: '1px solid var(--input)', background: 'var(--background)',
                    color: 'var(--foreground)', fontSize: 13,
                    fontFamily: 'inherit', resize: 'vertical', lineHeight: 1.5,
                  }}
                />
              </div>
            )}

            {type === 'faq' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)' }}>Question</label>
                  <input
                    value={editedQuestion}
                    onChange={e => setEditedQuestion(e.target.value)}
                    style={{
                      padding: '9px 12px', borderRadius: 8,
                      border: '1px solid var(--input)', background: 'var(--background)',
                      color: 'var(--foreground)', fontSize: 13, fontFamily: 'inherit', width: '100%', boxSizing: 'border-box',
                    }}
                  />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)' }}>Answer</label>
                  <textarea
                    value={editedAnswer}
                    onChange={e => setEditedAnswer(e.target.value)}
                    rows={5}
                    style={{
                      width: '100%', boxSizing: 'border-box',
                      padding: '10px 12px', borderRadius: 8,
                      border: '1px solid var(--input)', background: 'var(--background)',
                      color: 'var(--foreground)', fontSize: 13,
                      fontFamily: 'inherit', resize: 'vertical', lineHeight: 1.5,
                    }}
                  />
                </div>
              </div>
            )}

            {/* Save error */}
            {saveError && (
              <div style={{ color: 'var(--destructive)', fontSize: 12 }}>{saveError}</div>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                onClick={onClose}
                style={{
                  padding: '8px 18px', borderRadius: 8,
                  border: '1px solid var(--border)', background: 'var(--background)',
                  color: 'var(--foreground)', fontSize: 13, fontWeight: 500, cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={saving || (type === 'instruction' ? !editedAddition.trim() : !editedQuestion.trim() || !editedAnswer.trim())}
                style={{
                  padding: '8px 18px', borderRadius: 8, border: 'none',
                  background: 'var(--primary)', color: 'var(--primary-foreground)',
                  fontSize: 13, fontWeight: 600,
                  cursor: saving ? 'default' : 'pointer',
                  opacity: saving ? 0.7 : 1,
                }}
              >
                {saving ? 'Saving…' : type === 'instruction' ? 'Add to instructions' : 'Add FAQ'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
