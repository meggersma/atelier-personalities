export function composureLabel(v) {
  if (v < 0.25) return "barely keeping it together"
  if (v < 0.40) return "visibly rattled"
  if (v < 0.55) return "uneasy, choosing words carefully"
  if (v < 0.72) return "cautious but composed"
  return "calm and fully controlled"
}

export function knowledgeLabel(v) {
  if (v < 0.20) return "severely impaired, contradicting self"
  if (v < 0.40) return "unreliable, gaps emerging"
  if (v < 0.60) return "moderate, some gaps"
  if (v < 0.80) return "good, mostly reliable"
  return "excellent, sharp recall"
}

export function agreeablenessLabel(v) {
  if (v < 0.20) return "openly hostile"
  if (v < 0.38) return "defensive, resistant"
  if (v < 0.60) return "neutral"
  if (v < 0.80) return "cooperative"
  return "highly cooperative"
}

export function verbosityLabel(v) {
  if (v < 0.20) return "terse, yes/no only"
  if (v < 0.40) return "brief, to the point"
  if (v < 0.60) return "moderate answers"
  if (v < 0.80) return "elaborates, adds context"
  return "highly verbose, tangents"
}

export function rigidityLabel(v) {
  if (v < 0.20) return "open to revision"
  if (v < 0.40) return "will adjust when pressed"
  if (v < 0.60) return "holds account, can be nudged"
  if (v < 0.80) return "firm, resists changes"
  return "immovable, rigidly insists"
}

export function performanceLabel(v) {
  if (v < 0.20) return "unprepared, confused"
  if (v < 0.40) return "poorly prepared, struggling"
  if (v < 0.60) return "adequately prepared"
  if (v < 0.80) return "well-prepared, confident"
  return "exceptionally prepared"
}

export function computeScores(state) {
  const { C, K, A, V, R, P } = state
  const consistency = 0.5 * K + 0.4 * R - 0.1 * (1 - K) * (1 - R)
  const evasion = 0.5 * (1 - K) + 0.3 * Math.abs(V - 0.5) * 2 + 0.2 * P
  const realism_raw = 1.0 - 0.3 * (Math.abs(C - 0.5) * 2) - 0.3 * (Math.abs(K - 0.5) * 2) - 0.4 * (Math.max(0, P - 0.8) * 5)
  const realism = Math.max(0, realism_raw)
  const adversarial = 0.4 * (1 - K) + 0.3 * (1 - A) + 0.2 * R + 0.1 * (1 - C)
  return {
    consistency: Math.round(consistency * 1000) / 1000,
    evasion: Math.round(evasion * 1000) / 1000,
    realism: Math.round(realism * 1000) / 1000,
    adversarial: Math.round(adversarial * 1000) / 1000,
  }
}
