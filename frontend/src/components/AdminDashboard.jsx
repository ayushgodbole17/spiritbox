import { useState, useEffect, useCallback } from 'react'
import adm from '../styles/admin.module.css'

const BASE = import.meta.env.VITE_API_URL || ''

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------

function makeAuthHeader(username, password) {
  return 'Basic ' + btoa(`${username}:${password}`)
}

async function apiFetch(path, auth, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      Authorization: auth,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  if (res.status === 401) throw new Error('401')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Login screen
// ---------------------------------------------------------------------------

function LoginScreen({ onLogin, error }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    onLogin(username, password)
  }

  return (
    <div className={adm.loginWrap}>
      <form className={adm.loginCard} onSubmit={handleSubmit}>
        <div className={adm.loginLogo}>
          <span className={adm.loginIcon}>✦</span>
          <span className={adm.loginTitle}>Spiritbox Admin</span>
        </div>
        <input
          className={adm.loginInput}
          type="text"
          placeholder="Username"
          value={username}
          onChange={e => setUsername(e.target.value)}
          autoFocus
        />
        <input
          className={adm.loginInput}
          type="password"
          placeholder="Password"
          value={password}
          onChange={e => setPassword(e.target.value)}
        />
        {error && <p className={adm.loginError}>{error}</p>}
        <button className={adm.loginBtn} type="submit">Sign in</button>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Metric card
// ---------------------------------------------------------------------------

function MetricCard({ label, value, sub, pass }) {
  return (
    <div className={adm.metricCard}>
      <div className={adm.metricLabel}>{label}</div>
      <div className={`${adm.metricValue} ${pass === true ? adm.pass : pass === false ? adm.fail : ''}`}>
        {value ?? '—'}
      </div>
      {sub && <div className={adm.metricSub}>{sub}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Analytics panel
// ---------------------------------------------------------------------------

const CATEGORY_COLORS = {
  fitness:      '#10b981',
  nutrition:    '#f59e0b',
  sleep:        '#6366f1',
  mental_health:'#ec4899',
  hydration:    '#06b6d4',
  supplements:  '#8b5cf6',
  recovery:     '#f97316',
  stress:       '#ef4444',
  productivity: '#3b82f6',
  default:      '#7c3aed',
}

function AnalyticsPanel({ auth }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    apiFetch('/api/admin/analytics', auth)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [auth])

  if (loading) return <div className={adm.panelLoading}>Loading analytics…</div>
  if (error)   return <div className={adm.panelError}>Error: {error}</div>
  if (data?.error) return <div className={adm.panelError}>DB error: {data.error}</div>

  const ov  = data?.overview || {}
  const vol = data?.volume_by_day || []
  const cats = data?.category_distribution || []
  const tiers = data?.model_tier_distribution || {}
  const ev = data?.recent_eval

  // Volume bar chart
  const maxVol = vol.length ? Math.max(...vol.map(d => d.count), 1) : 1
  const barMaxPx = 68 // max height in px (inside 88px container with 20px bottom padding)

  // Model tier bars
  const tierTotal = Object.values(tiers).reduce((a, b) => a + b, 0) || 1

  return (
    <div className={adm.panel}>
      <h2 className={adm.panelTitle}>Analytics</h2>

      {/* Overview metrics */}
      <div className={adm.metricRow}>
        <MetricCard label="Total Entries"  value={ov.total_entries ?? 0} />
        <MetricCard label="Today"          value={ov.entries_today ?? 0} />
        <MetricCard label="This Week"      value={ov.entries_this_week ?? 0} />
        <MetricCard label="Cache Hit %"    value={`${Math.round((ov.cache_hit_rate ?? 0) * 100)}%`} />
        <MetricCard label="Tier 1 Calls"   value={ov.tier1_calls ?? 0} sub="gpt-4o-mini" />
        <MetricCard label="Tier 2 Calls"   value={ov.tier2_calls ?? 0} sub="gpt-4o" />
      </div>

      <div className={adm.analyticsGrid}>
        {/* Volume by day */}
        <div className={adm.chartSection} style={{ gridColumn: '1 / -1' }}>
          <div className={adm.chartLabel}>Entry Volume — Last 30 Days</div>
          <div className={adm.barChart}>
            {vol.map((d, i) => {
              const h = Math.max(2, Math.round((d.count / maxVol) * barMaxPx))
              const showLabel = i % 7 === 0
              return (
                <div
                  key={d.date}
                  className={adm.bar}
                  style={{ height: `${h}px` }}
                  title={`${d.date}: ${d.count}`}
                >
                  {showLabel && (
                    <span className={adm.barLabel}>
                      {d.date.slice(5)} {/* MM-DD */}
                    </span>
                  )}
                </div>
              )
            })}
            {vol.length === 0 && (
              <span style={{ fontSize: 12, color: 'var(--text-3)', alignSelf: 'center' }}>No data yet</span>
            )}
          </div>
        </div>

        {/* Category distribution */}
        <div className={adm.chartSection}>
          <div className={adm.chartLabel}>Category Distribution (top 10)</div>
          <div className={adm.hBarChart}>
            {cats.map(c => (
              <div key={c.category} className={adm.hBarRow}>
                <div className={adm.hBarLabel}>{c.category}</div>
                <div
                  className={adm.hBar}
                  style={{
                    width: `${Math.max(c.pct, 1)}%`,
                    background: CATEGORY_COLORS[c.category] || CATEGORY_COLORS.default,
                    maxWidth: 'calc(100% - 130px)',
                  }}
                />
                <span className={adm.hBarCount}>{c.count} ({c.pct}%)</span>
              </div>
            ))}
            {cats.length === 0 && (
              <span style={{ fontSize: 12, color: 'var(--text-3)' }}>No data yet</span>
            )}
          </div>
        </div>

        {/* Model tier + eval snapshot stacked */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Model tier usage */}
          <div className={adm.chartSection}>
            <div className={adm.chartLabel}>Model Tier Usage</div>
            <div className={adm.hBarChart}>
              {Object.entries(tiers).map(([model, count]) => (
                <div key={model} className={adm.hBarRow}>
                  <div className={adm.hBarLabel}>{model}</div>
                  <div
                    className={adm.hBar}
                    style={{
                      width: `${Math.max(Math.round(count / tierTotal * 100), 1)}%`,
                      maxWidth: 'calc(100% - 130px)',
                    }}
                  />
                  <span className={adm.hBarCount}>{count}</span>
                </div>
              ))}
              {Object.keys(tiers).length === 0 && (
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>No data yet</span>
              )}
            </div>
          </div>

          {/* Latest eval snapshot */}
          <div className={adm.chartSection}>
            <div className={adm.chartLabel}>Latest Eval Snapshot</div>
            {ev ? (
              <div className={adm.evalSnapshot}>
                <div className={adm.evalSnapshotRow}>
                  <span>Classifier Precision</span>
                  <span className={adm.evalSnapshotVal}>{ev.classifier_precision?.toFixed(4) ?? '—'}</span>
                </div>
                <div className={adm.evalSnapshotRow}>
                  <span>Entity F1</span>
                  <span className={adm.evalSnapshotVal}>{ev.entity_f1?.toFixed(4) ?? '—'}</span>
                </div>
                <div className={adm.evalSnapshotRow}>
                  <span>Result</span>
                  <span className={`${adm.evalSnapshotVal} ${ev.passed ? adm.pass : adm.fail}`}>
                    {ev.passed ? 'PASS' : 'FAIL'}
                  </span>
                </div>
                <div className={adm.evalSnapshotRow}>
                  <span>Run at</span>
                  <span style={{ fontSize: 11, color: 'var(--text-3)' }}>
                    {ev.run_at ? new Date(ev.run_at).toLocaleString() : '—'}
                  </span>
                </div>
              </div>
            ) : (
              <p className={adm.emptyNote}>No evals run yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Evals panel
// ---------------------------------------------------------------------------

function EvalsPanel({ auth }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await apiFetch('/api/admin/evals', auth)
      setData(d)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [auth])

  useEffect(() => { load() }, [load])

  async function triggerRun() {
    setRunning(true)
    try {
      await apiFetch('/api/admin/evals/run', auth, { method: 'POST' })
      // Poll every 5s until results update
      const interval = setInterval(async () => {
        const d = await apiFetch('/api/admin/evals', auth)
        if (d.classifier_precision !== undefined) {
          setData(d)
          clearInterval(interval)
          setRunning(false)
        }
      }, 5000)
    } catch (e) {
      setError(e.message)
      setRunning(false)
    }
  }

  if (loading) return <div className={adm.panelLoading}>Loading evals…</div>
  if (error)   return <div className={adm.panelError}>Error: {error}</div>

  if (data?.status === 'not_run') {
    return (
      <div className={adm.panel}>
        <div className={adm.panelHeader}>
          <h2 className={adm.panelTitle}>Evals</h2>
          <button className={adm.runBtn} onClick={triggerRun} disabled={running}>
            {running ? 'Running…' : 'Run now'}
          </button>
        </div>
        <p className={adm.emptyNote}>No eval results yet. Click "Run now" to evaluate against the golden dataset.</p>
      </div>
    )
  }

  const passed = data?.passed || {}
  const thresholds = data?.thresholds || {}
  const perEntry = data?.per_entry || []

  return (
    <div className={adm.panel}>
      <div className={adm.panelHeader}>
        <h2 className={adm.panelTitle}>Evals</h2>
        <button className={adm.runBtn} onClick={triggerRun} disabled={running}>
          {running ? 'Running…' : 'Run now'}
        </button>
      </div>

      <div className={adm.metricRow}>
        <MetricCard
          label="Classifier Precision"
          value={data?.classifier_precision?.toFixed(4)}
          sub={`threshold ≥ ${thresholds.classifier_precision}`}
          pass={passed.classifier_precision}
        />
        <MetricCard
          label="Entity F1"
          value={data?.entity_f1?.toFixed(4)}
          sub={`threshold ≥ ${thresholds.entity_f1}`}
          pass={passed.entity_f1}
        />
        <MetricCard
          label="Entries Evaluated"
          value={perEntry.length}
        />
        <MetricCard
          label="Overall"
          value={Object.values(passed).every(Boolean) ? 'PASS' : 'FAIL'}
          pass={Object.values(passed).every(Boolean)}
        />
      </div>

      {perEntry.length > 0 && (
        <div className={adm.tableWrap}>
          <table className={adm.table}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Classifier Precision</th>
                <th>Entity F1</th>
                <th>Predicted Categories</th>
                <th>Expected Categories</th>
              </tr>
            </thead>
            <tbody>
              {perEntry.map(row => (
                <tr key={row.id}>
                  <td className={adm.mono}>{row.id}</td>
                  <td className={row.classifier_precision >= thresholds.classifier_precision ? adm.passCell : adm.failCell}>
                    {row.classifier_precision?.toFixed(3)}
                  </td>
                  <td className={row.entity_f1 >= thresholds.entity_f1 ? adm.passCell : adm.failCell}>
                    {row.entity_f1?.toFixed(3)}
                  </td>
                  <td>{(row.predicted_categories || []).join(', ')}</td>
                  <td>{(row.expected_categories || []).join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// LangFuse metrics panel
// ---------------------------------------------------------------------------

function MetricsPanel({ auth }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    apiFetch('/api/admin/metrics', auth)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [auth])

  if (loading) return <div className={adm.panelLoading}>Loading LangFuse metrics…</div>
  if (error)   return <div className={adm.panelError}>Error: {error}</div>
  if (data?.status === 'unavailable') return (
    <div className={adm.panel}>
      <h2 className={adm.panelTitle}>LangFuse Traces</h2>
      <p className={adm.emptyNote}>{data.message}</p>
    </div>
  )

  const { summary = {}, traces = [] } = data || {}

  return (
    <div className={adm.panel}>
      <div className={adm.panelHeader}>
        <h2 className={adm.panelTitle}>LangFuse Traces</h2>
        <a className={adm.externalLink} href={data?.langfuse_host} target="_blank" rel="noreferrer">
          Open LangFuse ↗
        </a>
      </div>

      <div className={adm.metricRow}>
        <MetricCard label="Total Traces" value={summary.total_traces} />
        <MetricCard label="Avg Latency" value={summary.avg_latency_ms != null ? `${summary.avg_latency_ms} ms` : '—'} />
        <MetricCard label="Errors" value={summary.error_count} sub={`${((summary.error_rate || 0) * 100).toFixed(1)}% error rate`} />
        {Object.entries(summary.model_usage || {}).map(([model, count]) => (
          <MetricCard key={model} label={model} value={`${count} calls`} />
        ))}
      </div>

      {traces.length > 0 && (
        <div className={adm.tableWrap}>
          <table className={adm.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Timestamp</th>
                <th>Latency</th>
                <th>Level</th>
                <th>Input preview</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((t, i) => (
                <tr key={t.id || i}>
                  <td className={adm.mono}>{t.name || '—'}</td>
                  <td className={adm.dimCell}>{t.timestamp ? new Date(t.timestamp).toLocaleString() : '—'}</td>
                  <td>{t.latency_ms != null ? `${t.latency_ms} ms` : '—'}</td>
                  <td className={t.level?.toLowerCase() === 'error' ? adm.failCell : ''}>{t.level || '—'}</td>
                  <td className={adm.inputPreview}>{t.input || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// System status panel
// ---------------------------------------------------------------------------

function StatusPanel({ auth }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  useEffect(() => {
    apiFetch('/api/admin/status', auth)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [auth])

  if (loading) return <div className={adm.panelLoading}>Loading status…</div>
  if (error)   return <div className={adm.panelError}>Error: {error}</div>

  const cache = data?.cache || {}
  const lf    = data?.langfuse || {}

  return (
    <div className={adm.panel}>
      <h2 className={adm.panelTitle}>System Status</h2>
      <div className={adm.metricRow}>
        <MetricCard label="Cache Entries" value={cache.total ?? 0} sub="in-memory semantic cache" />
        {Object.entries(cache.by_namespace || {}).map(([ns, count]) => (
          <MetricCard key={ns} label={`Cache · ${ns}`} value={count} />
        ))}
        <MetricCard
          label="LangFuse"
          value={lf.configured ? 'Connected' : 'Not configured'}
          pass={lf.configured}
          sub={lf.host}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Releases panel
// ---------------------------------------------------------------------------

const TYPE_COLORS = { feature: '#7c3aed', bugfix: '#ef4444', improvement: '#3b82f6', breaking: '#f97316' }
const TYPE_LABELS = { feature: 'Feature', bugfix: 'Bug fix', improvement: 'Improvement', breaking: 'Breaking' }

function ReleasesPanel({ auth }) {
  const [releases, setReleases] = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm]         = useState({ version: '', date: new Date().toISOString().slice(0,10), type: 'feature', title: '', changes: '' })
  const [saving, setSaving]     = useState(false)

  useEffect(() => {
    apiFetch('/api/admin/releases', auth)
      .then(setReleases)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [auth])

  async function handleAdd(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const changes = form.changes
        .split('\n')
        .map(l => l.trim())
        .filter(Boolean)
        .map(l => ({ type: form.type, text: l }))
      const release = { version: form.version, date: form.date, type: form.type, title: form.title, changes }
      const saved = await apiFetch('/api/admin/releases', auth, { method: 'POST', body: JSON.stringify(release) })
      setReleases(prev => [saved, ...(prev || [])])
      setShowForm(false)
      setForm({ version: '', date: new Date().toISOString().slice(0,10), type: 'feature', title: '', changes: '' })
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className={adm.panelLoading}>Loading releases…</div>
  if (error)   return <div className={adm.panelError}>Error: {error}</div>

  return (
    <div className={adm.panel}>
      <div className={adm.panelHeader}>
        <h2 className={adm.panelTitle}>Release Notes</h2>
        <button className={adm.runBtn} onClick={() => setShowForm(v => !v)}>
          {showForm ? 'Cancel' : '+ New release'}
        </button>
      </div>

      {showForm && (
        <form className={adm.releaseForm} onSubmit={handleAdd}>
          <div className={adm.releaseFormRow}>
            <input className={adm.releaseInput} placeholder="Version (e.g. 0.5.0)" value={form.version} onChange={e => setForm(f => ({...f, version: e.target.value}))} required />
            <input className={adm.releaseInput} type="date" value={form.date} onChange={e => setForm(f => ({...f, date: e.target.value}))} required />
            <select className={adm.releaseInput} value={form.type} onChange={e => setForm(f => ({...f, type: e.target.value}))}>
              <option value="feature">Feature</option>
              <option value="bugfix">Bug fix</option>
              <option value="improvement">Improvement</option>
              <option value="breaking">Breaking</option>
            </select>
          </div>
          <input className={adm.releaseInput} placeholder="Release title" value={form.title} onChange={e => setForm(f => ({...f, title: e.target.value}))} required />
          <textarea className={adm.releaseTextarea} placeholder={"One change per line:\nAdded X\nFixed Y"} value={form.changes} onChange={e => setForm(f => ({...f, changes: e.target.value}))} rows={4} required />
          <button className={adm.runBtn} type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save release'}</button>
        </form>
      )}

      <div className={adm.releaseList}>
        {(releases || []).map((r, i) => (
          <div key={i} className={adm.releaseEntry}>
            <div className={adm.releaseHeader}>
              <span className={adm.releaseVersion}>v{r.version}</span>
              <span className={adm.releaseTitle}>{r.title}</span>
              <span className={adm.releaseDate}>{r.date}</span>
            </div>
            <ul className={adm.changeList}>
              {(r.changes || []).map((c, j) => {
                const type = typeof c === 'string' ? r.type : (c.type || r.type || 'feature')
                const text = typeof c === 'string' ? c : c.text
                return (
                  <li key={j} className={adm.changeItem}>
                    <span
                      className={adm.changeType}
                      style={{ background: `${TYPE_COLORS[type] || '#6b7280'}22`, color: TYPE_COLORS[type] || '#6b7280', borderColor: `${TYPE_COLORS[type] || '#6b7280'}44` }}
                    >
                      {TYPE_LABELS[type] || type}
                    </span>
                    <span className={adm.changeText}>{text}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
        {(!releases || releases.length === 0) && (
          <p className={adm.emptyNote}>No releases yet. Click "+ New release" to add one.</p>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------

export default function AdminDashboard() {
  const [auth, setAuth]           = useState(() => sessionStorage.getItem('sb_admin_auth') || null)
  const [loginError, setLoginError] = useState(null)
  const [activeTab, setActiveTab] = useState('analytics')

  async function handleLogin(username, password) {
    const header = makeAuthHeader(username, password)
    try {
      await apiFetch('/api/admin/status', header)
      sessionStorage.setItem('sb_admin_auth', header)
      setAuth(header)
      setLoginError(null)
    } catch (e) {
      if (e.message === '401') setLoginError('Invalid username or password.')
      else setLoginError(`Connection error: ${e.message}`)
    }
  }

  function handleLogout() {
    sessionStorage.removeItem('sb_admin_auth')
    setAuth(null)
  }

  if (!auth) {
    return <LoginScreen onLogin={handleLogin} error={loginError} />
  }

  return (
    <div className={adm.shell}>
      <header className={adm.header}>
        <div className={adm.headerLeft}>
          <span className={adm.headerIcon}>✦</span>
          <span className={adm.headerTitle}>Spiritbox</span>
          <span className={adm.headerBadge}>admin</span>
        </div>
        <nav className={adm.tabNav}>
          {[['analytics','Analytics'],['evals','Evals'],['metrics','LangFuse'],['status','System'],['releases','Releases']].map(([tab, label]) => (
            <button
              key={tab}
              className={`${adm.tabBtn} ${activeTab === tab ? adm.tabBtnActive : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {label}
            </button>
          ))}
        </nav>
        <button className={adm.logoutBtn} onClick={handleLogout}>Sign out</button>
      </header>

      <main className={adm.content}>
        {activeTab === 'analytics' && <AnalyticsPanel auth={auth} />}
        {activeTab === 'evals'     && <EvalsPanel     auth={auth} />}
        {activeTab === 'metrics'   && <MetricsPanel   auth={auth} />}
        {activeTab === 'status'    && <StatusPanel    auth={auth} />}
        {activeTab === 'releases'  && <ReleasesPanel  auth={auth} />}
      </main>
    </div>
  )
}
