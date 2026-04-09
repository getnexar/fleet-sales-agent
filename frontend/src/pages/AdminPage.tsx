import { useState } from 'react'
import ConversationList from '../components/admin/ConversationList'
import FeedbackPanel from '../components/admin/FeedbackPanel'
import ConfigEditor from '../components/admin/ConfigEditor'

type Tab = 'conversations' | 'feedback' | 'config'

// When navigating from a triage badge, we pass resource + detail to jump to the right section
interface ConfigTarget {
  resource: string
  detail: string
  tab: 'faqs' | 'prompts'
}

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<Tab>('conversations')
  const [configTarget, setConfigTarget] = useState<ConfigTarget | null>(null)

  function navigateToConfig(resource: string, detail: string) {
    const tab = resource === 'faq' ? 'faqs' : 'prompts'
    setConfigTarget({ resource, detail, tab })
    setActiveTab('config')
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--background)',
      color: 'var(--foreground)',
      fontFamily: 'var(--font-body, system-ui, sans-serif)',
    }}>
      {/* Top nav */}
      <div style={{
        borderBottom: '1px solid var(--border)',
        background: 'var(--card)',
        padding: '0 32px',
        display: 'flex',
        alignItems: 'center',
        gap: 32,
        height: 52,
      }}>
        <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: '-0.02em', marginRight: 16 }}>
          Nexar Fleet <span style={{ color: 'var(--muted-foreground)', fontWeight: 400 }}>Admin</span>
        </div>

        {([
          { key: 'conversations', label: 'Conversations' },
          { key: 'feedback', label: 'Feedback' },
          { key: 'config', label: 'Config' },
        ] as { key: Tab; label: string }[]).map(tab => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveTab(tab.key)
              if (tab.key !== 'config') setConfigTarget(null)
            }}
            style={{
              background: 'none',
              border: 'none',
              borderBottom: activeTab === tab.key ? '2px solid var(--primary)' : '2px solid transparent',
              padding: '16px 0',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: activeTab === tab.key ? 600 : 400,
              color: activeTab === tab.key ? 'var(--foreground)' : 'var(--muted-foreground)',
              height: '100%',
              transition: 'color .1s',
            }}
          >
            {tab.label}
          </button>
        ))}

        <div style={{ flex: 1 }} />

        <a
          href="/"
          style={{ fontSize: 12, color: 'var(--muted-foreground)', textDecoration: 'none' }}
        >
          ← Chat
        </a>
      </div>

      {/* Content */}
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '28px 24px' }}>
        {activeTab === 'conversations' && (
          <ConversationList onNavigateConfig={navigateToConfig} />
        )}

        {activeTab === 'feedback' && (
          <FeedbackPanel onNavigateConfig={navigateToConfig} />
        )}

        {activeTab === 'config' && (
          <ConfigEditor
            key={configTarget ? `${configTarget.resource}:${configTarget.detail}` : 'default'}
            initialTab={configTarget?.tab}
            highlightResource={configTarget?.resource}
            highlightDetail={configTarget?.detail}
          />
        )}
      </div>
    </div>
  )
}
