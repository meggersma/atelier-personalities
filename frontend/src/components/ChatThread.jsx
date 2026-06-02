import { useEffect, useRef, useState } from 'react'

const EVENT_STYLES = {
  intimidation: {
    background: '#fee2e2',
    border: '1px solid #fca5a5',
    borderLeft: '3px solid #b91c1c',
    color: '#7f1d1d',
  },
  combative: {
    background: '#fff1f2',
    border: '1px solid #fda4af',
    borderLeft: '3px solid #881337',
    color: '#881337',
  },
  attorney_interrupts: {
    background: '#f8fafc',
    border: '1px solid #cbd5e1',
    borderTop: '2px solid #334155',
    color: '#334155',
  },
  witness_interrupts: {
    background: '#fafafa',
    border: '1px dashed #9ca3af',
    color: '#374151',
  },
  personality_shift: {
    background: '#f0fdf4',
    border: '1px dashed #86efac',
    borderLeft: '3px solid #16a34a',
    color: '#14532d',
  },
}

function EventBanner({ event }) {
  const style = EVENT_STYLES[event.type] || {
    background: '#f3f4f6',
    border: '1px solid #d1d5db',
    color: '#374151',
  }
  return (
    <div style={{
      ...style,
      borderRadius: 3,
      padding: '6px 12px',
      marginBottom: 8,
      fontSize: 11,
      display: 'flex',
      alignItems: 'baseline',
      gap: 8,
    }}>
      <span style={{ fontWeight: 800, textTransform: 'uppercase', letterSpacing: 0.5, whiteSpace: 'nowrap' }}>
        {event.label}
      </span>
      <span style={{ opacity: 0.7, fontSize: 10 }}>{event.detail}</span>
    </div>
  )
}

function ToneLabel({ tone }) {
  if (!tone || tone === 'neutral, measured') return null
  return (
    <div style={{
      marginTop: 5,
      fontSize: 10,
      color: '#9ca3af',
      fontStyle: 'italic',
      letterSpacing: 0.3,
    }}>
      tone: {tone}
    </div>
  )
}

function StateDeltaBadges({ delta }) {
  const significant = Object.entries(delta || {}).filter(([, v]) => Math.abs(v) > 0.01)
  if (!significant.length) return null

  const DIM_LABELS = { C: 'Composure', K: 'Knowledge', A: 'Agree', V: 'Verbose', R: 'Rigid', P: 'Perf' }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
      {significant.map(([dim, val]) => {
        const isPos = val > 0
        return (
          <span key={dim} style={{
            background: isPos ? '#dcfce7' : '#fee2e2',
            border: `1px solid ${isPos ? '#86efac' : '#fca5a5'}`,
            color: isPos ? '#15803d' : '#b91c1c',
            padding: '1px 7px',
            borderRadius: 2,
            fontSize: 10,
            fontFamily: 'monospace',
          }}>
            {DIM_LABELS[dim]}: {isPos ? '+' : ''}{val.toFixed(3)}
          </span>
        )
      })}
    </div>
  )
}

function WitnessMessage({ msg }) {
  const [showAnalysis, setShowAnalysis] = useState(false)
  const hasAnalysis = msg.encoding != null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', marginBottom: 20 }}>
      {/* Event banners sit above the response bubble */}
      {msg.events && msg.events.length > 0 && (
        <div style={{ width: '90%', marginBottom: 6 }}>
          {msg.events.map((ev, i) => <EventBanner key={i} event={ev} />)}
        </div>
      )}

      {/* Response bubble */}
      <div
        onClick={() => hasAnalysis && setShowAnalysis(s => !s)}
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: '3px 10px 10px 3px',
          padding: '12px 16px',
          maxWidth: '82%',
          fontSize: 14,
          lineHeight: 1.75,
          color: 'var(--text)',
          cursor: hasAnalysis ? 'pointer' : 'default',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {msg.content}
      </div>

      {/* Tone + spoken indicator + toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 4 }}>
        <ToneLabel tone={msg.tone} />
        {msg.spoken && (
          <span style={{ fontSize: 10, color: '#9ca3af' }}>
            🔊 spoken
          </span>
        )}
        {hasAnalysis && (
          <span
            style={{ fontSize: 10, color: 'var(--muted)', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setShowAnalysis(s => !s)}
          >
            {showAnalysis ? '▲ hide analysis' : '▼ analysis'}
          </span>
        )}
      </div>

      {/* Analysis panel */}
      {showAnalysis && hasAnalysis && (
        <div style={{
          marginTop: 6,
          background: 'var(--surface2)',
          border: '1px solid var(--border)',
          borderRadius: 3,
          padding: '10px 14px',
          fontSize: 11,
          maxWidth: '82%',
        }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 6 }}>
            <PressureBadge value={msg.encoding.pressure} />
            <TypeBadge type={msg.encoding.question_type} />
            {msg.encoding.sensitivity > 0.1 && (
              <span style={{
                background: '#fef3c7', border: '1px solid #fde68a',
                color: '#92400e', padding: '1px 7px', borderRadius: 2,
                fontSize: 10, fontWeight: 700,
              }}>
                SENS {(msg.encoding.sensitivity * 100).toFixed(0)}%
              </span>
            )}
          </div>
          {msg.encoding.hit_topics?.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
              <span style={{ color: 'var(--muted)', fontSize: 10 }}>Topics:</span>
              {msg.encoding.hit_topics.map((t, i) => (
                <span key={i} style={{
                  background: '#fef9c3', border: '1px solid #fde68a',
                  color: '#78350f', padding: '1px 7px', borderRadius: 2, fontSize: 10,
                }}>
                  {t}
                </span>
              ))}
            </div>
          )}
          <StateDeltaBadges delta={msg.state_delta} />
        </div>
      )}
    </div>
  )
}

function PressureBadge({ value }) {
  const label = value >= 0.7 ? 'HIGH' : value >= 0.4 ? 'MED' : 'LOW'
  const styles = {
    HIGH: { background: '#fee2e2', border: '1px solid #fca5a5', color: '#b91c1c' },
    MED:  { background: '#fef3c7', border: '1px solid #fde68a', color: '#92400e' },
    LOW:  { background: '#dcfce7', border: '1px solid #86efac', color: '#15803d' },
  }[label]
  return (
    <span style={{ ...styles, padding: '1px 7px', borderRadius: 2, fontSize: 10, fontWeight: 700 }}>
      PRESSURE {label} {(value * 100).toFixed(0)}%
    </span>
  )
}

function TypeBadge({ type }) {
  const styles = {
    leading:     { background: '#fee2e2', border: '1px solid #fca5a5', color: '#b91c1c' },
    hypothetical:{ background: '#fef3c7', border: '1px solid #fde68a', color: '#92400e' },
    closed:      { background: '#cffafe', border: '1px solid #a5f3fc', color: '#0e7490' },
    open:        { background: '#f3f4f6', border: '1px solid #d1d5db', color: '#374151' },
  }
  const s = styles[type] || styles.open
  return (
    <span style={{ ...s, padding: '1px 7px', borderRadius: 2, fontSize: 10, fontWeight: 700, textTransform: 'uppercase' }}>
      {type}
    </span>
  )
}

function AttorneyMessage({ msg }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', marginBottom: 20 }}>
      <div style={{
        background: '#111111',
        border: '1px solid #111111',
        borderRadius: '10px 3px 3px 10px',
        padding: '12px 16px',
        maxWidth: '82%',
        fontSize: 14,
        lineHeight: 1.75,
        color: '#ffffff',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        textAlign: 'right',
      }}>
        {msg.content}
      </div>
    </div>
  )
}

export default function ChatThread({ messages, loading }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  if (messages.length === 0 && !loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>
        <div style={{ fontSize: 28, marginBottom: 10 }}>⚖</div>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>Begin the examination.</div>
        <div style={{ fontSize: 12 }}>Use the suggested questions below or compose your own.</div>
      </div>
    )
  }

  return (
    <div style={{ padding: '20px 24px' }}>
      {messages.map((msg, i) =>
        msg.role === 'user'
          ? <AttorneyMessage key={i} msg={msg} />
          : <WitnessMessage key={i} msg={msg} />
      )}

      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', color: 'var(--muted)' }}>
          <div className="spinner" />
          <span style={{ fontSize: 12 }}>Witness responding...</span>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
