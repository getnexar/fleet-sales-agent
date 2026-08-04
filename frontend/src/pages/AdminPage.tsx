import { useState } from 'react'
import Dashboard from '../components/admin/Dashboard'
import ConversationList from '../components/admin/ConversationList'
import ConfigEditor from '../components/admin/ConfigEditor'

type Tab = 'dashboard' | 'conversations' | 'config'

interface ConfigTarget {
  resource: string
  detail: string
  tab: 'faqs' | 'prompts'
}

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')
  const [configTarget, setConfigTarget] = useState<ConfigTarget | null>(null)
  const [conversationsFailureFilter, setConversationsFailureFilter] = useState<string | null>(null)

  function navigateToConfig(resource: string, detail: string) {
    const tab = resource === 'faq' ? 'faqs' : 'prompts'
    setConfigTarget({ resource, detail, tab })
    setActiveTab('config')
  }

  function navigateToFailedConversations(bucket: string) {
    setConversationsFailureFilter(bucket)
    setActiveTab('conversations')
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--background)',
      color: 'var(--foreground)',
      fontFamily: 'var(--font-sans, system-ui, sans-serif)',
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
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}>
        <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: '-0.02em', marginRight: 16, fontFamily: 'var(--font-heading)' }}>
          Nexar Fleet <span style={{ color: 'var(--muted-foreground)', fontWeight: 400 }}>Admin</span>
        </div>

        {([
          { key: 'dashboard', label: 'Dashboard' },
          { key: 'conversations', label: 'Conversations' },
          { key: 'config', label: 'Agent Overview' },
        ] as { key: Tab; label: string }[]).map(tab => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveTab(tab.key)
              if (tab.key !== 'config') setConfigTarget(null)
              if (tab.key !== 'conversations') setConversationsFailureFilter(null)
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
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '28px 24px' }}>
        {activeTab === 'dashboard' && <Dashboard onSelectFailureBucket={navigateToFailedConversations} />}

        {activeTab === 'conversations' && (
          <ConversationList onNavigateConfig={navigateToConfig} initialHubspotFailure={conversationsFailureFilter} />
        )}

        {activeTab === 'config' && (
          <ConfigEditor
            key={configTarget ? `${configTarget.resource}:${configTarget.detail}` : 'default'}
            initialTab={configTarget?.tab === 'faqs' ? 'faqs' : 'context'}
            highlightResource={configTarget?.resource}
            highlightDetail={configTarget?.detail}
          />
        )}
      </div>
    </div>
  )
}
