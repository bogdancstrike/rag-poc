import { create } from 'zustand'
import type { Message, Source } from '@/types'

interface StreamingMessage {
  id: string         // temporary optimistic ID
  role: 'assistant'
  content: string    // accumulated delta text
  sources: Source[]
  streaming: boolean
  created_at: string
}

interface SessionStore {
  activeSessionId: string | null
  messages: Message[]
  streaming: StreamingMessage | null
  pendingQuery: string | null   // pre-populated from InsightsPanel "Ask about this"

  setActiveSession:   (id: string | null) => void
  setMessages:        (msgs: Message[]) => void
  appendMessage:      (msg: Message) => void
  startStreaming:     (sources: Source[], sessionId: string) => void
  appendDelta:        (delta: string) => void
  finishStreaming:    (messageId: string, sessionId: string) => void
  clearStreaming:     () => void
  setPendingQuery:    (q: string | null) => void
}

export const useSessionStore = create<SessionStore>((set, get) => ({
  activeSessionId: null,
  messages:        [],
  streaming:       null,
  pendingQuery:    null,

  setActiveSession: (id) => set({ activeSessionId: id, messages: [], streaming: null }),

  setMessages: (msgs) => set({ messages: msgs }),

  appendMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),

  /** Called when the SSE 'sources' event arrives — starts optimistic streaming message */
  startStreaming: (sources, sessionId) => {
    set({
      activeSessionId: sessionId,
      streaming: {
        id:         `streaming-${Date.now()}`,
        role:       'assistant',
        content:    '',
        sources,
        streaming:  true,
        created_at: new Date().toISOString(),
      },
    })
  },

  /** Accumulate each text delta */
  appendDelta: (delta) =>
    set((s) => {
      if (!s.streaming) return s
      return { streaming: { ...s.streaming, content: s.streaming.content + delta } }
    }),

  /** SSE 'done' — replace streaming placeholder with a real Message */
  finishStreaming: (messageId, sessionId) => {
    const { streaming, messages } = get()
    if (!streaming) return
    const finalMsg: Message = {
      id:         messageId,
      session_id: sessionId,
      role:       'assistant',
      content:    streaming.content,
      sources:    streaming.sources,
      created_at: streaming.created_at,
    }
    set({ messages: [...messages, finalMsg], streaming: null, activeSessionId: sessionId })
  },

  clearStreaming: () => set({ streaming: null }),

  setPendingQuery: (q) => set({ pendingQuery: q }),
}))
