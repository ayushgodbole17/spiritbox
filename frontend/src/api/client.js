const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8080'

/**
 * POST /ingest/text
 * @param {string} text
 * @param {string} userId
 */
export async function ingestText(text, userId = 'default') {
  const res = await fetch(`${BASE}/ingest/text`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, user_id: userId }),
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * POST /ingest/audio
 * Sends audio as multipart/form-data with field name 'file', filename 'recording.webm'
 * @param {Blob} audioBlob
 */
export async function ingestAudio(audioBlob) {
  const form = new FormData()
  form.append('file', audioBlob, 'recording.webm')

  const res = await fetch(`${BASE}/ingest/audio`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

/**
 * GET /entries
 * @param {number} limit
 */
export async function getEntries(limit = 20) {
  const res = await fetch(`${BASE}/entries?limit=${limit}`)
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
    headers: { 'Content-Type': 'application/json' },
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
  const res = await fetch(`${BASE}/entries/${entryId}`, { method: 'DELETE' })
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history, top_k: topK }),
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
