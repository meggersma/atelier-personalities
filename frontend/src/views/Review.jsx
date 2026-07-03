import { useState, useEffect } from 'react'
import { analyzeSession, analyzeUpload, getReviewers, buildReviewer } from '../api'

const SEVERITY = {
  critical: { label: 'CRITICAL', color: '#b91c1c', bg: '#fee2e2', border: '#fecaca' },
  major:    { label: 'MAJOR',    color: '#b45309', bg: '#ffedd5', border: '#fed7aa' },
  minor:    { label: 'MINOR',    color: '#374151', bg: '#f3f4f6', border: '#d1d5db' },
  praise:   { label: 'PRAISE',   color: '#15803d', bg: '#dcfce7', border: '#bbf7d0' },
}

const SEV_ORDER = ['critical', 'major', 'minor', 'praise']

const SCORE_LABELS = {
  witness_control: 'Witness Control',
  question_form: 'Question Form',
  sequencing: 'Sequencing',
  impeachment_discipline: 'Impeachment Discipline',
}

const TABS = [
  { id: 'summary', label: 'Summary' },
  { id: 'recommendations', label: 'Recommendations' },
  { id: 'transcript', label: 'Annotated Transcript' },
]

function scoreColor(v) {
  if (v >= 70) return '#15803d'
  if (v >= 50) return '#b45309'
  return '#b91c1c'
}

function avgScore(scores) {
  const vals = Object.keys(SCORE_LABELS).map(k => scores[k])
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)
}

function categoryLabel(cat) {
  return cat.replace(/_/g, ' ')
}

// Rebuild turns the same way the backend adapter does: turn_id = message index.
function turnsFromSession(session) {
  return (session?.messages || []).map((m, i) => ({
    turn_id: i,
    speaker: m.role === 'user' ? 'examiner' : 'witness',
    text: m.content,
  }))
}

function HighlightedText({ text, annotations }) {
  const spans = annotations
    .filter(a => a.span && a.span.start !== null && a.span.end !== null)
    .map(a => ({ start: a.span.start, end: a.span.end, severity: a.severity }))
    .sort((x, y) => x.start - y.start)

  const parts = []
  let cursor = 0
  for (const s of spans) {
    if (s.start < cursor) continue // skip overlapping spans; first one wins
    if (s.start > cursor) parts.push({ text: text.slice(cursor, s.start) })
    parts.push({ text: text.slice(s.start, s.end), severity: s.severity })
    cursor = s.end
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor) })

  return (
    <span>
      {parts.map((p, i) => p.severity ? (
        <mark key={i} style={{
          background: SEVERITY[p.severity].bg,
          color: SEVERITY[p.severity].color,
          borderBottom: `2px solid ${SEVERITY[p.severity].color}`,
          padding: '1px 2px',
          borderRadius: 2,
        }}>{p.text}</mark>
      ) : (
        <span key={i}>{p.text}</span>
      ))}
    </span>
  )
}

function AnnotationCard({ ann, showTurn }) {
  const sev = SEVERITY[ann.severity]
  return (
    <div style={{
      border: `1px solid ${sev.border}`,
      borderLeft: `3px solid ${sev.color}`,
      borderRadius: 4,
      padding: '8px 12px',
      background: 'var(--bg)',
      marginTop: 6,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
          color: sev.color, background: sev.bg,
          padding: '1px 6px', borderRadius: 2,
        }}>{sev.label}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)', textTransform: 'capitalize' }}>
          {categoryLabel(ann.category)}
        </span>
        {showTurn && (
          <span style={{ fontSize: 10, color: 'var(--muted)' }}>turn [{ann.turn_id}]</span>
        )}
      </div>
      {showTurn && ann.span?.quote && (
        <div style={{
          fontSize: 12, color: 'var(--muted)', fontStyle: 'italic',
          marginBottom: 4, lineHeight: 1.45,
        }}>
          “{ann.span.quote}”
        </div>
      )}
      <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.5 }}>{ann.ai_note}</div>
      {ann.suggested_rewrite && (
        <div style={{
          marginTop: 6, fontSize: 12, lineHeight: 1.5,
          padding: '6px 10px', background: 'var(--surface)',
          borderLeft: '2px solid var(--accent2)', borderRadius: 2,
          fontStyle: 'italic', color: 'var(--accent2)',
        }}>
          Rewrite: {ann.suggested_rewrite}
        </div>
      )}
    </div>
  )
}

const CONTROL_HEIGHT = 36

const controlBtnStyle = {
  height: CONTROL_HEIGHT,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
}

function ReviewerSelect({ reviewers, reviewerId, setReviewerId, onAdd }) {
  const current = reviewers.find(r => r.reviewer_id === reviewerId)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <select
          value={reviewerId || ''}
          onChange={e => setReviewerId(e.target.value)}
          style={{
            height: CONTROL_HEIGHT,
            fontSize: 13, fontWeight: 500, padding: '0 12px', borderRadius: 2,
            border: '1px solid var(--border)', background: 'var(--bg)',
            color: 'var(--text)', fontFamily: 'inherit',
            minWidth: 220, cursor: 'pointer',
          }}
        >
          {reviewers.map(r => (
            <option key={r.reviewer_id} value={r.reviewer_id}>
              {r.name}{r.custom ? ' (custom)' : ''}
            </option>
          ))}
        </select>
        <button className="btn" style={controlBtnStyle} onClick={onAdd} title="Add a reviewer from a partner's real feedback">
          + Add
        </button>
      </div>
      {current?.blurb && (
        <span style={{ fontSize: 10.5, color: 'var(--muted)', maxWidth: 300 }}>{current.blurb}</span>
      )}
    </div>
  )
}

const fieldStyle = {
  width: '100%', fontSize: 13, padding: '9px 12px',
  border: '1px solid var(--border)', borderRadius: 2, lineHeight: 1.5,
  background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit',
  outline: 'none',
}

function AddReviewerPanel({ onSave, onCancel }) {
  const [name, setName] = useState('')
  const [materials, setMaterials] = useState('')
  const [fileNames, setFileNames] = useState([])
  const [building, setBuilding] = useState(false)
  const [preview, setPreview] = useState(null)
  const [err, setErr] = useState(null)

  const handleFiles = async (e) => {
    try {
      const files = [...e.target.files]
      const texts = await Promise.all(files.map(f => f.text()))
      setMaterials(prev => [prev, ...texts].filter(Boolean).join('\n\n---\n\n'))
      setFileNames(prev => [...prev, ...files.map(f => f.name)])
    } catch {
      setErr('Could not read one of the files — plain-text files (.txt, .md) work best.')
    }
  }

  const distill = async () => {
    setBuilding(true)
    setErr(null)
    try {
      setPreview(await buildReviewer(name, materials))
    } catch (e2) {
      setErr(e2.message)
    } finally {
      setBuilding(false)
    }
  }

  return (
    <div className="card" style={{ padding: 20, marginBottom: 16, border: '1px solid var(--text)', textAlign: 'left' }}>
      {/* Panel header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Add a Reviewer</div>
        <button
          onClick={onCancel}
          aria-label="Close"
          style={{
            border: 'none', background: 'transparent', color: 'var(--muted)',
            fontSize: 16, lineHeight: 1, cursor: 'pointer', padding: 4, fontFamily: 'inherit',
          }}
        >
          ✕
        </button>
      </div>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14, lineHeight: 1.55, maxWidth: 560 }}>
        Paste or upload samples of a partner's real feedback — redline comments, post-mortem
        memos, emails about depositions. Their reviewing style is distilled into a profile
        you can select like any other reviewer.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Reviewer name (e.g., Jordan Ellis)"
          style={fieldStyle}
        />
        <textarea
          value={materials}
          onChange={e => setMaterials(e.target.value)}
          placeholder="Paste feedback samples here..."
          rows={6}
          style={{ ...fieldStyle, fontSize: 12.5, resize: 'vertical' }}
        />
      </div>

      {/* Footer row: secondary action left, primary action right, everything on one axis */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <label className="btn btn-sm" style={{
          cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        }}>
          Upload files
          <input type="file" multiple accept=".txt,.md,.text" onChange={handleFiles} style={{ display: 'none' }} />
        </label>
        {fileNames.length > 0 && (
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            {fileNames.length} file{fileNames.length > 1 ? 's' : ''} added
            {' — '}{fileNames.slice(0, 2).join(', ')}{fileNames.length > 2 ? '…' : ''}
          </span>
        )}
        <button
          className="btn btn-sm btn-primary"
          style={{ marginLeft: 'auto' }}
          onClick={distill}
          disabled={building || !name.trim() || !materials.trim()}
        >
          {building ? 'Distilling...' : 'Distill Profile'}
        </button>
      </div>
      {err && <div className="error-msg" style={{ marginTop: 10 }}>{err}</div>}

      {preview && (
        <div style={{
          marginTop: 16, padding: 14, background: 'var(--surface)',
          border: '1px solid var(--border-light)', borderRadius: 4,
        }}>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{preview.name}</div>
            <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>{preview.blurb}</div>
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', fontWeight: 700, letterSpacing: 0.5, marginBottom: 4 }}>
            REVIEWING PHILOSOPHY — EDIT BEFORE SAVING
          </div>
          <textarea
            value={preview.emphasis}
            onChange={e => setPreview({ ...preview, emphasis: e.target.value })}
            rows={7}
            style={{ ...fieldStyle, fontSize: 12, resize: 'vertical' }}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
            <button className="btn btn-sm" onClick={() => setPreview(null)}>Discard</button>
            <button className="btn btn-sm btn-primary" onClick={() => onSave(preview)}>
              Save Reviewer
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function UploadTranscriptPanel({ onRun, onCancel }) {
  const [file, setFile] = useState(null)
  const [witnessName, setWitnessName] = useState('')
  const [mode, setMode] = useState('deposition')
  const [caseContext, setCaseContext] = useState('')

  return (
    <div className="card" style={{ padding: 20, marginBottom: 16, border: '1px solid var(--text)', textAlign: 'left' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div className="section-title" style={{ marginBottom: 0 }}>Upload a Transcript</div>
        <button
          onClick={onCancel}
          aria-label="Close"
          style={{
            border: 'none', background: 'transparent', color: 'var(--muted)',
            fontSize: 16, lineHeight: 1, cursor: 'pointer', padding: 4, fontFamily: 'inherit',
          }}
        >
          ✕
        </button>
      </div>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 14, lineHeight: 1.55, maxWidth: 560 }}>
        Upload a prior deposition or cross-examination (.pdf or .txt, Q./A. court-reporter
        format). It goes through the same reviewer as a live session.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <label className="btn" style={{ ...controlBtnStyle, cursor: 'pointer' }}>
            Choose File
            <input
              type="file"
              accept=".pdf,.txt,.text,.md"
              onChange={e => setFile(e.target.files[0] || null)}
              style={{ display: 'none' }}
            />
          </label>
          <span style={{ fontSize: 12, color: file ? 'var(--text)' : 'var(--muted)' }}>
            {file ? file.name : 'No file selected'}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <input
            value={witnessName}
            onChange={e => setWitnessName(e.target.value)}
            placeholder="Witness name (optional — read from the caption if present)"
            style={fieldStyle}
          />
          <select
            value={mode}
            onChange={e => setMode(e.target.value)}
            style={{ ...fieldStyle, width: 220, flex: '0 0 auto', cursor: 'pointer' }}
          >
            <option value="deposition">Deposition</option>
            <option value="cross_examination">Cross-examination</option>
            <option value="direct_examination">Direct examination</option>
          </select>
        </div>
        <textarea
          value={caseContext}
          onChange={e => setCaseContext(e.target.value)}
          placeholder="Case context (optional — helps the reviewer judge strategy)"
          rows={2}
          style={{ ...fieldStyle, fontSize: 12.5, resize: 'vertical' }}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
        <button
          className="btn btn-primary"
          style={controlBtnStyle}
          disabled={!file}
          onClick={() => onRun({ file, witnessName, mode, caseContext })}
        >
          Analyze Transcript
        </button>
      </div>
    </div>
  )
}

export default function Review({ session, analyses, setAnalyses, customReviewers, setCustomReviewers }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [builtins, setBuiltins] = useState([])
  const [reviewerId, setReviewerId] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [tab, setTab] = useState('summary')
  const [adding, setAdding] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)

  useEffect(() => {
    getReviewers()
      .then(data => {
        setBuiltins(data.reviewers || [])
        setReviewerId(prev => prev || data.reviewers?.[0]?.reviewer_id || null)
      })
      .catch(() => {}) // Non-fatal; backend falls back to the default reviewer.
  }, [])

  const reviewers = [...builtins, ...customReviewers]
  const canAnalyze = session && (session.messages || []).length > 0
  const analysis = analyses.find(a => a.analysis_id === selectedId)
    || analyses[analyses.length - 1]
    || null

  // The most recent EARLIER analysis by the same reviewer — the honest
  // baseline for "did I improve," since different reviewers score differently.
  const baseline = analysis ? [...analyses]
    .filter(a =>
      a.reviewer_id === analysis.reviewer_id &&
      a.analysis_id !== analysis.analysis_id &&
      a.created_at < analysis.created_at)
    .sort((x, y) => y.created_at.localeCompare(x.created_at))[0] || null
    : null

  const runAnalysis = async () => {
    setLoading(true)
    setError(null)
    try {
      const custom = customReviewers.find(r => r.reviewer_id === reviewerId) || null
      const result = await analyzeSession(session, custom ? null : reviewerId, custom)
      // Snapshot the turns so the review survives End Session clearing the session.
      const entry = {
        ...result,
        turns: turnsFromSession(session),
        witness_name: session.persona?.name || null,
        reviewer_name: reviewers.find(r => r.reviewer_id === result.reviewer_id)?.name || result.reviewer_id,
      }
      setAnalyses(prev => [...prev, entry])
      setSelectedId(entry.analysis_id)
      setTab('summary')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const runUpload = async ({ file, witnessName, mode, caseContext }) => {
    setLoading(true)
    setError(null)
    try {
      const custom = customReviewers.find(r => r.reviewer_id === reviewerId) || null
      // Uploads come back with turns and witness_name already attached —
      // there's no session for the client to snapshot them from.
      const result = await analyzeUpload(file, {
        witnessName, mode, caseContext,
        reviewerId: custom ? null : reviewerId,
        reviewer: custom,
      })
      const entry = {
        ...result,
        reviewer_name: reviewers.find(r => r.reviewer_id === result.reviewer_id)?.name || result.reviewer_id,
      }
      setAnalyses(prev => [...prev, entry])
      setSelectedId(entry.analysis_id)
      setTab('summary')
      setUploadOpen(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const saveReviewer = (profile) => {
    setCustomReviewers(prev => [...prev.filter(r => r.reviewer_id !== profile.reviewer_id), profile])
    setReviewerId(profile.reviewer_id)
    setAdding(false)
  }

  const reviewerLabel = (a) => a.reviewer_name || a.reviewer_id.replace(/_/g, ' ')

  if (loading) {
    return (
      <div className="view" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 300 }}>
        <div className="spinner" />
        <span style={{ marginLeft: 12, color: 'var(--muted)' }}>
          Reviewing the transcript... (this takes ~30 seconds)
        </span>
      </div>
    )
  }

  if (!analysis) {
    return (
      <div className="view" style={{ maxWidth: 700, margin: '0 auto' }}>
        {adding && <AddReviewerPanel onSave={saveReviewer} onCancel={() => setAdding(false)} />}
        {uploadOpen && <UploadTranscriptPanel onRun={runUpload} onCancel={() => setUploadOpen(false)} />}
        <div className="empty-state">
          <h3>No analysis yet</h3>
          <p>
            {canAnalyze
              ? `Run a reviewer on your current session (${session.messages.length / 2 | 0} exchanges with ${session.persona?.name || 'the witness'}), or upload a prior transcript.`
              : 'Complete an examination in the Examine tab, or upload a prior deposition or cross-examination for feedback.'}
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center', alignItems: 'flex-start', marginTop: 12 }}>
            <ReviewerSelect reviewers={reviewers} reviewerId={reviewerId} setReviewerId={setReviewerId} onAdd={() => setAdding(true)} />
            {canAnalyze && (
              <button className="btn btn-primary" style={controlBtnStyle} onClick={runAnalysis}>
                Analyze Session
              </button>
            )}
            <button
              className={canAnalyze ? 'btn' : 'btn btn-primary'}
              style={controlBtnStyle}
              onClick={() => setUploadOpen(true)}
            >
              Upload Transcript
            </button>
          </div>
          {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}
        </div>
      </div>
    )
  }

  const { summary, annotations, patterns } = analysis
  const turns = analysis.turns || turnsFromSession(session)
  const byTurn = {}
  for (const a of annotations) {
    (byTurn[a.turn_id] = byTurn[a.turn_id] || []).push(a)
  }
  const counts = { critical: 0, major: 0, minor: 0, praise: 0 }
  annotations.forEach(a => counts[a.severity]++)
  const sortedAnns = [...annotations].sort((x, y) =>
    SEV_ORDER.indexOf(x.severity) - SEV_ORDER.indexOf(y.severity) || x.turn_id - y.turn_id)

  return (
    <div className="view" style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700 }}>Session Review</h2>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
            {analysis.witness_name ? `${analysis.witness_name} · ` : ''}
            {analysis.source === 'live_session' ? 'Live session' : 'Uploaded transcript'} ·
            reviewed by {reviewerLabel(analysis)} · {new Date(analysis.created_at).toLocaleString()}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <ReviewerSelect reviewers={reviewers} reviewerId={reviewerId} setReviewerId={setReviewerId} onAdd={() => setAdding(true)} />
          {canAnalyze && (
            <button className="btn" style={controlBtnStyle} onClick={runAnalysis}>Analyze</button>
          )}
          <button className="btn" style={controlBtnStyle} onClick={() => setUploadOpen(true)}>Upload</button>
        </div>
      </div>

      {adding && <AddReviewerPanel onSave={saveReviewer} onCancel={() => setAdding(false)} />}
      {uploadOpen && <UploadTranscriptPanel onRun={runUpload} onCancel={() => setUploadOpen(false)} />}

      {/* History */}
      {analyses.length > 1 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600 }}>HISTORY</span>
          {[...analyses].reverse().map(a => {
            const active = a.analysis_id === analysis.analysis_id
            return (
              <button
                key={a.analysis_id}
                onClick={() => setSelectedId(a.analysis_id)}
                style={{
                  fontSize: 11, padding: '3px 10px', borderRadius: 2,
                  border: active ? '1px solid var(--text)' : '1px solid var(--border)',
                  background: active ? 'var(--text)' : 'var(--bg)',
                  color: active ? 'var(--bg)' : 'var(--text)',
                  cursor: 'pointer', fontFamily: 'inherit',
                }}
              >
                {new Date(a.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                {a.witness_name ? ` · ${a.witness_name}` : ''}
                {' · '}{reviewerLabel(a)}
                {' · '}{avgScore(a.summary.scores)}
              </button>
            )
          })}
        </div>
      )}

      {error && <div className="error-msg" style={{ marginBottom: 12 }}>{error}</div>}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '2px solid var(--text)', marginBottom: 16 }}>
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              fontSize: 12, fontWeight: 600, padding: '7px 16px',
              border: 'none', borderRadius: '2px 2px 0 0', cursor: 'pointer',
              fontFamily: 'inherit',
              background: tab === t.id ? 'var(--text)' : 'transparent',
              color: tab === t.id ? 'var(--bg)' : 'var(--muted)',
            }}
          >
            {t.label}
            {t.id === 'recommendations' && ` (${counts.critical + counts.major})`}
          </button>
        ))}
        <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 'auto', alignSelf: 'center' }}>
          {counts.critical} critical · {counts.major} major · {counts.minor} minor · {counts.praise} praise
        </span>
      </div>

      {/* ── Summary tab ── */}
      {tab === 'summary' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
            {Object.entries(SCORE_LABELS).map(([key, label]) => {
              const v = summary.scores[key]
              const delta = baseline ? v - baseline.summary.scores[key] : null
              return (
                <div key={key} className="card" style={{ padding: '12px 14px' }}>
                  <div style={{ fontSize: 11, color: 'var(--muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    {label}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '4px 0' }}>
                    <span style={{ fontSize: 26, fontWeight: 800, color: scoreColor(v) }}>{v}</span>
                    {delta !== null && delta !== 0 && (
                      <span style={{
                        fontSize: 12, fontWeight: 700,
                        color: delta > 0 ? '#15803d' : '#b91c1c',
                      }}>
                        {delta > 0 ? '▲' : '▼'} {Math.abs(delta)}
                      </span>
                    )}
                  </div>
                  <div className="progress-bar">
                    <div className="progress-fill" style={{ width: `${v}%`, background: scoreColor(v) }} />
                  </div>
                </div>
              )
            })}
          </div>
          {baseline && (
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: -10, marginBottom: 14 }}>
              Deltas vs. previous review by {reviewerLabel(baseline)} on{' '}
              {new Date(baseline.created_at).toLocaleDateString()}
            </div>
          )}

          <div className="card" style={{ padding: 16, marginBottom: 16 }}>
            <div className="section-title">Reviewer Memo</div>
            <p style={{ fontSize: 13, lineHeight: 1.65, marginBottom: 12 }}>{summary.memo}</p>
            <div className="section-title">Try Next Session</div>
            <ol style={{ paddingLeft: 20 }}>
              {summary.try_next.map((t, i) => (
                <li key={i} style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 6 }}>{t}</li>
              ))}
            </ol>
          </div>

          {patterns.length > 0 && (
            <div className="card" style={{ padding: 16, marginBottom: 16 }}>
              <div className="section-title">Recurring Patterns</div>
              {patterns.map(p => (
                <div key={p.pattern_id} style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                    <span className="badge badge-blue">{p.label.replace(/_/g, ' ')}</span>
                    <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                      turns {p.turn_ids.map(t => `[${t}]`).join(' ')}
                    </span>
                  </div>
                  <div style={{ fontSize: 12.5, lineHeight: 1.55 }}>{p.note}</div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Recommendations tab ── */}
      {tab === 'recommendations' && (
        <div style={{ maxWidth: 760 }}>
          {sortedAnns.length === 0 && (
            <p style={{ fontSize: 13, color: 'var(--muted)' }}>No annotations in this review.</p>
          )}
          {sortedAnns.map(a => <AnnotationCard key={a.annotation_id} ann={a} showTurn />)}
        </div>
      )}

      {/* ── Transcript tab ── */}
      {tab === 'transcript' && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          {turns.map(turn => {
            const anns = byTurn[turn.turn_id] || []
            const isExaminer = turn.speaker === 'examiner'
            return (
              <div key={turn.turn_id} style={{
                padding: '10px 16px',
                borderBottom: '1px solid var(--border-light)',
                background: isExaminer ? 'var(--bg)' : 'var(--surface)',
              }}>
                <div style={{ display: 'flex', gap: 10 }}>
                  <span style={{
                    fontSize: 10, fontWeight: 700, letterSpacing: 0.5,
                    color: 'var(--muted)', minWidth: 76, paddingTop: 2,
                  }}>
                    [{turn.turn_id}] {(turn.speaker || 'witness').toUpperCase()}
                  </span>
                  <div style={{ flex: 1, fontSize: 13, lineHeight: 1.6 }}>
                    <HighlightedText text={turn.text} annotations={anns} />
                    {anns.map(a => <AnnotationCard key={a.annotation_id} ann={a} />)}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
