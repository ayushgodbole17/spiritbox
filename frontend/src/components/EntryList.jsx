import { useState, useEffect, useRef } from 'react'
import styles from '../styles/components.module.css'
import { deleteEntry, updateEntry } from '../api/client.js'

// ─── date helpers ────────────────────────────────────────────────────────────

function getDateObj(entry) {
  const raw = entry.entry_date || entry.created_at || entry.timestamp || entry.date
  if (!raw) return null
  try { return new Date(raw) } catch { return null }
}

function formatEntryDate(date) {
  if (!date) return { day: '', date: '', time: '' }
  const day  = date.toLocaleDateString('en-US', { weekday: 'short' })         // Mon
  const d    = date.toLocaleDateString('en-US', { day: 'numeric', month: 'short' }) // 25 Mar
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }) // 3:42 pm
  return { day, date: d, time }
}

function monthKey(date) {
  if (!date) return 'Unknown'
  return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) // March 2026
}

function getPreview(entry) {
  const text = entry.summary || entry.raw_text || entry.text || ''
  return text.slice(0, 90) + (text.length > 90 ? '…' : '')
}

function entryId(entry, i) {
  return entry.entry_id || entry.id || entry._id || String(i)
}

// ─── skeleton ────────────────────────────────────────────────────────────────

function SkeletonList() {
  return (
    <div className={styles.entryListLoading}>
      {[80, 60, 90, 50, 70].map((w, i) => (
        <div key={i} className={styles.skeletonLine} style={{ width: `${w}%` }} />
      ))}
    </div>
  )
}

// ─── 3-dot menu ──────────────────────────────────────────────────────────────

function EntryMenu({ onEdit, onDelete, deleting }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  return (
    <div className={styles.entryMenuWrapper} ref={ref}>
      <button
        className={styles.dotsBtn}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v) }}
        aria-label="Entry options"
        title="Options"
      >
        ⋮
      </button>
      {open && (
        <div className={styles.dotsDropdown}>
          <button
            className={styles.dotsOption}
            onClick={(e) => { e.stopPropagation(); setOpen(false); onEdit() }}
          >
            Edit
          </button>
          <button
            className={`${styles.dotsOption} ${styles.dotsOptionDanger}`}
            onClick={(e) => { e.stopPropagation(); setOpen(false); onDelete() }}
            disabled={deleting}
          >
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  )
}

// ─── inline edit ─────────────────────────────────────────────────────────────

function EditPane({ entry, onSave, onCancel }) {
  const [text, setText] = useState(entry.raw_text || '')
  const [saving, setSaving] = useState(false)

  async function handleSave(e) {
    e.stopPropagation()
    setSaving(true)
    try {
      await onSave(text)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.editPane} onClick={(e) => e.stopPropagation()}>
      <textarea
        className={styles.editTextarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        autoFocus
      />
      <div className={styles.editActions}>
        <button className={`${styles.btn} ${styles.btnPrimary} ${styles.btnSm}`} onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button className={`${styles.btn} ${styles.btnGhost} ${styles.btnSm}`} onClick={(e) => { e.stopPropagation(); onCancel() }}>
          Cancel
        </button>
      </div>
    </div>
  )
}

// ─── main component ──────────────────────────────────────────────────────────

export default function EntryList({ selectedId, onSelect, refreshToken }) {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [editingId, setEditingId] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    import('../api/client.js').then(({ getEntries }) => getEntries(50))
      .then((data) => {
        if (!cancelled) {
          const list = Array.isArray(data) ? data : (data.entries || data.results || [])
          setEntries(list)
          setLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) { setError(err.message); setLoading(false) }
      })
    return () => { cancelled = true }
  }, [refreshToken])

  async function handleDelete(id) {
    if (deletingId) return
    setDeletingId(id)
    try {
      await deleteEntry(id)
      setEntries((prev) => prev.filter((en) => entryId(en) !== id))
      if (selectedId === id) onSelect(null, null)
    } catch (err) {
      console.error('Delete failed:', err)
    } finally {
      setDeletingId(null)
    }
  }

  async function handleSave(id, text) {
    await updateEntry(id, text)
    setEntries((prev) => prev.map((en) => entryId(en) === id ? { ...en, raw_text: text } : en))
    setEditingId(null)
  }

  // Group entries by month
  const groups = []
  let currentMonth = null
  for (const entry of entries) {
    const date = getDateObj(entry)
    const mk = monthKey(date)
    if (mk !== currentMonth) {
      currentMonth = mk
      groups.push({ type: 'separator', label: mk })
    }
    groups.push({ type: 'entry', entry })
  }

  return (
    <div>
      <div className={styles.entryListHeader}>
        <span className={styles.entryListTitle}>Past Entries</span>
        {!loading && !error && (
          <span className={styles.entryListCount}>{entries.length}</span>
        )}
      </div>

      {loading && <SkeletonList />}

      {!loading && error && (
        <div className={styles.entryListEmpty}>Could not load entries.</div>
      )}

      {!loading && !error && entries.length === 0 && (
        <div className={styles.entryListEmpty}>No entries yet. Submit your first one!</div>
      )}

      {!loading && !error && entries.length > 0 && (
        <div className={styles.entryListItems}>
          {groups.map((item, i) => {
            if (item.type === 'separator') {
              return (
                <div key={`sep-${item.label}`} className={styles.monthSeparator}>
                  {item.label}
                </div>
              )
            }

            const entry = item.entry
            const id = entryId(entry)
            const isActive = id === selectedId
            const isEditing = editingId === id
            const date = getDateObj(entry)
            const { day, date: d, time } = formatEntryDate(date)

            return (
              <div
                key={id}
                className={`${styles.entryListItem} ${isActive ? styles.entryListItemActive : ''}`}
                onClick={() => !isEditing && onSelect(entry, id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && !isEditing && onSelect(entry, id)}
              >
                <div className={styles.entryItemTop}>
                  <div className={styles.entryItemDateBlock}>
                    <span className={styles.entryItemDay}>{day}</span>
                    <span className={styles.entryItemDate}>{d}</span>
                    <span className={styles.entryItemTime}>{time}</span>
                  </div>
                  <EntryMenu
                    onEdit={() => setEditingId(id)}
                    onDelete={() => handleDelete(id)}
                    deleting={deletingId === id}
                  />
                </div>

                {isEditing ? (
                  <EditPane
                    entry={entry}
                    onSave={(text) => handleSave(id, text)}
                    onCancel={() => setEditingId(null)}
                  />
                ) : (
                  <div className={styles.entryItemPreview}>{getPreview(entry)}</div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
