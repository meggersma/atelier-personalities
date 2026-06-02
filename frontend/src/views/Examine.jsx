import { useState, useEffect, useRef, useCallback } from 'react'
import { chat, getSuggestedQuestions, createRealtimeSession } from '../api'
import ChatThread from '../components/ChatThread'
import StateDashboard from '../components/StateDashboard'
import useRealtimeVoice from '../hooks/useRealtimeVoice'

const VOICE_OPTIONS = [
  { id: 'ash', label: 'Ash', desc: 'Neutral, versatile' },
  { id: 'ballad', label: 'Ballad', desc: 'Warm, empathetic' },
  { id: 'coral', label: 'Coral', desc: 'Clear, expressive' },
  { id: 'echo', label: 'Echo', desc: 'Deep, measured' },
  { id: 'sage', label: 'Sage', desc: 'Authoritative' },
  { id: 'shimmer', label: 'Shimmer', desc: 'Bright, warm' },
  { id: 'verse', label: 'Verse', desc: 'Balanced' },
]

export default function Examine({ session, setSession, onReset }) {
  const [messages, setMessages] = useState([])
  const [state, setState] = useState(null)
  const [state0, setState0] = useState(null)
  const [memory, setMemory] = useState({})
  const [trajectory, setTrajectory] = useState([])
  const [scores, setScores] = useState(null)
  const [scoresTrajectory, setScoresTrajectory] = useState([])
  const [suggestedQuestions, setSuggestedQuestions] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingSession, setLoadingSession] = useState(true)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  // Voice mode state
  const [voiceMode, setVoiceMode] = useState(false)
  const [voiceConnecting, setVoiceConnecting] = useState(false)
  const [selectedVoice, setSelectedVoice] = useState('ash')

  const voiceRef = useRef(null)

  const handleVoiceError = useCallback((msg) => {
    setError(msg)
    setVoiceMode(false)
    setVoiceConnecting(false)
  }, [])

  const handleVoiceTranscript = useCallback(async (text) => {
    if (!text?.trim() || loading || !session) return

    setLoading(true)
    setError(null)

    const userMsg = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])

    try {
      const result = await chat(session, text)

      const assistantMsg = {
        role: 'assistant',
        content: result.reply,
        encoding: result.encoding,
        state_delta: result.state_delta,
        scores: result.scores,
        events: result.events || [],
        tone: result.tone || null,
        spoken: true,
      }

      setMessages(prev => [...prev, assistantMsg])
      setSession(result.session)
      setState(result.state)
      setScores(result.scores)
      setMemory(result.session.memory || {})
      setTrajectory(result.session.trajectory || [])
      setScoresTrajectory(result.session.scores_trajectory || [])
      fetchSuggestedQuestions(result.session)

      voiceRef.current?.injectResponse(result.reply, result.voice_instructions)
    } catch (err) {
      setError(err.message)
      setMessages(prev => prev.slice(0, -1))
      voiceRef.current?.unmuteMic()
    } finally {
      setLoading(false)
    }
  }, [loading, session])

  const voice = useRealtimeVoice({
    onTranscript: handleVoiceTranscript,
    onError: handleVoiceError,
  })
  voiceRef.current = voice

  useEffect(() => {
    if (!session) {
      setSuggestedQuestions([])
      setLoadingSession(false)
      return
    }
    setMessages(session.messages || [])
    setState(session.state || null)
    setState0(session.state_0 || null)
    setMemory(session.memory || {})
    setScores(session.scores_trajectory?.[session.scores_trajectory.length - 1] || null)
    setTrajectory(session.trajectory || (session.state ? [session.state] : []))
    setScoresTrajectory(session.scores_trajectory || [])
    setLoadingSession(false)
    fetchSuggestedQuestions(session)
  }, [session])

  const fetchSuggestedQuestions = async (activeSession) => {
    try {
      const data = await getSuggestedQuestions(activeSession)
      setSuggestedQuestions(data.questions || [])
    } catch {
      // Non-fatal
    }
  }

  const handleVoiceToggle = async () => {
    if (voiceMode) {
      voice.disconnect()
      setVoiceMode(false)
      return
    }

    setVoiceConnecting(true)
    setError(null)
    try {
      const data = await createRealtimeSession(session.session_id, selectedVoice, session)
      await voice.connect(data.client_secret, {
        voice: data.voice,
        voiceInstructions: data.voice_instructions,
      })
      setVoiceMode(true)
    } catch (err) {
      setError(`Voice connection failed: ${err.message}`)
    } finally {
      setVoiceConnecting(false)
    }
  }

  const handleSend = async () => {
    const msg = input.trim()
    if (!msg || loading || !session) return

    setInput('')
    setLoading(true)
    setError(null)

    const userMsg = { role: 'user', content: msg }
    setMessages(prev => [...prev, userMsg])

    try {
      const result = await chat(session, msg)

      const assistantMsg = {
        role: 'assistant',
        content: result.reply,
        encoding: result.encoding,
        state_delta: result.state_delta,
        scores: result.scores,
        events: result.events || [],
        tone: result.tone || null,
        spoken: voiceMode && voice.isConnected,
      }

      setMessages(prev => [...prev, assistantMsg])
      setSession(result.session)
      setState(result.state)
      setScores(result.scores)
      setMemory(result.session.memory || {})
      setTrajectory(result.session.trajectory || [])
      setScoresTrajectory(result.session.scores_trajectory || [])
      fetchSuggestedQuestions(result.session)

      if (voiceMode && voice.isConnected) {
        voice.injectResponse(result.reply, result.voice_instructions)
      }
    } catch (err) {
      setError(err.message)
      setMessages(prev => prev.slice(0, -1))
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleEndSession = async () => {
    if (window.confirm('End this examination session?')) {
      voice.disconnect()
      setVoiceMode(false)
      setSession(null)
      onReset()
    }
  }

  if (loadingSession) {
    return (
      <div className="view" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="spinner" />
        <span style={{ marginLeft: 12, color: 'var(--muted)' }}>Loading session...</span>
      </div>
    )
  }

  if (!session) {
    return (
      <div className="view">
        <div className="empty-state">
          <h3>No active session</h3>
          <p>Configure a witness in the Configure tab to start a session.</p>
        </div>
      </div>
    )
  }

  const persona = session?.persona || {}

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 57px)', overflow: 'hidden' }}>
      {/* Left: Chat Panel - 65% */}
      <div style={{ width: '65%', display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)' }}>
        {/* Session header */}
        <div style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--surface)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div>
            <span style={{ fontWeight: 600, color: 'var(--text)' }}>{persona.name}</span>
            <span style={{ color: 'var(--muted)', fontSize: 12, marginLeft: 8 }}>
              {persona.role}{persona.organization ? ` · ${persona.organization}` : ''}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: 'var(--muted)', fontSize: 11 }}>
              Turn {session?.turn || 0}
            </span>

            {/* Voice selector */}
            {!voiceMode && (
              <select
                value={selectedVoice}
                onChange={(e) => setSelectedVoice(e.target.value)}
                style={{
                  fontSize: 11,
                  padding: '3px 6px',
                  borderRadius: 4,
                  border: '1px solid var(--border)',
                  background: 'var(--bg)',
                  color: 'var(--text)',
                  fontFamily: 'inherit',
                }}
              >
                {VOICE_OPTIONS.map(v => (
                  <option key={v.id} value={v.id}>{v.label} — {v.desc}</option>
                ))}
              </select>
            )}

            {/* Voice toggle */}
            <button
              onClick={handleVoiceToggle}
              disabled={voiceConnecting}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '4px 10px',
                borderRadius: 4,
                border: voiceMode
                  ? '1px solid #22c55e'
                  : '1px solid var(--border)',
                background: voiceMode
                  ? 'rgba(34,197,94,0.1)'
                  : 'var(--surface)',
                color: voiceMode ? '#16a34a' : 'var(--text)',
                fontSize: 11,
                fontWeight: 600,
                cursor: voiceConnecting ? 'default' : 'pointer',
                fontFamily: 'inherit',
                transition: 'all 0.15s',
              }}
            >
              {voiceConnecting ? (
                <><div className="spinner" style={{ width: 12, height: 12 }} /> Connecting...</>
              ) : voiceMode ? (
                <>{voice.isSpeaking ? '🔊' : voice.isListening ? '🎤' : '✓'} Voice On</>
              ) : (
                <>🎤 Voice</>
              )}
            </button>

            <button className="btn btn-sm btn-danger" onClick={handleEndSession}>
              End Session
            </button>
          </div>
        </div>

        {/* Chat Thread */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <ChatThread messages={messages} loading={loading} />
        </div>

        {/* Error */}
        {error && (
          <div style={{ padding: '0 16px' }}>
            <div className="error-msg">{error}</div>
          </div>
        )}

        {/* Suggested Questions */}
        {suggestedQuestions.length > 0 && (
          <div style={{ padding: '8px 16px', borderTop: '1px solid var(--border)', background: 'var(--surface)' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'var(--muted)', marginRight: 4 }}>Suggested:</span>
              {suggestedQuestions.map((q, i) => (
                <button
                  key={i}
                  onClick={() => setInput(q)}
                  style={{
                    background: 'rgba(99,102,241,0.1)',
                    border: '1px solid rgba(99,102,241,0.3)',
                    borderRadius: 4,
                    color: 'var(--accent)',
                    padding: '3px 10px',
                    fontSize: 11,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    transition: 'all 0.15s',
                    maxWidth: 300,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  onMouseEnter={e => e.target.style.background = 'rgba(99,102,241,0.2)'}
                  onMouseLeave={e => e.target.style.background = 'rgba(99,102,241,0.1)'}
                >
                  {q.length > 60 ? q.substring(0, 57) + '...' : q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Voice status bar */}
        {voiceMode && voice.isConnected && (
          <div style={{
            padding: '8px 16px',
            borderTop: '1px solid var(--border)',
            background: voice.isSpeaking
              ? 'rgba(99,102,241,0.08)'
              : voice.isListening
                ? 'rgba(34,197,94,0.06)'
                : 'var(--surface)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            transition: 'background 0.3s',
          }}>
            <div style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: voice.isSpeaking
                ? '#6366f1'
                : voice.isListening
                  ? '#22c55e'
                  : loading
                    ? '#f59e0b'
                    : '#9ca3af',
              animation: (voice.isListening || voice.isSpeaking) ? 'pulse 1.5s ease-in-out infinite' : 'none',
            }} />
            <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 500 }}>
              {voice.isSpeaking
                ? '🔊 Witness speaking...'
                : voice.isListening
                  ? '🎤 Listening — ask your question'
                  : loading
                    ? '⏳ Witness thinking...'
                    : 'Ready'}
            </span>
            {voice.error && (
              <span style={{ fontSize: 11, color: '#ef4444', marginLeft: 'auto' }}>
                {voice.error}
              </span>
            )}
          </div>
        )}

        {/* Input Area */}
        <div style={{
          padding: 12,
          borderTop: '1px solid var(--border)',
          background: 'var(--surface)',
          display: 'flex',
          gap: 10,
          alignItems: 'flex-end',
        }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={voiceMode && voice.isConnected
              ? "Speak or type your question..."
              : "Type your question... (Enter to send, Shift+Enter for newline)"}
            rows={2}
            style={{
              flex: 1,
              resize: 'none',
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              color: 'var(--text)',
              padding: '10px 12px',
              fontFamily: 'inherit',
              fontSize: 13,
              outline: 'none',
            }}
            disabled={loading}
          />
          <button
            className="btn btn-primary"
            style={{ padding: '10px 20px', height: 52 }}
            onClick={handleSend}
            disabled={loading || !input.trim()}
          >
            {loading ? (
              <div className="spinner" style={{ width: 14, height: 14 }} />
            ) : 'Send'}
          </button>
        </div>
      </div>

      {/* Right: State Dashboard - 35% */}
      <div style={{ width: '35%', overflowY: 'auto', padding: 16 }}>
        {state && (
          <StateDashboard
            state={state}
            state0={state0}
            memory={memory}
            scores={scores}
            trajectory={trajectory}
            scoresTrajectory={scoresTrajectory}
            messages={messages}
            persona={persona}
          />
        )}
      </div>
    </div>
  )
}
