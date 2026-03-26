import { useState } from 'react'
import styles from '../styles/components.module.css'

export default function TextEntry({ onResult, onError }) {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    const trimmed = text.trim()
    if (!trimmed) return

    setLoading(true)
    onError(null)

    try {
      // Import lazily to avoid circular issues at module level
      const { ingestText } = await import('../api/client.js')
      const result = await ingestText(trimmed)
      onResult(result)
    } catch (err) {
      onError(err.message || 'Failed to process entry.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className={styles.textEntryForm} onSubmit={handleSubmit}>
      <textarea
        className={styles.textarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="What's on your mind today?"
        rows={4}
        disabled={loading}
      />
      <div className={styles.textEntryFooter}>
        <span className={styles.charCount}>
          {text.length > 0 ? `${text.length} chars` : ''}
        </span>
        <button
          type="submit"
          className={`${styles.btn} ${styles.btnPrimary}`}
          disabled={loading || text.trim().length === 0}
        >
          {loading && <span className={styles.spinner} />}
          {loading ? 'Processing…' : 'Process Entry'}
        </button>
      </div>
    </form>
  )
}
