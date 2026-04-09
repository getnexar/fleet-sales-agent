import { useEffect } from 'react'
import { useThumbsDownFeedback } from '../../hooks/useAdmin'
import { TriageBadge, formatTs } from './ConversationList'
import type { FeedbackItem } from '../../types'

export default function FeedbackPanel({
  onNavigateConfig,
}: {
  onNavigateConfig?: (resource: string, detail: string) => void
}) {
  const { feedback, loading, error, load } = useThumbsDownFeedback()

  useEffect(() => { load() }, [load])

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 14, color: 'var(--muted-foreground)' }}>
          {feedback.length} thumbs-down feedback{feedback.length !== 1 ? 's' : ''}
        </div>
        <button
          onClick={() => load()}
          style={{ fontSize: 13, padding: '5px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--background)', cursor: 'pointer', color: 'var(--foreground)' }}
        >
          Refresh
        </button>
      </div>

      {loading && <div style={{ color: 'var(--muted-foreground)', padding: '20px 0' }}>Loading feedback…</div>}
      {error && <div style={{ color: '#ef4444', padding: '12px 0' }}>{error}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {feedback.map((item: FeedbackItem) => (
          <div
            key={item.feedback_id}
            style={{
              padding: 16,
              borderRadius: 10,
              border: '1px solid var(--border)',
              background: 'var(--card)',
            }}
          >
            {/* Header row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={{ fontSize: 12, color: 'var(--muted-foreground)' }}>
                {formatTs(item.timestamp)}
                {item.source === 'admin' && (
                  <span style={{ marginLeft: 6, background: 'var(--muted)', borderRadius: 6, padding: '1px 6px', fontSize: 11 }}>admin</span>
                )}
              </span>
              <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--muted-foreground)' }}>
                {item.session_id?.slice(0, 12)}…
              </span>
            </div>

            {/* Q&A */}
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', marginBottom: 3 }}>USER</div>
              <div style={{ fontSize: 13, color: 'var(--foreground)', lineHeight: 1.5 }}>{item.question}</div>
            </div>
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', marginBottom: 3 }}>BOT</div>
              <div style={{
                fontSize: 13,
                color: 'var(--foreground)',
                lineHeight: 1.5,
                background: 'var(--muted)',
                padding: '8px 10px',
                borderRadius: 8,
                maxHeight: 120,
                overflowY: 'auto',
              }}>
                {item.answer}
              </div>
            </div>

            {/* Admin notes */}
            {item.feedback_text && (
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', marginBottom: 3 }}>NOTES</div>
                <div style={{ fontSize: 13, color: 'var(--foreground)', fontStyle: 'italic' }}>{item.feedback_text}</div>
              </div>
            )}

            {/* Triage */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {item.triage_resource ? (
                <>
                  <span style={{ fontSize: 12, color: 'var(--muted-foreground)' }}>Likely cause:</span>
                  <TriageBadge
                    resource={item.triage_resource}
                    detail={item.triage_detail}
                    onEdit={
                      item.triage_resource !== 'unknown' && onNavigateConfig
                        ? () => onNavigateConfig(item.triage_resource!, item.triage_detail || '')
                        : undefined
                    }
                  />
                  {item.triage_reasoning && (
                    <span style={{ fontSize: 12, color: 'var(--muted-foreground)', width: '100%', marginTop: 4 }}>
                      {item.triage_reasoning}
                    </span>
                  )}
                </>
              ) : (
                <span style={{ fontSize: 12, color: 'var(--muted-foreground)' }}>
                  Triage pending…
                </span>
              )}
            </div>
          </div>
        ))}

        {feedback.length === 0 && !loading && (
          <div style={{ color: 'var(--muted-foreground)', padding: '20px 0', textAlign: 'center' }}>
            No thumbs-down feedback yet.
          </div>
        )}
      </div>
    </div>
  )
}
