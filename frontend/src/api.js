const API_ORIGIN = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const BASE = `${API_ORIGIN}/api`

async function errorDetail(res) {
  const t = await res.text()
  try {
    const j = JSON.parse(t)
    const d = j.detail
    if (Array.isArray(d)) return (d[0] ?? t) || String(res.status)
    return (d ?? t) || String(res.status)
  } catch {
    return t || String(res.status)
  }
}

export async function ingestFiles(files) {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  const res = await fetch(`${BASE}/ingest`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Ingest failed: ${await errorDetail(res)}`)
  return res.json()
}

export async function extractCandidates(segments, supplementalInfo = '') {
  const res = await fetch(`${BASE}/extract-candidates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      segment_ids: (segments || []).map(s => s.id),
      segments,
      supplemental_info: supplementalInfo,
    })
  })
  if (!res.ok) throw new Error(`Extract candidates failed: ${await errorDetail(res)}`)
  return res.json()
}

export async function buildPersona(candidate, supportSegments, supplementalInfo = '', mode = 'cross_examination') {
  const res = await fetch(`${BASE}/build-persona`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      candidate,
      support_segment_ids: (supportSegments || []).map(s => s.id),
      support_segments: supportSegments,
      supplemental_info: supplementalInfo,
      mode,
    })
  })
  if (!res.ok) throw new Error(`Build persona failed: ${res.status}`)
  return res.json()
}

export async function createSession(persona, personalityState, memoryOverrides = []) {
  const res = await fetch(`${BASE}/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      persona_id: persona?.persona_id || null,
      persona,
      personality_state: personalityState,
      memory_overrides: memoryOverrides
    })
  })
  if (!res.ok) throw new Error(`Create session failed: ${res.status}`)
  return res.json()
}

export async function chat(session, message) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: session?.session_id || null, session, message })
  })
  if (!res.ok) throw new Error(`Chat failed: ${res.status}`)
  return res.json()
}

export async function createRealtimeSession(sessionId, voice, session) {
  const body = { session_id: sessionId, session }
  if (voice) body.voice = voice
  const res = await fetch(`${BASE}/realtime/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Realtime session failed: ${await errorDetail(res)}`)
  return res.json()
}

export async function analyzeSession(session, reviewerId = null, reviewer = null) {
  const res = await fetch(`${BASE}/analysis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: session?.session_id || null,
      session,
      reviewer_id: reviewerId,
      reviewer,
    })
  })
  if (!res.ok) throw new Error(`Analysis failed: ${await errorDetail(res)}`)
  return res.json()
}

export async function analyzeUpload(file, { witnessName = '', mode = '', caseContext = '', reviewerId = null, reviewer = null } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (witnessName) form.append('witness_name', witnessName)
  if (mode) form.append('mode', mode)
  if (caseContext) form.append('case_context', caseContext)
  if (reviewerId) form.append('reviewer_id', reviewerId)
  if (reviewer) form.append('reviewer', JSON.stringify(reviewer))
  const res = await fetch(`${BASE}/analysis/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Upload analysis failed: ${await errorDetail(res)}`)
  return res.json()
}

export async function buildReviewer(name, materials) {
  const res = await fetch(`${BASE}/reviewers/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, materials })
  })
  if (!res.ok) throw new Error(`Build reviewer failed: ${await errorDetail(res)}`)
  return res.json()
}

export async function getReviewers() {
  const res = await fetch(`${BASE}/reviewers`)
  if (!res.ok) throw new Error(`Get reviewers failed: ${await errorDetail(res)}`)
  return res.json()
}

export async function getSuggestedQuestions(session) {
  const res = await fetch(`${BASE}/session/__client__/suggested-questions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: session?.session_id || null, session })
  })
  if (!res.ok) throw new Error(`Get suggested questions failed: ${res.status}`)
  return res.json()
}
