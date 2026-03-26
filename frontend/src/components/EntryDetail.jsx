import EntryResult from './EntryResult.jsx'
import styles from '../styles/components.module.css'

function formatDate(iso) {
  if (!iso) return ''
  try {
    return new Intl.DateTimeFormat('en-US', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

/**
 * Weaviate stores categories as a flat string array and sentence-level data
 * in sentence_tags (JSON string). EntryResult expects [{sentence, categories}].
 * Normalize before passing through.
 */
function normalizeEntry(entry) {
  // If sentence_tags is already a proper array (PostgreSQL), use it directly
  if (Array.isArray(entry.sentence_tags) && entry.sentence_tags.length > 0) {
    return { ...entry, categories: entry.sentence_tags }
  }

  let categories = entry.categories

  // If categories is a flat array of strings, try to parse sentence_tags JSON (Weaviate legacy)
  if (Array.isArray(categories) && categories.length > 0 && typeof categories[0] === 'string') {
    try {
      const parsed = JSON.parse(entry.sentence_tags || '[]')
      if (Array.isArray(parsed) && parsed.length > 0) {
        categories = parsed
      }
    } catch {
      categories = categories.map((cat) => ({ sentence: '', categories: [cat] }))
    }
  }

  return { ...entry, categories }
}

export default function EntryDetail({ entry, onClose }) {
  if (!entry) return null

  const date = entry.entry_date || entry.created_at || entry.timestamp || entry.date
  const normalized = normalizeEntry(entry)

  return (
    <div className={styles.entryDetail}>
      <div className={styles.entryDetailHeader}>
        <div className={styles.entryDetailMeta}>
          <span className={styles.entryDetailDate}>{formatDate(date)}</span>
          <span className={styles.entryDetailLabel}>Past Entry</span>
        </div>
        <button className={styles.closeBtn} onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>
      <EntryResult result={normalized} />
    </div>
  )
}
