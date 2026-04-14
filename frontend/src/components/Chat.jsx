import { useState, useRef, useEffect } from 'react'
import { sendChatStream } from '../api/client.js'
import styles from '../styles/components.module.css'

export default function Chat() {
  const [messages, setMessages] = useState([])   // [{role, content, sources?}]
  const [input, setInput]       = useState('')
  const [loading, setLoading]   = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleSend(e) {
    e.preventDefault()
    const text = input.trim()
    if (!text || loading) return

    const userMsg = { role: 'user', content: text }
    const next = [...messages, userMsg]
    setMessages(next)
    setInput('')
    setLoading(true)

    // Add a placeholder assistant message that we'll stream into
    const assistantIdx = next.length
    const withPlaceholder = [...next, { role: 'assistant', content: '', sources: [] }]
    setMessages(withPlaceholder)

    try {
      const history = next.map(m => ({ role: m.role, content: m.content }))
      const { sources } = await sendChatStream(
        text,
        history.slice(0, -1),
        (token) => {
          // Append each token to the assistant message
          setMessages(prev => {
            const updated = [...prev]
            updated[assistantIdx] = {
              ...updated[assistantIdx],
              content: updated[assistantIdx].content + token,
            }
            return updated
          })
        },
      )
      // Attach sources once stream completes
      setMessages(prev => {
        const updated = [...prev]
        updated[assistantIdx] = { ...updated[assistantIdx], sources }
        return updated
      })
    } catch (err) {
      setMessages(prev => {
        const updated = [...prev]
        updated[assistantIdx] = {
          ...updated[assistantIdx],
          content: `Sorry, something went wrong: ${err.message}`,
        }
        return updated
      })
    } finally {
      setLoading(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) handleSend(e)
  }

  return (
    <div className={styles.chatPanel}>
      <div className={styles.chatMessages}>
        {messages.length === 0 && (
          <div className={styles.chatEmpty}>
            <div className={styles.chatEmptyIcon}>◎</div>
            <p className={styles.chatEmptyTitle}>Ask anything about your journal</p>
            <p className={styles.chatEmptyHint}>
              Try "What was I stressed about last month?" or "How often have I gone to the gym?"
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`${styles.chatBubbleRow} ${msg.role === 'user' ? styles.chatBubbleRowUser : ''}`}>
            {msg.role === 'assistant' && (
              <div className={styles.chatAvatar}>✦</div>
            )}
            <div className={`${styles.chatBubble} ${msg.role === 'user' ? styles.chatBubbleUser : styles.chatBubbleAssistant} ${loading && msg.role === 'assistant' && i === messages.length - 1 ? styles.chatBubbleStreaming : ''}`}>
              <p className={styles.chatBubbleText}>{msg.content}</p>
              {msg.sources && msg.sources.length > 0 && (
                <div className={styles.chatSources}>
                  <span className={styles.chatSourcesLabel}>Sources</span>
                  {msg.sources.map((s, j) => (
                    <span key={j} className={styles.chatSourceChip}>
                      {formatDate(s.entry_date)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && messages.length > 0 && messages[messages.length - 1].content === '' && (
          <div className={styles.chatBubbleRow}>
            <div className={styles.chatAvatar}>✦</div>
            <div className={`${styles.chatBubble} ${styles.chatBubbleAssistant} ${styles.chatBubbleThinking}`}>
              <span className={styles.chatDot} />
              <span className={styles.chatDot} />
              <span className={styles.chatDot} />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <form className={styles.chatInputRow} onSubmit={handleSend}>
        <textarea
          className={styles.chatInput}
          placeholder="Ask about your past entries…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={loading}
        />
        <button
          type="submit"
          className={styles.chatSendBtn}
          disabled={!input.trim() || loading}
          aria-label="Send"
        >
          ↑
        </button>
      </form>
    </div>
  )
}

function formatDate(raw) {
  if (!raw) return 'entry'
  try {
    const d = new Date(raw)
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  } catch {
    return 'entry'
  }
}
