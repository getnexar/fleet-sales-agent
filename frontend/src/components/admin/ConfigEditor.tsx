import { useState, useEffect, useRef } from 'react'
import { useAdminConfig } from '../../hooks/useAdmin'
import type { FaqEntry } from '../../types'

const PHASE_ORDER = [
  'CONNECT', 'QUALIFY', 'QUALIFY_CAMERA_SELECTION',
  'PRESENT', 'HANDLE_OBJECTIONS', 'CLOSE_QUOTE', 'CLOSE_DEMO', 'CLOSE_TRIAL',
]

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
  const highlightRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (highlightEntry && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [highlightEntry])

  function update(i: number, field: keyof FaqEntry, val: string) {
    const next = [...faqs]
    next[i] = { ...next[i], [field]: val }
    onChange(next)
  }

  function remove(i: number) {
    onChange(faqs.filter((_, idx) => idx !== i))
  }

  function add() {
    onChange([...faqs, { question: '', answer: '', category: '' }])
    setExpanded(faqs.length)
  }

  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {faqs.map((faq, i) => {
          const isHighlighted = highlightEntry && faq.question.toLowerCase().includes(highlightEntry.toLowerCase())
          return (
            <div
              key={i}
              ref={isHighlighted ? highlightRef : null}
              style={{
                border: `1px solid ${isHighlighted ? 'var(--primary)' : 'var(--border)'}`,
                borderRadius: 10,
                overflow: 'hidden',
                boxShadow: isHighlighted ? '0 0 0 2px var(--primary)' : 'none',
              }}
            >
              {/* Collapsed header */}
              <div
                onClick={() => setExpanded(expanded === i ? null : i)}
                style={{
                  padding: '10px 14px',
                  cursor: 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: expanded === i ? 'var(--muted)' : 'var(--card)',
                }}
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
                  <span style={{ fontSize: 14, color: 'var(--muted-foreground)' }}>{expanded === i ? '▲' : '▼'}</span>
                </div>
              </div>

              {/* Expanded form */}
              {expanded === i && (
                <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 10, background: 'var(--background)' }}>
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>Question</label>
                    <input
                      value={faq.question}
                      onChange={e => update(i, 'question', e.target.value)}
                      style={inputStyle}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>Answer</label>
                    <textarea
                      value={faq.answer}
                      onChange={e => update(i, 'answer', e.target.value)}
                      rows={5}
                      style={{ ...inputStyle, resize: 'vertical' }}
                    />
                  </div>
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted-foreground)', display: 'block', marginBottom: 4 }}>Category (optional)</label>
                    <input
                      value={faq.category || ''}
                      onChange={e => update(i, 'category', e.target.value)}
                      style={inputStyle}
                    />
                  </div>
                  <button
                    onClick={() => remove(i)}
                    style={{ alignSelf: 'flex-start', fontSize: 12, padding: '4px 12px', borderRadius: 7, border: '1px solid #fca5a5', background: '#fef2f2', color: '#b91c1c', cursor: 'pointer' }}
                  >
                    Remove entry
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <button
        onClick={add}
        style={{ marginTop: 12, fontSize: 13, padding: '7px 16px', borderRadius: 8, border: '1px dashed var(--border)', background: 'var(--background)', cursor: 'pointer', color: 'var(--muted-foreground)', width: '100%' }}
      >
        + Add FAQ entry
      </button>
    </div>
  )
}

// ─── Prompts Editor ───────────────────────────────────────────────────────────

function PromptsEditor({
  corePrompt,
  phasePrompts,
  onCoreChange,
  onPhaseChange,
  highlightPhase,
}: {
  corePrompt: string
  phasePrompts: Record<string, string>
  onCoreChange: (v: string) => void
  onPhaseChange: (phase: string, v: string) => void
  highlightPhase?: string
}) {
  const [expandedPhase, setExpandedPhase] = useState<string | null>(highlightPhase || null)
  const [coreExpanded, setCoreExpanded] = useState(!highlightPhase)
  const highlightRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (highlightPhase) {
      setExpandedPhase(highlightPhase)
      setTimeout(() => highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100)
    }
  }, [highlightPhase])

  const phases = PHASE_ORDER.filter(p => p in phasePrompts)
  // Include any phases in phasePrompts not in our ordered list
  const extraPhases = Object.keys(phasePrompts).filter(p => !PHASE_ORDER.includes(p))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Core prompt */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
        <div
          onClick={() => setCoreExpanded(!coreExpanded)}
          style={{ padding: '10px 14px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', background: coreExpanded ? 'var(--muted)' : 'var(--card)' }}
        >
          <span style={{ fontSize: 13, fontWeight: 600 }}>Core Prompt</span>
          <span style={{ fontSize: 12, color: 'var(--muted-foreground)' }}>Identity · Style rules · JSON schema</span>
          <span style={{ fontSize: 14, color: 'var(--muted-foreground)', marginLeft: 12 }}>{coreExpanded ? '▲' : '▼'}</span>
        </div>
        {coreExpanded && (
          <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border)', background: 'var(--background)' }}>
            <div style={{ fontSize: 12, color: 'var(--muted-foreground)', marginBottom: 6 }}>
              Use <code style={{ background: 'var(--muted)', padding: '1px 4px', borderRadius: 4 }}>{'{{faqs}}'}</code> as the placeholder where FAQ content is injected.
            </div>
            <textarea
              value={corePrompt}
              onChange={e => onCoreChange(e.target.value)}
              rows={20}
              style={{ ...inputStyle, resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }}
            />
          </div>
        )}
      </div>

      {/* Phase prompts */}
      {[...phases, ...extraPhases].map(phase => {
        const isHighlighted = phase === highlightPhase
        return (
          <div
            key={phase}
            ref={isHighlighted ? highlightRef : null}
            style={{
              border: `1px solid ${isHighlighted ? 'var(--primary)' : 'var(--border)'}`,
              borderRadius: 10,
              overflow: 'hidden',
              boxShadow: isHighlighted ? '0 0 0 2px var(--primary)' : 'none',
            }}
          >
            <div
              onClick={() => setExpandedPhase(expandedPhase === phase ? null : phase)}
              style={{ padding: '10px 14px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: expandedPhase === phase ? 'var(--muted)' : 'var(--card)' }}
            >
              <span style={{ fontSize: 13, fontWeight: 600 }}>{phase}</span>
              <span style={{ fontSize: 14, color: 'var(--muted-foreground)' }}>{expandedPhase === phase ? '▲' : '▼'}</span>
            </div>
            {expandedPhase === phase && (
              <div style={{ padding: '12px 14px', borderTop: '1px solid var(--border)', background: 'var(--background)' }}>
                <textarea
                  value={phasePrompts[phase] || ''}
                  onChange={e => onPhaseChange(phase, e.target.value)}
                  rows={16}
                  style={{ ...inputStyle, resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }}
                />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Main ConfigEditor ────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '7px 10px',
  borderRadius: 8,
  border: '1px solid var(--border)',
  fontSize: 13,
  background: 'var(--background)',
  color: 'var(--foreground)',
  fontFamily: 'inherit',
  boxSizing: 'border-box',
}

export default function ConfigEditor({
  initialTab = 'faqs',
  highlightResource,
  highlightDetail,
}: {
  initialTab?: 'faqs' | 'prompts'
  highlightResource?: string
  highlightDetail?: string
}) {
  const { config, loading, saving, saved, error, load, saveFaqs, savePrompts } = useAdminConfig()
  const [tab, setTab] = useState<'faqs' | 'prompts'>(initialTab)
  const [localFaqs, setLocalFaqs] = useState<FaqEntry[]>([])
  const [localCore, setLocalCore] = useState('')
  const [localPhase, setLocalPhase] = useState<Record<string, string>>({})
  const [jsonError, setJsonError] = useState<string | null>(null)

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (config) {
      setLocalFaqs(config.faqs || [])
      setLocalCore(config.core_prompt || '')
      setLocalPhase(config.phase_prompts || {})
    }
  }, [config])

  useEffect(() => {
    if (initialTab) setTab(initialTab)
  }, [initialTab])

  // Auto-navigate to the right tab/section when coming from a triage badge
  const highlightFaqEntry = highlightResource === 'faq' ? highlightDetail : undefined
  const highlightPhase = highlightResource === 'phase_prompt' ? highlightDetail : undefined
  const highlightCore = highlightResource === 'core_prompt'

  useEffect(() => {
    if (highlightResource === 'faq') setTab('faqs')
    if (highlightResource === 'phase_prompt' || highlightResource === 'core_prompt') setTab('prompts')
  }, [highlightResource])

  async function handleSaveFaqs() {
    setJsonError(null)
    await saveFaqs(localFaqs)
  }

  async function handleSavePrompts() {
    setJsonError(null)
    await savePrompts(localCore, localPhase)
  }

  if (loading) return <div style={{ color: 'var(--muted-foreground)', padding: '20px 0' }}>Loading config…</div>
  if (error && !config) return <div style={{ color: '#ef4444', padding: '12px 0' }}>{error}</div>

  return (
    <div>
      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 20, borderBottom: '1px solid var(--border)' }}>
        {[
          { key: 'faqs', label: 'FAQ Knowledge Base' },
          { key: 'prompts', label: 'Prompts & Instructions' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as 'faqs' | 'prompts')}
            style={{
              padding: '8px 18px',
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

      {/* Error / saved banners */}
      {error && <div style={{ color: '#ef4444', marginBottom: 12, fontSize: 13 }}>{error}</div>}
      {jsonError && <div style={{ color: '#ef4444', marginBottom: 12, fontSize: 13 }}>JSON error: {jsonError}</div>}
      {saved && (
        <div style={{ background: '#dcfce7', color: '#166534', borderRadius: 8, padding: '8px 14px', marginBottom: 12, fontSize: 13 }}>
          Saved and reloaded — changes are live.
        </div>
      )}

      {/* FAQ tab */}
      {tab === 'faqs' && (
        <div>
          <FaqEditor
            faqs={localFaqs}
            onChange={setLocalFaqs}
            highlightEntry={highlightFaqEntry}
          />
          <button
            onClick={handleSaveFaqs}
            disabled={saving}
            style={saveButtonStyle(saving)}
          >
            {saving ? 'Saving…' : 'Save & Reload'}
          </button>
        </div>
      )}

      {/* Prompts tab */}
      {tab === 'prompts' && (
        <div>
          {highlightCore && (
            <div style={{ background: '#fef3c7', borderRadius: 8, padding: '8px 14px', marginBottom: 12, fontSize: 13, color: '#92400e' }}>
              Triage points to the Core Prompt. The relevant rule is: <strong>{highlightDetail}</strong>
            </div>
          )}
          <PromptsEditor
            corePrompt={localCore}
            phasePrompts={localPhase}
            onCoreChange={setLocalCore}
            onPhaseChange={(phase, val) => setLocalPhase(p => ({ ...p, [phase]: val }))}
            highlightPhase={highlightPhase}
          />
          <button
            onClick={handleSavePrompts}
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
