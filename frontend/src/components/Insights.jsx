import { useEffect, useState } from 'react'
import { getWeeklyDigest, triggerWeeklyRollup } from '../api/client.js'
import styles from '../styles/components.module.css'

function MoodBar({ mood }) {
  if (!mood || mood.score === null || mood.score === undefined) {
    return <p className={styles.insightsSubtle}>Not enough tagged entries this week.</p>
  }
  const pct = Math.round(((mood.score + 1) / 2) * 100)
  const label = mood.score > 0.2 ? 'uplifted' : mood.score < -0.2 ? 'heavy' : 'mixed'
  return (
    <div>
      <div className={styles.insightsMoodBar}>
        <div
          className={styles.insightsMoodBarFill}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className={styles.insightsSubtle}>
        {label} · {mood.positive} positive / {mood.negative} heavy tags
      </p>
    </div>
  )
}

function ThemeCard({ theme }) {
  return (
    <div className={styles.insightsTheme}>
      <div className={styles.insightsThemeHeader}>
        <span className={styles.insightsThemeLabel}>{theme.label}</span>
        <span className={styles.insightsThemeCount}>{theme.entry_count || theme.entry_ids?.length || 0} entries</span>
      </div>
      {theme.summary && <p className={styles.insightsThemeBody}>{theme.summary}</p>}
    </div>
  )
}

export default function Insights() {
  const [digest, setDigest] = useState(null)
  const [loading, setLoading] = useState(true)
  const [rolling, setRolling] = useState(false)
  const [error, setError] = useState(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getWeeklyDigest()
      setDigest(data)
    } catch (e) {
      setError(e.message || 'Failed to load digest')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const runRollup = async () => {
    setRolling(true)
    setError(null)
    try {
      await triggerWeeklyRollup()
      await load()
    } catch (e) {
      setError(e.message || 'Rollup failed')
    } finally {
      setRolling(false)
    }
  }

  if (loading) {
    return <div className={styles.insightsRoot}><p className={styles.insightsSubtle}>Loading your week…</p></div>
  }

  if (error) {
    return (
      <div className={styles.insightsRoot}>
        <p className={styles.errorBanner}>{error}</p>
        <button className={styles.insightsButton} onClick={load}>Retry</button>
      </div>
    )
  }

  if (!digest) return null

  const themes = digest.rollup?.themes || []
  const weekStart = digest.week_start ? new Date(digest.week_start).toLocaleDateString() : ''

  return (
    <div className={styles.insightsRoot}>
      <header className={styles.insightsHeader}>
        <div>
          <h2 className={styles.insightsTitle}>Your Week</h2>
          <p className={styles.insightsSubtle}>
            {digest.entry_count} entries since {weekStart}
          </p>
        </div>
        <button
          className={styles.insightsButton}
          onClick={runRollup}
          disabled={rolling}
        >
          {rolling ? 'Rolling up…' : 'Refresh themes'}
        </button>
      </header>

      <section className={styles.insightsSection}>
        <h3 className={styles.insightsSectionTitle}>Mood</h3>
        <MoodBar mood={digest.mood} />
      </section>

      <section className={styles.insightsSection}>
        <h3 className={styles.insightsSectionTitle}>Themes</h3>
        {themes.length === 0 && (
          <p className={styles.insightsSubtle}>
            No themes yet — click <em>Refresh themes</em> to cluster this week's entries.
          </p>
        )}
        {themes.map((t, i) => <ThemeCard key={i} theme={t} />)}
      </section>

      <section className={styles.insightsSection}>
        <h3 className={styles.insightsSectionTitle}>Habit streaks</h3>
        {digest.habits.length === 0 ? (
          <p className={styles.insightsSubtle}>No habits tracked yet.</p>
        ) : (
          <ul className={styles.insightsHabitList}>
            {digest.habits.map((h, i) => (
              <li key={i} className={styles.insightsHabitRow}>
                <span>{h.name}</span>
                <span className={styles.insightsHabitStreak}>{h.streak_days} day streak</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.insightsSection}>
        <h3 className={styles.insightsSectionTitle}>Longest entries</h3>
        {digest.top_entries.length === 0 ? (
          <p className={styles.insightsSubtle}>No entries this week.</p>
        ) : (
          <ul className={styles.insightsTopList}>
            {digest.top_entries.map((e) => (
              <li key={e.id} className={styles.insightsTopItem}>
                <p className={styles.insightsTopSummary}>{e.summary}</p>
                <span className={styles.insightsSubtle}>
                  {e.created_at ? new Date(e.created_at).toLocaleDateString() : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
