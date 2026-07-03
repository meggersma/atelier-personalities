import { useEffect, useState } from 'react'
import Upload from './views/Upload'
import Personas from './views/Personas'
import Configure from './views/Configure'
import Examine from './views/Examine'
import Review from './views/Review'
import './app.css'

const STORAGE_KEY = 'witness-sim-state'

export default function App() {
  const [view, setView] = useState('upload')
  const [segments, setSegments] = useState([])
  const [documents, setDocuments] = useState([]) // [{document_id, name, segment_count}]
  const [candidates, setCandidates] = useState([])
  const [personas, setPersonas] = useState([])
  const [session, setSession] = useState(null)
  const [configPersonaId, setConfigPersonaId] = useState(null)
  const [analyses, setAnalyses] = useState([])
  const [customReviewers, setCustomReviewers] = useState([])

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const saved = JSON.parse(raw)
      setSegments(saved.segments || [])
      setDocuments(saved.documents || [])
      setCandidates(saved.candidates || [])
      setPersonas(saved.personas || [])
      setSession(saved.session || null)
      setConfigPersonaId(saved.configPersonaId || null)
      // Migrate the pre-history shape (single saved analysis) into the array.
      setAnalyses(saved.analyses || (saved.analysis ? [saved.analysis] : []))
      setCustomReviewers(saved.customReviewers || [])
    } catch {
      // Ignore corrupt local state.
    }
  }, [])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      segments,
      documents,
      candidates,
      personas,
      session,
      configPersonaId,
      analyses,
      customReviewers,
    }))
  }, [segments, documents, candidates, personas, session, configPersonaId, analyses, customReviewers])

  const nav = [
    { id: 'upload', label: 'Upload' },
    { id: 'personas', label: 'Personas' },
    { id: 'configure', label: 'Configure' },
    { id: 'examine', label: 'Examine' },
    { id: 'review', label: 'Review' },
  ]

  return (
    <div>
      <nav className="nav">
        <span className="nav-title">WITNESS SIM</span>
        {nav.map(n => (
          <button
            key={n.id}
            className={`nav-btn${view === n.id ? ' active' : ''}`}
            onClick={() => setView(n.id)}
          >
            {n.label}
          </button>
        ))}
      </nav>

      {view === 'upload' && (
        <Upload
          segments={segments}
          setSegments={setSegments}
          documents={documents}
          setDocuments={setDocuments}
          candidates={candidates}
          setCandidates={setCandidates}
          personas={personas}
          setPersonas={setPersonas}
          onPersonaBuilt={() => setView('personas')}
        />
      )}

      {view === 'personas' && (
        <Personas
          personas={personas}
          setPersonas={setPersonas}
          onConfigure={(personaId) => {
            setConfigPersonaId(personaId)
            setView('configure')
          }}
        />
      )}

      {view === 'configure' && (
        <Configure
          personas={personas}
          configPersonaId={configPersonaId}
          setConfigPersonaId={setConfigPersonaId}
          onSessionStart={(nextSession) => {
            setSession(nextSession)
            setView('examine')
          }}
        />
      )}

      {view === 'examine' && (
        <Examine
          session={session}
          setSession={setSession}
          onReset={() => setView('configure')}
          onReview={() => setView('review')}
        />
      )}

      {view === 'review' && (
        <Review
          session={session}
          analyses={analyses}
          setAnalyses={setAnalyses}
          customReviewers={customReviewers}
          setCustomReviewers={setCustomReviewers}
        />
      )}
    </div>
  )
}
