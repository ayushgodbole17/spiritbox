import { useState, useCallback } from 'react'
import TextEntry from './components/TextEntry.jsx'
import AudioRecorder from './components/AudioRecorder.jsx'
import EntryResult from './components/EntryResult.jsx'
import EntryList from './components/EntryList.jsx'
import EntryDetail from './components/EntryDetail.jsx'
import Chat from './components/Chat.jsx'
import styles from './styles/App.module.css'
import compStyles from './styles/components.module.css'

export default function App() {
  const [inputTab, setInputTab]     = useState('text')      // 'text' | 'audio'
  const [mobileTab, setMobileTab]   = useState('write')     // 'write' | 'history' | 'chat'
  const [result, setResult]         = useState(null)
  const [error, setError]           = useState(null)
  const [selectedEntry, setSelectedEntry] = useState(null)
  const [selectedId, setSelectedId]       = useState(null)
  const [refreshToken, setRefreshToken]   = useState(0)

  const handleResult = useCallback((data) => {
    setResult(data)
    setSelectedEntry(null)
    setSelectedId(null)
    setTimeout(() => setRefreshToken((t) => t + 1), 800)
  }, [])

  const handleSelectEntry = useCallback((entry, id) => {
    setSelectedEntry(entry)
    setSelectedId(id)
    setResult(null)
    setMobileTab('write') // switch to main view to show the detail
  }, [])

  const handleCloseDetail = useCallback(() => {
    setSelectedEntry(null)
    setSelectedId(null)
  }, [])

  return (
    <div className={styles.app}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className={styles.header}>
        <div className={styles.headerLogo}>
          <div className={styles.headerIcon}>✦</div>
          <span className={styles.headerTitle}>Spiritbox</span>
        </div>
        <span className={styles.headerSub}>journal intelligence</span>
      </header>

      {/* ── Sidebar (desktop) ───────────────────────────────────────────── */}
      <aside className={styles.sidebar}>
        <EntryList
          selectedId={selectedId}
          onSelect={handleSelectEntry}
          refreshToken={refreshToken}
        />
      </aside>

      {/* ── Main ────────────────────────────────────────────────────────── */}
      <main className={styles.main}>

        {/* Mobile tab: write pane */}
        <div className={`${styles.mobilePane} ${mobileTab === 'write' ? styles.mobilePaneVisible : ''}`}>

          {/* Input card */}
          <div className={styles.inputCard}>
            <div className={styles.inputCardHeader}>
              <div className={styles.tabBar}>
                <button
                  className={`${styles.tab} ${inputTab === 'text' ? styles.tabActive : ''}`}
                  onClick={() => setInputTab('text')}
                >
                  Text
                </button>
                <button
                  className={`${styles.tab} ${inputTab === 'audio' ? styles.tabActive : ''}`}
                  onClick={() => setInputTab('audio')}
                >
                  Audio
                </button>
              </div>
            </div>
            {inputTab === 'text'  && <TextEntry  onResult={handleResult} onError={setError} />}
            {inputTab === 'audio' && <AudioRecorder onResult={handleResult} onError={setError} />}
          </div>

          {/* Error */}
          {error && (
            <div className={compStyles.errorBanner}>
              <span className={compStyles.errorIcon}>⚠</span>
              <span>{error}</span>
              <button className={compStyles.errorDismiss} onClick={() => setError(null)}>×</button>
            </div>
          )}

          {/* Result */}
          {result && !selectedEntry && <EntryResult result={result} />}

          {/* Selected past entry */}
          {selectedEntry && (
            <EntryDetail entry={selectedEntry} onClose={handleCloseDetail} />
          )}

          {/* Empty state */}
          {!result && !selectedEntry && !error && (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>✦</div>
              <p className={styles.emptyTitle}>What's on your mind?</p>
              <p className={styles.emptyHint}>Type or record a journal entry above.</p>
            </div>
          )}
        </div>

        {/* Mobile tab: history pane */}
        <div className={`${styles.mobilePane} ${mobileTab === 'history' ? styles.mobilePaneVisible : ''}`}>
          <EntryList
            selectedId={selectedId}
            onSelect={handleSelectEntry}
            refreshToken={refreshToken}
          />
        </div>

        {/* Mobile tab: chat pane — also shown on desktop */}
        <div className={`${styles.mobilePane} ${styles.chatPane} ${mobileTab === 'chat' ? styles.mobilePaneVisible : ''}`}>
          <Chat />
        </div>

      </main>

      {/* ── Desktop Chat panel ──────────────────────────────────────────── */}
      <aside className={styles.chatPanel}>
        <Chat />
      </aside>

      {/* ── Mobile bottom nav ───────────────────────────────────────────── */}
      <nav className={styles.mobileNav}>
        <button
          className={`${styles.mobileNavBtn} ${mobileTab === 'write' ? styles.mobileNavBtnActive : ''}`}
          onClick={() => setMobileTab('write')}
        >
          <span className={styles.mobileNavIcon}>✎</span>
          <span className={styles.mobileNavLabel}>Write</span>
        </button>
        <button
          className={`${styles.mobileNavBtn} ${mobileTab === 'history' ? styles.mobileNavBtnActive : ''}`}
          onClick={() => setMobileTab('history')}
        >
          <span className={styles.mobileNavIcon}>☰</span>
          <span className={styles.mobileNavLabel}>History</span>
        </button>
        <button
          className={`${styles.mobileNavBtn} ${mobileTab === 'chat' ? styles.mobileNavBtnActive : ''}`}
          onClick={() => setMobileTab('chat')}
        >
          <span className={styles.mobileNavIcon}>◎</span>
          <span className={styles.mobileNavLabel}>Ask</span>
        </button>
      </nav>

    </div>
  )
}
