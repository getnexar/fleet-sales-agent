import { useState, useEffect } from 'react'
import type { ConversationSummary, ConversationDetail, ConversationMessage } from '../../types'
import { useConversations, useConversationDetail } from '../../hooks/useAdmin'

function formatTs(ts: unknown): string {
  if (!ts) return '—'
  // Firestore timestamps come as {_seconds, _nanoseconds} or ISO strings
  const secs = (ts as { _seconds?: number })?._seconds
  const date = secs ? new Date(secs * 1000) : new Date(ts as string)
  if (isNaN(date.getTime())) return '—'
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function RatingBadge({ rating }: { rating?: string }) {
  if (!rating) return null
  return (
    <span style={{
      fontSize: 14,
      padding: '2px 8px',
      borderRadius: 12,
      background: rating === 'thumbs_up' ? '#dcfce7' : '#fee2e2',
      color: rating === 'thumbs_up' ? '#166534' : '#991b1b',
    }}>
      {rating === 'thumbs_up' ? '👍' : '👎'}
    </span>
  )
}

function TriageBadge({
  resource,
  detail,
  onEdit,
}: {
  resource?: string
  detail?: string
  onEdit?: () => void
}) {
  if (!resource) return null
  const label = resource === 'faq'
    ? `FAQ: ${detail}`
    : resource === 'phase_prompt'
    ? `Phase: ${detail}`
    : resource === 'core_prompt'
    ? `Core Prompt: ${detail}`
    : `Unknown`

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span style={{
        fontSize: 12,
        padding: '2px 8px',
        borderRadius: 8,
        background: '#fef3c7',
        color: '#92400e',
      }}>
        → {label}
      </span>
      {onEdit && (
        <button
          onClick={onEdit}
          style={{
            fontSize: 12,
            background: 'none',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '1px 8px',
            cursor: 'pointer',
            color: 'var(--primary)',
          }}
        >
          Edit →
        </button>
      )}
    </span>
  )
}

function ConversationDetailPanel({
  sessionId,
  onClose,
  onNavigateConfig,
}: {
  sessionId: string
  onClose: () => void
  onNavigateConfig?: (resource: string, detail: string) => void
}) {
  const { detail, loading, error, load, rate } = useConversationDetail()
  const [rating, setRating] = useState<'thumbs_up' | 'thumbs_down' | null>(null)
  const [notes, setNotes] = useState('')
  const [ratingSubmitted, setRatingSubmitted] = useState(false)
  const [ratingError, setRatingError] = useState<string | null>(null)

  useEffect(() => {
    load(sessionId)
  }, [sessionId, load])

  useEffect(() => {
    if (detail?.rating) {
      setRating(detail.rating)
      setNotes(detail.rating_notes || '')
    }
  }, [detail])

  async function submitRating() {
    if (!rating || !detail) return
    setRatingError(null)
    try {
      // Pick the last user→assistant exchange for triage context
      const msgs = detail.messages || []
      const lastAssistant = [...msgs].reverse().find(m => m.role === 'assistant')
      const lastUser = [...msgs].reverse().find(m => m.role === 'user')
      await rate(
        sessionId,
        rating,
        notes,
        lastUser?.content || '',
        lastAssistant?.content || '',
      )
      setRatingSubmitted(true)
      setTimeout(() => setRatingSubmitted(false), 3000)
    } catch (e) {
      setRatingError(String(e))
    }
  }

  return (
    <div style={{
      position: 'fixed', top: 0, right: 0, bottom: 0, width: 520,
      background: 'var(--card)', borderLeft: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', zIndex: 50, boxShadow: '-4px 0 24px rgba(0,0,0,.1)',
    }}>
      {/* Header */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 15 }}>Conversation</div>
          <div style={{ fontSize: 12, color: 'var(--muted-foreground)', fontFamily: 'monospace' }}>{sessionId.slice(0, 18)}…</div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--muted-foreground)' }}>×</button>
      </div>

      {loading && <div style={{ padding: 24, color: 'var(--muted-foreground)' }}>Loading…</div>}
      {error && <div style={{ padding: 24, color: '#ef4444' }}>{error}</div>}

      {detail && !loading && (
        <>
          {/* Lead info strip */}
          {detail.lead && (
            <div style={{ padding: '10px 20px', background: 'var(--muted)', fontSize: 13, borderBottom: '1px solid var(--border)' }}>
              {[
                detail.lead.contact_name,
                detail.lead.contact_email,
                detail.lead.business_name,
                detail.lead.num_cameras ? `${detail.lead.num_cameras} cameras` : null,
                detail.lead.camera_model,
              ].filter(Boolean).join(' · ')}
            </div>
          )}

          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {detail.messages.map((msg: ConversationMessage, i: number) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                <div style={{
                  maxWidth: '85%',
                  padding: '8px 12px',
                  borderRadius: msg.role === 'user' ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                  background: msg.role === 'user' ? 'var(--primary)' : 'var(--background)',
                  color: msg.role === 'user' ? 'var(--primary-foreground)' : 'var(--foreground)',
                  border: msg.role === 'assistant' ? '1px solid var(--border)' : 'none',
                  fontSize: 13,
                  lineHeight: 1.5,
                  whiteSpace: 'pre-wrap',
                }}>
                  {msg.content}
                </div>
                <div style={{ fontSize: 11, color: 'var(--muted-foreground)', marginTop: 2 }}>
                  {msg.role === 'assistant' && msg.cta_type ? `cta: ${msg.cta_type} · ` : ''}
                  {formatTs(msg.timestamp)}
                </div>
              </div>
            ))}
          </div>

          {/* Rating panel */}
          <div style={{ padding: '16px 20px', borderTop: '1px solid var(--border)' }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>Rate this conversation</div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              {(['thumbs_up', 'thumbs_down'] as const).map(r => (
                <button
                  key={r}
                  onClick={() => setRating(r)}
                  style={{
                    padding: '6px 16px',
                    borderRadius: 8,
                    border: '1px solid var(--border)',
                    cursor: 'pointer',
                    fontSize: 20,
                    background: rating === r ? (r === 'thumbs_up' ? '#dcfce7' : '#fee2e2') : 'var(--background)',
                    transition: 'background .15s',
                  }}
                >
                  {r === 'thumbs_up' ? '👍' : '👎'}
                </button>
              ))}
            </div>
            {rating === 'thumbs_down' && (
              <textarea
                placeholder="What was wrong? (used for AI triage)"
                value={notes}
                onChange={e => setNotes(e.target.value)}
                rows={3}
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: 8,
                  border: '1px solid var(--border)',
                  fontSize: 13,
                  resize: 'vertical',
                  boxSizing: 'border-box',
                  background: 'var(--background)',
                  color: 'var(--foreground)',
                  fontFamily: 'inherit',
                  marginBottom: 8,
                }}
              />
            )}
            <button
              onClick={submitRating}
              disabled={!rating}
              style={{
                padding: '8px 20px',
                borderRadius: 8,
                border: 'none',
                background: rating ? 'var(--primary)' : 'var(--muted)',
                color: rating ? 'var(--primary-foreground)' : 'var(--muted-foreground)',
                cursor: rating ? 'pointer' : 'default',
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              {ratingSubmitted ? 'Saved ✓' : 'Save Rating'}
            </button>
            {ratingError && <div style={{ color: '#ef4444', fontSize: 12, marginTop: 6 }}>{ratingError}</div>}
            {ratingSubmitted && rating === 'thumbs_down' && (
              <div style={{ fontSize: 12, color: 'var(--muted-foreground)', marginTop: 6 }}>
                AI triage running in background — check Feedback tab in a moment.
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

export default function ConversationList({ onNavigateConfig }: { onNavigateConfig?: (resource: string, detail: string) => void }) {
  const { conversations, loading, error, load } = useConversations()
  const [selectedSession, setSelectedSession] = useState<string | null>(null)

  useEffect(() => { load() }, [load])

  return (
    <div style={{ position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 14, color: 'var(--muted-foreground)' }}>
          {conversations.length} conversations
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <a
            href={`/api/admin/conversations/export?limit=200`}
            download="fleet_conversations.json"
            style={{
              fontSize: 13, padding: '5px 14px', borderRadius: 8,
              border: '1px solid var(--border)', background: 'var(--background)',
              cursor: 'pointer', color: 'var(--foreground)', textDecoration: 'none',
              display: 'inline-block',
            }}
          >
            Export JSON
          </a>
          <button
            onClick={() => load()}
            style={{ fontSize: 13, padding: '5px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--background)', cursor: 'pointer', color: 'var(--foreground)' }}
          >
            Refresh
          </button>
        </div>
      </div>

      {loading && <div style={{ color: 'var(--muted-foreground)', padding: '20px 0' }}>Loading conversations…</div>}
      {error && <div style={{ color: '#ef4444', padding: '12px 0' }}>{error}</div>}

      {!loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {conversations.map(c => (
            <div
              key={c.session_id}
              onClick={() => setSelectedSession(c.session_id)}
              style={{
                padding: '12px 16px',
                borderRadius: 10,
                border: '1px solid var(--border)',
                background: selectedSession === c.session_id ? 'var(--muted)' : 'var(--card)',
                cursor: 'pointer',
                transition: 'background .1s',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4, color: 'var(--foreground)' }}>
                    {formatTs(c.updated_at)}
                    <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--muted-foreground)', fontFamily: 'monospace' }}>
                      {c.session_id.slice(0, 12)}…
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--muted-foreground)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.last_message_preview || 'No messages'}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
                  <RatingBadge rating={c.rating} />
                  <span style={{ fontSize: 11, color: 'var(--muted-foreground)' }}>
                    {c.user_message_count} msg{c.user_message_count !== 1 ? 's' : ''}
                  </span>
                </div>
              </div>
            </div>
          ))}
          {conversations.length === 0 && !loading && (
            <div style={{ color: 'var(--muted-foreground)', padding: '20px 0', textAlign: 'center' }}>No conversations yet.</div>
          )}
        </div>
      )}

      {selectedSession && (
        <ConversationDetailPanel
          sessionId={selectedSession}
          onClose={() => setSelectedSession(null)}
          onNavigateConfig={onNavigateConfig}
        />
      )}
    </div>
  )
}

export { TriageBadge, RatingBadge, formatTs }
