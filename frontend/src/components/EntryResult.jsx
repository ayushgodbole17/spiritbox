import { useState } from 'react'
import styles from '../styles/components.module.css'

const CATEGORY_META = {
  health:          { color: '#ef4444', icon: '♥' },
  work:            { color: '#3b82f6', icon: '⚡' },
  music:           { color: '#a855f7', icon: '♪' },
  relationships:   { color: '#ec4899', icon: '✦' },
  mental_health:   { color: '#f97316', icon: '◎' },
  finances:        { color: '#eab308', icon: '◈' },
  personal_growth: { color: '#10b981', icon: '↑' },
  family:          { color: '#06b6d4', icon: '⌂' },
  fitness:         { color: '#84cc16', icon: '◉' },
  food:            { color: '#f59e0b', icon: '◆' },
  travel:          { color: '#14b8a6', icon: '→' },
  learning:        { color: '#8b5cf6', icon: '◇' },
  hobbies:         { color: '#f43f5e', icon: '★' },
  other:           { color: '#6b7280', icon: '·' },
}

function hex2rgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}

function CategoryPill({ category }) {
  const meta = CATEGORY_META[category] || CATEGORY_META.other
  const label = category.replace(/_/g, '\u00a0') // non-breaking space
  return (
    <span
      className={styles.categoryPill}
      style={{
        background: hex2rgba(meta.color, 0.14),
        color: meta.color,
        border: `1px solid ${hex2rgba(meta.color, 0.28)}`,
      }}
    >
      <span className={styles.categoryPillIcon}>{meta.icon}</span>
      {label}
    </span>
  )
}

function normalizeCategoryRows(categories) {
  if (!categories || !Array.isArray(categories) || categories.length === 0) return []
  if (typeof categories[0] === 'string') {
    // flat array — show as a single pills row with no sentence text
    return [{ text: '', labels: categories }]
  }
  return categories.map((c) => ({
    text: c.sentence || c.text || '',
    labels: c.labels || c.categories || (c.label ? [c.label] : ['other']),
  }))
}

function formatEventTime(e) {
  if (typeof e === 'string') return e
  return e.description || e.event || e.name || JSON.stringify(e)
}

export default function EntryResult({ result }) {
  const [showFull, setShowFull] = useState(false)
  if (!result) return null

  const { summary, categories, entities, raw_text } = result

  const categoryRows = normalizeCategoryRows(categories)

  // Collect unique top-level categories for the header strip
  const uniqueCategories = [...new Set(categoryRows.flatMap((r) => r.labels || []))]

  const events  = entities?.events        || []
  const people  = entities?.people        || []
  const amounts = entities?.amounts       || []
  const dates   = entities?.dates         || []

  return (
    <div className={styles.resultCard}>

      {/* ── Summary ─────────────────────────────────────────────────────── */}
      {summary && (
        <div className={styles.summarySection}>
          <p className={styles.summaryText}>{summary}</p>
          {uniqueCategories.length > 0 && (
            <div className={styles.summaryPills}>
              {uniqueCategories.map((cat) => (
                <CategoryPill key={cat} category={cat} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Sentence breakdown ──────────────────────────────────────────── */}
      {categoryRows.length > 0 && categoryRows.some((r) => r.text) && (
        <div className={styles.breakdownSection}>
          <div className={styles.sectionLabel}>Breakdown</div>
          <div className={styles.breakdownRows}>
            {categoryRows.filter((r) => r.text).map((row, i) => (
              <div key={i} className={styles.breakdownRow}>
                <span className={styles.breakdownText}>{row.text}</span>
                <div className={styles.breakdownPills}>
                  {(row.labels || ['other']).map((lbl) => (
                    <CategoryPill key={lbl} category={lbl} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Entities ────────────────────────────────────────────────────── */}
      {(events.length > 0 || people.length > 0 || amounts.length > 0 || dates.length > 0) && (
        <div className={styles.entitiesSection}>
          <div className={styles.sectionLabel}>Extracted</div>
          <div className={styles.entityChips}>
            {people.map((p, i) => (
              <span key={`p${i}`} className={styles.entityChip} data-type="person">
                <span className={styles.entityChipIcon}>👤</span>
                {typeof p === 'string' ? p : (p.name || JSON.stringify(p))}
              </span>
            ))}
            {events.map((e, i) => (
              <span key={`e${i}`} className={styles.entityChip} data-type="event">
                <span className={styles.entityChipIcon}>📅</span>
                {formatEventTime(e)}
              </span>
            ))}
            {amounts.map((a, i) => (
              <span key={`a${i}`} className={styles.entityChip} data-type="amount">
                <span className={styles.entityChipIcon}>💰</span>
                {typeof a === 'string' ? a : (a.description ? `${a.description} — ${a.amount}` : JSON.stringify(a))}
              </span>
            ))}
            {dates.map((d, i) => (
              <span key={`d${i}`} className={styles.entityChip} data-type="date">
                <span className={styles.entityChipIcon}>🗓</span>
                {typeof d === 'string' ? d : JSON.stringify(d)}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── View full entry ──────────────────────────────────────────────── */}
      {raw_text && (
        <div className={styles.fullEntrySection}>
          <button
            className={styles.fullEntryToggle}
            onClick={() => setShowFull(v => !v)}
          >
            <span>{showFull ? '▴ Hide entry' : '▾ View full entry'}</span>
          </button>
          {showFull && (
            <p className={styles.fullEntryText}>{raw_text}</p>
          )}
        </div>
      )}

    </div>
  )
}
