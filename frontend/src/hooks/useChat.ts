import { useRef, useCallback } from 'react'
import { streamChat } from '@/api/chat'
import { useSessionStore } from '@/stores/sessionStore'

/**
 * useChat — manages sending a message and consuming the SSE stream.
 *
 * Returns sendMessage(query) and isStreaming state.
 * Delegates all state mutations to sessionStore.
 */
export function useChat() {
  const abortRef = useRef<AbortController | null>(null)
  const {
    activeSessionId,
    streaming,
    appendMessage,
    startStreaming,
    appendDelta,
    finishStreaming,
    clearStreaming,
  } = useSessionStore()

  const isStreaming = streaming !== null

  const sendMessage = useCallback(
    (query: string) => {
      if (!query.trim() || isStreaming) return

      // Cancel any in-flight stream
      abortRef.current?.abort()

      // Optimistically add the user message to the local list
      appendMessage({
        id:         `user-${Date.now()}`,
        session_id: activeSessionId ?? '',
        role:       'user',
        content:    query,
        sources:    null,
        created_at: new Date().toISOString(),
      })

      abortRef.current = streamChat(query, activeSessionId, {
        onSources:  (sources, sessionId) => startStreaming(sources, sessionId),
        onDelta:    (delta)              => appendDelta(delta),
        onDone:     (msgId, sessionId)   => finishStreaming(msgId, sessionId),
        onError:    (err)               => {
          clearStreaming()
          appendMessage({
            id:         `err-${Date.now()}`,
            session_id: activeSessionId ?? '',
            role:       'assistant',
            content:    `Error: ${err}`,
            sources:    null,
            created_at: new Date().toISOString(),
          })
        },
      })
    },
    [activeSessionId, isStreaming, appendMessage, startStreaming, appendDelta, finishStreaming, clearStreaming],
  )

  const cancel = useCallback(() => {
    abortRef.current?.abort()
    clearStreaming()
  }, [clearStreaming])

  return { sendMessage, isStreaming, cancel }
}
