export const ARCHETYPES = {
  Neutral:       [0.80, 0.80, 0.60, 0.40, 0.50, 0.30],
  Loquacious:    [0.60, 0.60, 0.70, 0.95, 0.30, 0.40],
  Combative:     [0.70, 0.30, 0.05, 0.20, 0.70, 0.40],
  Cooperative:   [0.80, 0.90, 0.95, 0.50, 0.30, 0.30],
  Forgetful:     [0.40, 0.40, 0.60, 0.75, 0.30, 0.30],
  Inventive:     [0.70, 0.10, 0.50, 0.60, 0.60, 0.70],
  Evasive:       [0.60, 0.10, 0.40, 0.55, 0.50, 0.50],
  Defensive:     [0.40, 0.50, 0.20, 0.35, 0.70, 0.50],
  Overconfident: [0.90, 0.40, 0.50, 0.70, 0.80, 0.70],
  Dogmatic:      [0.80, 0.60, 0.40, 0.50, 0.95, 0.60],
  Nervous:       [0.10, 0.60, 0.50, 0.40, 0.30, 0.20],
  Overprepared:  [0.90, 0.70, 0.60, 0.50, 0.70, 0.95],
  Pedantic:      [0.80, 0.70, 0.50, 0.70, 0.80, 0.50],
  Charming:      [0.90, 0.60, 0.90, 0.70, 0.40, 0.80],
}

export function inferArchetype(values) {
  // values: [C, K, A, V, R, P]
  // Return name of closest archetype by euclidean distance
  let best = null, bestDist = Infinity
  for (const [name, preset] of Object.entries(ARCHETYPES)) {
    const dist = Math.sqrt(preset.reduce((sum, v, i) => sum + (v - values[i]) ** 2, 0))
    if (dist < bestDist) { bestDist = dist; best = name }
  }
  return best
}
