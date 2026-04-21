import { useState, useRef, useEffect } from 'react'
import styles from '../styles/components.module.css'

function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0')
  const s = (seconds % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

export default function AudioRecorder({ onResult, onError }) {
  const [state, setState] = useState('idle') // idle | recording | processing
  const [elapsed, setElapsed] = useState(0)
  const [jobStatus, setJobStatus] = useState(null) // queued | running | completed | failed

  const mediaRecorderRef = useRef(null)
  const chunksRef = useRef([])
  const timerRef = useRef(null)
  const streamRef = useRef(null)

  // Clean up on unmount
  useEffect(() => {
    return () => {
      clearInterval(timerRef.current)
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop())
      }
    }
  }, [])

  async function startRecording() {
    onError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      // Prefer opus codec for quality + size
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm'

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        clearInterval(timerRef.current)
        const blob = new Blob(chunksRef.current, { type: mimeType })

        // Stop the mic track
        stream.getTracks().forEach((t) => t.stop())
        streamRef.current = null

        setState('processing')
        setJobStatus('queued')
        try {
          const { ingestAudio } = await import('../api/client.js')
          const result = await ingestAudio(blob, (status) => setJobStatus(status))
          onResult(result)
        } catch (err) {
          onError(err.message || 'Failed to process audio.')
        } finally {
          setState('idle')
          setElapsed(0)
          setJobStatus(null)
        }
      }

      recorder.start(250) // collect chunks every 250ms
      setState('recording')
      setElapsed(0)

      timerRef.current = setInterval(() => {
        setElapsed((s) => s + 1)
      }, 1000)
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        onError('Microphone access denied. Please allow microphone in your browser.')
      } else {
        onError(err.message || 'Could not start recording.')
      }
    }
  }

  function stopRecording() {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
  }

  function handleClick() {
    if (state === 'idle') startRecording()
    else if (state === 'recording') stopRecording()
  }

  const isRecording = state === 'recording'
  const isProcessing = state === 'processing'

  return (
    <div className={styles.audioRecorder}>
      <div className={styles.recordButtonWrapper}>
        {isRecording && <span className={styles.pulseRing} />}
        <button
          className={`${styles.recordButton} ${isRecording ? styles.recordButtonRecording : ''}`}
          onClick={handleClick}
          disabled={isProcessing}
          aria-label={isRecording ? 'Stop recording' : 'Start recording'}
          title={isRecording ? 'Click to stop' : 'Click to record'}
        >
          <span className={`${styles.recordDot} ${isRecording ? styles.recordDotActive : ''}`} />
        </button>
      </div>

      <div className={styles.recordInfo}>
        {isRecording && (
          <>
            <div className={styles.recordTimer}>{formatTime(elapsed)}</div>
            <div className={styles.recordingIndicator}>
              <span className={styles.recordingDot} />
              Recording — click to stop
            </div>
          </>
        )}
        {isProcessing && (
          <div className={styles.recordLabel}>
            <span className={styles.spinner} style={{ display: 'inline-block', marginRight: 8 }} />
            {jobStatus === 'running' ? 'Transcribing & analyzing…'
              : jobStatus === 'completed' ? 'Finishing up…'
              : 'Queued — waiting for worker…'}
          </div>
        )}
        {state === 'idle' && (
          <div className={styles.recordLabel}>Click to start recording</div>
        )}
      </div>

      <p className={styles.audioHint}>
        Audio is captured in WebM/Opus format and sent to the backend for transcription.
      </p>
    </div>
  )
}
