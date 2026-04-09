import ReactMarkdown from 'react-markdown'
import type { Message } from '../types'

interface Props {
  message: Message
}

export default function MessageBubble({ message }: Props) {
  const isUser = message.role === 'user'

  return (
    <div style={{ ...styles.row, justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      {!isUser && <div style={styles.avatar}>A</div>}

      <div style={{ maxWidth: '75%' }}>
        <div style={isUser ? styles.userBubble : styles.assistantBubble}>
          {isUser ? (
            message.content
          ) : (
            <ReactMarkdown
              components={{
                p: ({ children }) => <p style={{ margin: '0 0 8px 0' }}>{children}</p>,
                ul: ({ children }) => <ul style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ul>,
                ol: ({ children }) => <ol style={{ margin: '4px 0', paddingLeft: 20 }}>{children}</ol>,
                li: ({ children }) => <li style={{ marginBottom: 2 }}>{children}</li>,
                strong: ({ children }) => <strong style={{ fontWeight: 600 }}>{children}</strong>,
                a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'underline' }}>{children}</a>,
              }}
            >
              {message.content}
            </ReactMarkdown>
          )}
        </div>
        {!isUser && message.quote_url && (
          <a
            href={message.quote_url}
            target="_blank"
            rel="noreferrer"
            style={styles.quoteButton}
          >
            Review & Sign Your Quote →
          </a>
        )}
      </div>

      {isUser && <div style={styles.userDot} />}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  row: {
    display: 'flex',
    alignItems: 'flex-end',
    gap: 8,
    marginBottom: 8,
  },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: '50%',
    background: 'var(--primary)',
    color: 'var(--primary-foreground)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 700,
    fontSize: 13,
    flexShrink: 0,
  },
  userDot: {
    width: 28,
    height: 28,
    flexShrink: 0,
  },
  assistantBubble: {
    background: 'var(--card)',
    border: '1px solid var(--border)',
    borderRadius: '18px 18px 18px 4px',
    padding: '10px 14px',
    fontSize: 14,
    lineHeight: 1.5,
    color: 'var(--foreground)',
    fontFamily: 'var(--font-sans)',
  },
  userBubble: {
    background: 'var(--primary)',
    borderRadius: '18px 18px 4px 18px',
    padding: '10px 14px',
    fontSize: 14,
    lineHeight: 1.5,
    color: 'var(--primary-foreground)',
    whiteSpace: 'pre-wrap',
    fontFamily: 'var(--font-sans)',
  },
  quoteButton: {
    display: 'block',
    marginTop: 8,
    padding: '10px 16px',
    background: 'var(--primary)',
    color: 'var(--primary-foreground)',
    borderRadius: 10,
    fontSize: 14,
    fontWeight: 600,
    textDecoration: 'none',
    textAlign: 'center' as const,
    fontFamily: 'var(--font-sans)',
  },
}
