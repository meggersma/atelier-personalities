import { useState, useRef, useCallback, useEffect } from 'react'

const REALTIME_URL = 'https://api.openai.com/v1/realtime/calls'

const TURN_STATES = {
  IDLE: 'idle',
  LISTENING: 'listening',
  PROCESSING: 'processing',
  SPEAKING: 'speaking',
}

export default function useRealtimeVoice({ onTranscript, onError }) {
  const [isConnected, setIsConnected] = useState(false)
  const [turnState, setTurnState] = useState(TURN_STATES.IDLE)
  const [error, setError] = useState(null)

  const pcRef = useRef(null)
  const dcRef = useRef(null)
  const audioRef = useRef(null)
  const micStreamRef = useRef(null)

  const isSpeaking = turnState === TURN_STATES.SPEAKING
  const isListening = turnState === TURN_STATES.LISTENING
  const isProcessing = turnState === TURN_STATES.PROCESSING

  const sendEvent = useCallback((event) => {
    const dc = dcRef.current
    if (dc && dc.readyState === 'open') {
      dc.send(JSON.stringify(event))
    }
  }, [])

  const muteMic = useCallback(() => {
    micStreamRef.current?.getAudioTracks().forEach(t => { t.enabled = false })
  }, [])

  const unmuteMic = useCallback(() => {
    micStreamRef.current?.getAudioTracks().forEach(t => { t.enabled = true })
  }, [])

  const handleDataChannelMessage = useCallback((event) => {
    let data
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }

    switch (data.type) {
      case 'conversation.item.input_audio_transcription.completed': {
        const text = data.transcript?.trim()
        if (text) {
          muteMic()
          setTurnState(TURN_STATES.PROCESSING)
          onTranscript?.(text)
        }
        break
      }

      case 'response.output_audio.delta':
        setTurnState(TURN_STATES.SPEAKING)
        break

      case 'response.output_audio.done':
        break

      case 'response.done':
        setTurnState(TURN_STATES.IDLE)
        unmuteMic()
        break

      case 'error':
        setError(data.error?.message || 'Realtime API error')
        onError?.(data.error?.message || 'Realtime API error')
        break

      default:
        break
    }
  }, [onTranscript, onError, muteMic, unmuteMic])

  const connect = useCallback(async (ephemeralToken, { voice, voiceInstructions } = {}) => {
    try {
      setError(null)

      const pc = new RTCPeerConnection()
      pcRef.current = pc

      const audioEl = document.createElement('audio')
      audioEl.autoplay = true
      audioRef.current = audioEl

      pc.ontrack = (event) => {
        audioEl.srcObject = event.streams[0]
      }

      let micStream
      try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      } catch (err) {
        if (err.name === 'NotAllowedError') {
          throw new Error('Microphone access denied. Please allow mic access in browser settings.')
        } else if (err.name === 'NotFoundError') {
          throw new Error('No microphone found. Please connect a microphone.')
        }
        throw new Error(`Microphone error: ${err.message}`)
      }
      micStreamRef.current = micStream
      const audioTrack = micStream.getAudioTracks()[0]
      if (!audioTrack) {
        throw new Error('No audio track available from microphone')
      }
      pc.addTrack(audioTrack, micStream)

      const dc = pc.createDataChannel('oai-events')
      dcRef.current = dc

      dc.onopen = () => {
        dc.send(JSON.stringify({
          type: 'session.update',
          session: {
            type: 'realtime',
            instructions: voiceInstructions || '',
            output_modalities: ['audio'],
            audio: {
              input: {
                transcription: {
                  model: 'gpt-4o-mini-transcribe',
                },
                turn_detection: {
                  type: 'semantic_vad',
                },
              },
              output: {
                voice: voice || 'ash',
              },
            },
          },
        }))
        setIsConnected(true)
        setTurnState(TURN_STATES.LISTENING)
      }

      dc.onmessage = handleDataChannelMessage

      dc.onclose = () => {
        setIsConnected(false)
        setTurnState(TURN_STATES.IDLE)
      }

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          setError('Voice connection lost. Try reconnecting.')
          setIsConnected(false)
          setTurnState(TURN_STATES.IDLE)
          onError?.('Voice connection lost')
        }
      }

      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)

      const sdpResponse = await fetch(REALTIME_URL, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${ephemeralToken}`,
          'Content-Type': 'application/sdp',
        },
        body: offer.sdp,
      })

      if (!sdpResponse.ok) {
        const body = await sdpResponse.text().catch(() => '')
        let detail = ''
        try { detail = JSON.parse(body)?.error?.message || body } catch { detail = body }
        throw new Error(`WebRTC handshake failed (${sdpResponse.status}): ${detail}`)
      }

      const answerSdp = await sdpResponse.text()
      await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp })

    } catch (err) {
      setError(err.message)
      onError?.(err.message)
      disconnect()
      throw err
    }
  }, [handleDataChannelMessage, onError])

  const disconnect = useCallback(() => {
    micStreamRef.current?.getTracks().forEach(t => t.stop())
    micStreamRef.current = null

    dcRef.current?.close()
    dcRef.current = null

    pcRef.current?.close()
    pcRef.current = null

    audioRef.current?.remove()
    audioRef.current = null

    setIsConnected(false)
    setTurnState(TURN_STATES.IDLE)
    setError(null)
  }, [])

  const injectResponse = useCallback((text, voiceInstructions) => {
    if (!dcRef.current || dcRef.current.readyState !== 'open') return

    if (voiceInstructions) {
      sendEvent({
        type: 'session.update',
        session: { type: 'realtime', instructions: voiceInstructions },
      })
    }

    sendEvent({
      type: 'conversation.item.create',
      item: {
        type: 'message',
        role: 'user',
        content: [{
          type: 'input_text',
          text: text,
        }],
      },
    })

    sendEvent({
      type: 'response.create',
      response: {
        output_modalities: ['audio'],
      },
    })

    muteMic()
    setTurnState(TURN_STATES.SPEAKING)
  }, [sendEvent, muteMic])

  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return {
    isConnected,
    isSpeaking,
    isListening,
    isProcessing,
    turnState,
    error,
    connect,
    disconnect,
    injectResponse,
    muteMic,
    unmuteMic,
    sendEvent,
  }
}
