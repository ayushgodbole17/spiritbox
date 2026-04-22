const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080'

function authHeaders(extra = {}) {
  const token = localStorage.getItem('sb_token')
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

/**
 * POST /ingest/text
 * @param {string} text
 * @param {string} userId
 */
export async function ingestText(text, userId = 'default') {
  const res = await fetch(`${BASE}/ingest/text`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ text }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * POST /ingest/audio — server returns 202 + job_id; we poll until done,
 * then fetch the completed entry so the caller gets a full entry object back.
 * @param {Blob} audioBlob
 * @param {(status: string) => void} [onProgress] — optional status callback
 */
export async function ingestAudio(audioBlob, onProgress) {
  const form = new FormData()
  form.append('file', audioBlob, 'recording.webm')

  const submit = await fetch(`${BASE}/ingest/audio`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  })
  if (!submit.ok) {
    const err = await submit.text()
    throw new Error(err || `HTTP ${submit.status}`)
  }
  const { job_id } = await submit.json()
  if (!job_id) throw new Error('Server did not return a job_id')

  // Poll every 2s for up to 5 minutes.
  const deadline = Date.now() + 5 * 60 * 1000
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 2000))
    const poll = await fetch(`${BASE}/ingest/jobs/${job_id}`, { headers: authHeaders() })
    if (!poll.ok) {
      const err = await poll.text()
      throw new Error(err || `HTTP ${poll.status}`)
    }
    const job = await poll.json()
    if (onProgress) onProgress(job.status)

    if (job.status === 'completed') {
      if (job.result) return job.result
      // Fallback: older servers may not embed result — fetch the entry.
      if (!job.entry_id) throw new Error('Job completed without entry_id')
      const entryRes = await fetch(`${BASE}/entries/${job.entry_id}`, { headers: authHeaders() })
      if (!entryRes.ok) {
        const err = await entryRes.text()
        throw new Error(err || `HTTP ${entryRes.status}`)
      }
      return entryRes.json()
    }
    if (job.status === 'failed') {
      throw new Error(job.error || 'Transcription/pipeline failed')
    }
  }
  throw new Error('Timed out waiting for transcription (5 min).')
}

/**
 * GET /entries
 * @param {number} limit
 */
export async function getEntries(limit = 20) {
  const res = await fetch(`${BASE}/entries?limit=${limit}`, { headers: authHeaders() })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * PATCH /entries/:id
 * @param {string} entryId
 * @param {string} rawText
 */
export async function updateEntry(entryId, rawText) {
  const res = await fetch(`${BASE}/entries/${entryId}`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ raw_text: rawText }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * DELETE /entries/:id
 * @param {string} entryId
 */
export async function deleteEntry(entryId) {
  const res = await fetch(`${BASE}/entries/${entryId}`, { method: 'DELETE', headers: authHeaders() })
  if (!res.ok && res.status !== 204) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
}

/**
 * POST /chat
 * @param {string} message
 * @param {Array<{role: string, content: string}>} history
 * @param {number} topK
 */
export async function sendChat(message, history = [], topK = 5) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ message, history, top_k: topK }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * POST /chat/stream — SSE streaming variant of sendChat.
 * Calls onToken(string) for each token, returns final { sources } on completion.
 * @param {string} message
 * @param {Array<{role: string, content: string}>} history
 * @param {(token: string) => void} onToken
 * @param {number} topK
 * @returns {Promise<{sources: Array}>}
 */
export async function sendChatStream(message, history = [], onToken, topK = 5) {
  const res = await fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ message, history, top_k: topK }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sources = []

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Parse SSE lines
    const lines = buffer.split('\n')
    buffer = lines.pop() // keep incomplete line in buffer
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const evt = JSON.parse(line.slice(6))
        if (evt.done) {
          sources = evt.sources || []
        } else if (evt.token) {
          onToken(evt.token)
        }
      } catch { /* ignore malformed lines */ }
    }
  }
  return { sources }
}

/**
 * GET /api/digest/weekly — assembles the weekly insights digest.
 */
export async function getWeeklyDigest() {
  const res = await fetch(`${BASE}/api/digest/weekly`, { headers: authHeaders() })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * POST /api/digest/weekly/run — fire the rollup for the current user.
 */
export async function triggerWeeklyRollup() {
  const res = await fetch(`${BASE}/api/digest/weekly/run`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * GET /reminders
 */
export async function getReminders() {
  const res = await fetch(`${BASE}/reminders`)
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}
