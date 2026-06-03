import { useState, useEffect, useRef } from 'react'
import { useAdminConfig, useAgentContext, useCurrentUser } from '../../hooks/useAdmin'
import type { FaqEntry, AgentContext } from '../../types'

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 12px',
  borderRadius: 8,
  border: '1px solid var(--border)',
  fontSize: 13,
  background: 'var(--background)',
  color: 'var(--foreground)',
  fontFamily: 'inherit',
  boxSizing: 'border-box',
  lineHeight: 1.6,
}

function saveButtonStyle(disabled: boolean): React.CSSProperties {
  return {
    marginTop: 20,
    padding: '9px 24px',
    borderRadius: 9,
    border: 'none',
    background: disabled ? 'var(--muted)' : 'var(--primary)',
    color: disabled ? 'var(--muted-foreground)' : 'var(--primary-foreground)',
    cursor: disabled ? 'default' : 'pointer',
    fontSize: 14,
    fontWeight: 600,
  }
}

// ─── Agent Context Editor ────────────────────────────────────────────────────

const CONTEXT_FIELDS: {
  key: keyof AgentContext
  label: string
  description: string
  placeholder: string
}[] = [
  {
    key: 'business_context',
    label: 'Business Context',
    description: 'Describe Nexar, what we sell, key differentiators, and anything Alex should know about the company and our customers.',
    placeholder: `Nexar is an AI-powered fleet dashcam company helping small and mid-size businesses protect their drivers and reduce insurance costs. We sell three dashcam models — Beam 2 Mini, Beam 2, and Nexar One — all cloud-connected with a live platform for fleet managers to monitor trips, review incidents, and generate reports.

Our target customers run fleets of 5–200 vehicles across industries like construction, delivery, HVAC, rideshare, and transportation.

Key value props:
- Protects against false accident claims with HD video evidence
- Reduces insurance premiums (customers often save more than the subscription cost)
- Easy self-install — no technician needed
- No long contracts required (month-to-month available starting at $25/vehicle/month)`,
  },
  {
    key: 'escalations',
    label: 'Escalations',
    description: 'When should Alex escalate, and to whom? What situations need a human sales rep?',
    placeholder: `Escalate to a human when:
- The fleet has 50+ vehicles (enterprise-level deal — higher priority)
- The customer asks to speak with someone or requests a personal demo
- The customer mentions an active legal dispute or insurance claim in progress
- The customer is asking about custom pricing, volume discounts, or contract terms we don't advertise

For follow-up and enterprise leads: fleet@getnexar.com`,
  },
  {
    key: 'tone_style',
    label: 'Response Tone & Style',
    description: "How should Alex sound? Any terminology to use or avoid? Phrases that feel off-brand?",
    placeholder: `Write like a knowledgeable colleague — warm, direct, and concise.

Terminology to use:
- "dashcam" (not "dash cam" or "camera system")
- "fleet manager" or "fleet operator" (not "driver manager")
- "contact details" (not "personal information")

Avoid:
- Saying anything is "cheap" — use "cost-effective" or give the actual price
- Promising specific delivery dates or installation timelines
- Making definitive claims about insurance savings — say "customers often see" or "many fleets report"
- Using corporate buzzwords like "synergy", "holistic", "best-in-class"`,
  },
  {
    key: 'dos_donts',
    label: 'Dos & Don\'ts',
    description: 'Explicit behaviors Alex should always do or never do.',
    placeholder: `DO:
- Share the platform walkthrough video when a customer asks about features or how it works
- Mention the month-to-month option upfront — it reduces hesitation for first-time buyers
- Ask for fleet size early — it helps size the recommendation correctly
- Confirm that cameras work on all vehicle types (vans, trucks, sedans, etc.)

DON'T:
- Discuss competitor products or pricing
- Promise specific installation support timelines
- Collect payment information — always route purchases to the sales team
- Describe pricing that isn't listed (no custom quotes via chat)
- Share internal team information, email addresses other than fleet@getnexar.com, or internal processes`,
  },
]

function AgentContextEditor() {
  const { context, loading, saving, saved, error, load, save } = useAgentContext()
  const [local, setLocal] = useState<AgentContext>({
    business_context: '', escalations: '', tone_style: '', dos_donts: '',
  })

  useEffect(() => { load() }, [load])
  useEffect(() => { if (context) setLocal(context) }, [context])

  if (loading) return <div style={{ color: 'var(--muted-foreground)', padding: '20px 0' }}>Loading…</div>

  return (
    <div>
      <p style={{ fontSize: 13, color: 'var(--muted-foreground)', marginBottom: 20, lineHeight: 1.6, marginTop: 0 }}>
        Use these fields to customize Alex's knowledge and behavior — no technical expertise needed.
        Fill in what's relevant and leave others blank. Changes go live immediately after saving.
      </p>

      {error && <div style={{ color: '#ef4444', fontSize: 13, marginBottom: 12, padding: '8px 12px', background: '#fef2f2', borderRadius: 8 }}>{error}</div>}
      {saved && (
        <div style={{ background: '#dcfce7', color: '#166534', borderRadius: 8, padding: '8px 14px', marginBottom: 16, fontSize: 13 }}>
          Saved — changes are live.
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {CONTEXT_FIELDS.map(field => (
          <div key={field.key} style={{ background: 'var(--card)', border: '1px solid var(--border)', borderRadius: 10, padding: '16px 18px' }}>
            <label style={{ display: 'block', fontSize: 14, fontWeight: 600, marginBottom: 4, color: 'var(--foreground)' }}>
              {field.label}
            </label>
            <p style={{ fontSize: 12, color: 'var(--muted-foreground)', margin: '0 0 10px 0', lineHeight: 1.5 }}>
              {field.description}
            </p>
            <textarea
              value={local[field.key]}
              onChange={e => setLocal(prev => ({ ...prev, [field.key]: e.target.value }))}
              placeholder={field.placeholder}
              rows={5}
              style={{ ...inputStyle, resize: 'vertical' }}
            />
          </div>
        ))}
      </div>

      <button onClick={() => save(local)} disabled={saving} style={saveButtonStyle(saving)}>
        {saving ? 'Saving…' : 'Save & Apply'}
      </button>
    </div>
  )
}

// ─── FAQ Editor ───────────────────────────────────────────────────────────────

function FaqEditor({
  faqs,
  onChange,
  highlightEntry,
}: {
  faqs: FaqEntry[]
  onChange: (f: FaqEntry[]) => void
  highlightEntry?: string
}) {
  const [expanded, setExpanded] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const highlightRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (highlightEntry && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [highlightEntry])

  const filtered = search.trim()
    ? faqs.map((f, idx) => ({ faq: f, idx })).filter(({ faq }) => {
        const q = search.toLowerCase()
        return (
          faq.question.toLowerCase().includes(q) ||
          faq.answer.toLowerCase().includes(q) ||
          (faq.category || '').toLowerCase().includes(q)
        )
      })
    : faqs.map((f, idx) => ({ faq: f, idx }))

  function update(originalIdx: number, field: keyof FaqEntry, val: string) {
    const next = [...faqs]
    next[originalIdx] = { ...next[originalIdx], [field]: val }
    onChange(next)
  }

  function remove(originalIdx: number) {
    onChange(faqs.filter((_, i) => i !== originalIdx))
    setExpanded(null)
  }

  function add() {
    onChange([...faqs, { question: '', answer: '', category: '' }])
    setExpanded(faqs.length)
    setSearch('')
  }

  return (
    <div>
      {/* Top bar: search + add button */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <div style={{ flex: 1, position: 'relative' }}>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={`Search ${faqs.length} FAQ entries…`}
            style={{
              ...inputStyle,
              paddingLeft: 36,
              border: '2px solid var(--primary)',
              borderRadius: 9,
              fontSize: 14,
            }}
          />
          <span style={{ position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', color: 'var(--primary)', pointerEvents: 'none', fontSize: 15 }}>
            🔍
          </span>
          {search && (
            <button
              onClick={() => setSearch('')}
              style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted-foreground)', fontSize: 18, padding: '0 2px', lineHeight: 1 }}
            >
              ×
            </button>
          )}
        </div>
        <button
          onClick={add}
          style={{
            padding: '9px 18px',
            borderRadius: 9,
            border: 'none',
            background: 'var(--primary)',
            color: 'var(--primary-foreground)',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 600,
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          + Add FAQ
        </button>
      </div>

      {search && (
        <div style={{ fontSize: 12, color: 'var(--muted-foreground)', marginBottom: 10 }}>
          {filtered.length} result{filtered.length !== 1 ? 's' : ''} for "{search}"
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {filtered.map(({ faq, idx }) => {
          const isHighlighted = highlightEntry && faq.question.toLowerCase().includes(highlightEntry.toLowerCase())
          const isOpen = expanded === idx
          return (
            <div
              key={idx}
              ref={isHighlighted ? highlightRef : null}
              style={{
                border: `1px solid ${isHighlighted ? 'var(--primary)' : 'var(--border)'}`,
                borderRadius: 10,
                overflow: 'hidden',
                boxShadow: isHighlighted ? '0 0 0 2px var(--primary)' : 'none',
              }}
            >
              <div
                onClick={() => setExpanded(isOpen ? null : idx)}
                style={{ padding: '10px 14px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: isOpen ? 'var(--muted)' : 'var(--card)' }}
              >
                <span style={{ fontSize: 13, fontWeight: 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {faq.question || <em style={{ color: 'var(--muted-foreground)' }}>New FAQ</em>}
                </span>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
                  {faq.category && (
                    <span style={{ fontSize: 11, background: 'var(--muted)', borderRadius: 6, padding: '1px 7px', color: 'var(--muted-foreground)' }}>
                      {faq.category}
                    </span>
                  )}
                  <span style={{ fontSize: 14, color: 'var(--muted-foreground)' }}>{isOpen ? '▲' : '▼'}</span>
                </div>
              </div>
              {isOpen && (
                <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 10, background: 'var(--background)' }}>
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>Question</label>
                    <input value={faq.question} onChange={e => update(idx, 'question', e.target.value)} style={inputStyle} />
                  </div>
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>Answer</label>
                    <textarea value={faq.answer} onChange={e => update(idx, 'answer', e.target.value)} rows={5} style={{ ...inputStyle, resize: 'vertical' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>Category (optional)</label>
                    <input value={faq.category || ''} onChange={e => update(idx, 'category', e.target.value)} style={inputStyle} placeholder="e.g. Pricing, Installation, Hardware" />
                  </div>
                  <button
                    onClick={() => remove(idx)}
                    style={{ alignSelf: 'flex-start', fontSize: 12, padding: '4px 12px', borderRadius: 7, border: '1px solid #fca5a5', background: '#fef2f2', color: '#b91c1c', cursor: 'pointer' }}
                  >
                    Remove entry
                  </button>
                </div>
              )}
            </div>
          )
        })}

        {filtered.length === 0 && search && (
          <div style={{ textAlign: 'center', color: 'var(--muted-foreground)', padding: '24px 0', fontSize: 13 }}>
            No FAQs match "{search}"
          </div>
        )}

        {filtered.length === 0 && !search && (
          <div style={{ textAlign: 'center', color: 'var(--muted-foreground)', padding: '24px 0', fontSize: 13 }}>
            No FAQ entries yet. Click "+ Add FAQ" to create the first one.
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Main ConfigEditor ────────────────────────────────────────────────────────

export default function ConfigEditor({
  initialTab = 'context',
  highlightResource,
  highlightDetail,
}: {
  initialTab?: 'context' | 'faqs'
  highlightResource?: string
  highlightDetail?: string
}) {
  const { config, loading, saving, saved, error, load, saveFaqs } = useAdminConfig()
  const { load: loadUser } = useCurrentUser()
  const [tab, setTab] = useState<'context' | 'faqs'>(initialTab)
  const [localFaqs, setLocalFaqs] = useState<FaqEntry[]>([])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadUser() }, [loadUser])

  useEffect(() => {
    if (config) setLocalFaqs(config.faqs || [])
  }, [config])

  useEffect(() => {
    if (initialTab) setTab(initialTab)
  }, [initialTab])

  useEffect(() => {
    if (highlightResource === 'faq') setTab('faqs')
    if (highlightResource === 'phase_prompt' || highlightResource === 'core_prompt') setTab('context')
  }, [highlightResource])

  const highlightFaqEntry = highlightResource === 'faq' ? highlightDetail : undefined

  if (loading && !config) return <div style={{ color: 'var(--muted-foreground)', padding: '20px 0' }}>Loading…</div>
  if (error && !config) return <div style={{ color: '#ef4444', padding: '12px 0' }}>{error}</div>

  return (
    <div>
      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 24, borderBottom: '1px solid var(--border)' }}>
        {[
          { key: 'context', label: 'Agent Instructions' },
          { key: 'faqs', label: 'Knowledge Base' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as 'context' | 'faqs')}
            style={{
              padding: '8px 20px',
              border: 'none',
              borderBottom: tab === t.key ? '2px solid var(--primary)' : '2px solid transparent',
              background: 'none',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: tab === t.key ? 600 : 400,
              color: tab === t.key ? 'var(--foreground)' : 'var(--muted-foreground)',
              marginBottom: -1,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Error / saved banners (FAQs tab) */}
      {error && tab === 'faqs' && <div style={{ color: '#ef4444', marginBottom: 12, fontSize: 13 }}>{error}</div>}
      {saved && tab === 'faqs' && (
        <div style={{ background: '#dcfce7', color: '#166534', borderRadius: 8, padding: '8px 14px', marginBottom: 12, fontSize: 13 }}>
          Saved and reloaded — changes are live.
        </div>
      )}

      {tab === 'context' && <AgentContextEditor />}

      {tab === 'faqs' && (
        <div>
          <FaqEditor
            faqs={localFaqs}
            onChange={setLocalFaqs}
            highlightEntry={highlightFaqEntry}
          />
          <button
            onClick={() => saveFaqs(localFaqs)}
            disabled={saving}
            style={saveButtonStyle(saving)}
          >
            {saving ? 'Saving…' : 'Save & Reload'}
          </button>
        </div>
      )}
    </div>
  )
}

export { inputStyle }
