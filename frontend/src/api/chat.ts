import { API_BASE } from './client'
import type { SseEvent, Source } from '@/types'

export interface ChatStreamCallbacks {
  onSources:  (sources: Source[], sessionId: string) => void
  onDelta:    (delta: string) => void
  onDone:     (messageId: string, sessionId: string) => void
  onError:    (error: string) => void
}

/**
 * Stream a chat message via SSE (POST /v1/chat/stream).
 * Uses fetch + ReadableStream so POST body is supported (EventSource only supports GET).
 *
 * Returns an AbortController so the caller can cancel mid-stream.
 */
export function streamChat(
  message: string,
  sessionId: string | null,
  callbacks: ChatStreamCallbacks,
): AbortController {
  const controller = new AbortController()

  const run = async () => {
    let response: Response
    try {
      response = await fetch(`${API_BASE}/v1/chat/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ message, session_id: sessionId }),
        signal:  controller.signal,
      })
    } catch (err: any) {
      if (err.name !== 'AbortError') callbacks.onError(err.message)
      return
    }

    if (!response.ok || !response.body) {
      callbacks.onError(`HTTP ${response.status}`)
      return
    }

    const reader  = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer    = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // SSE lines are separated by \n\n; each line starts with "data: "
        const events = buffer.split('\n\n')
        buffer = events.pop() ?? ''   // keep incomplete tail

        for (const event of events) {
          const line = event.trim()
          if (!line.startsWith('data:')) continue
          const json = line.slice(5).trim()
          if (!json) continue
          try {
            const parsed: SseEvent = JSON.parse(json)
            if (parsed.type === 'sources') callbacks.onSources(parsed.sources, parsed.session_id)
            else if (parsed.type === 'delta')   callbacks.onDelta(parsed.content)
            else if (parsed.type === 'done')    callbacks.onDone(parsed.message_id, parsed.session_id)
            else if (parsed.type === 'error')   callbacks.onError(parsed.content)
          } catch {
            // malformed JSON — skip
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') callbacks.onError(err.message)
    }
  }

  run()
  return controller
}
