import { useState, useRef, useEffect } from 'react'
import { useChat } from '../hooks/useChat'
import MessageBubble from './MessageBubble'

export default function ChatWidget() {
  const [input, setInput] = useState('')
  const { messages, isLoading, sendMessage } = useChat()
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  useEffect(() => {
    if (!isLoading) {
      inputRef.current?.focus()
    }
  }, [isLoading])

  const handleSend = () => {
    const text = input.trim()
    if (!text) return
    setInput('')
    sendMessage(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <div style={styles.avatar}>A</div>
          <div>
            <div style={styles.agentName}>Alex</div>
            <div style={styles.agentStatus}>● Online · Nexar Fleet Assistant</div>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div style={styles.messages}>
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
          />
        ))}

        {isLoading && (
          <div style={styles.typingRow}>
            <div style={styles.avatar}>A</div>
            <div style={styles.typingBubble}>
              <span style={styles.dot} />
              <span style={{ ...styles.dot, animationDelay: '0.2s' }} />
              <span style={{ ...styles.dot, animationDelay: '0.4s' }} />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={styles.inputArea}>
        <input
          ref={inputRef}
          style={styles.input}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about Fleet dash cams..."
          autoFocus
        />
        <button
          style={{ ...styles.sendBtn, opacity: !input.trim() ? 0.4 : 1 }}
          onClick={handleSend}
          disabled={!input.trim()}
        >
          ➤
        </button>
      </div>

      {/* Footer */}
      <div style={styles.footer}>
        <span>Powered by </span>
        <a href="https://fleet.getnexar.com" target="_blank" rel="noreferrer" style={styles.footerLink}>
          Nexar Fleet
        </a>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    maxWidth: 680,
    margin: '0 auto',
    fontFamily: 'var(--font-sans)',
    background: 'var(--card)',
    boxShadow: '0 0 40px rgba(0,0,0,0.12)',
  },
  header: {
    background: 'oklch(0.141 0.004 285.823)',
    color: '#fff',
    padding: '16px 20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: '50%',
    background: 'var(--primary)',
    color: 'var(--primary-foreground)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 700,
    fontSize: 16,
    flexShrink: 0,
  },
  agentName: { fontWeight: 600, fontSize: 15, fontFamily: 'var(--font-heading)' },
  agentStatus: { fontSize: 12, color: 'var(--muted-foreground)', marginTop: 2 },
  messages: {
    flex: 1,
    overflowY: 'auto',
    padding: '20px 16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    background: 'var(--background)',
  },
  typingRow: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: 8,
    marginTop: 4,
  },
  typingBubble: {
    background: 'var(--card)',
    border: '1px solid var(--border)',
    borderRadius: '18px 18px 18px 4px',
    padding: '12px 16px',
    display: 'flex',
    gap: 4,
    alignItems: 'center',
  },
  dot: {
    width: 7,
    height: 7,
    background: 'var(--muted-foreground)',
    borderRadius: '50%',
    display: 'inline-block',
    animation: 'bounce 1s infinite',
  },
  followUps: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 8,
    paddingLeft: 44,
  },
  followUpBtn: {
    background: 'var(--card)',
    border: '1px solid var(--primary)',
    borderRadius: 20,
    padding: '6px 14px',
    fontSize: 13,
    color: 'var(--primary)',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  inputArea: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '12px 16px',
    borderTop: '1px solid var(--border)',
    background: 'var(--card)',
  },
  input: {
    flex: 1,
    border: '1px solid var(--border)',
    borderRadius: 24,
    padding: '10px 16px',
    fontSize: 14,
    outline: 'none',
    background: 'var(--background)',
    fontFamily: 'var(--font-sans)',
    color: 'var(--foreground)',
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: '50%',
    background: 'var(--primary)',
    color: 'var(--primary-foreground)',
    border: 'none',
    cursor: 'pointer',
    fontSize: 16,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'opacity 0.15s',
  },
  footer: {
    textAlign: 'center',
    padding: '8px',
    fontSize: 11,
    color: 'var(--muted-foreground)',
    borderTop: '1px solid var(--border)',
  },
  footerLink: { color: 'var(--primary)', textDecoration: 'none' },
}
