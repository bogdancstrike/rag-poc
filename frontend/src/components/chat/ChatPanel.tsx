import { useEffect, useRef, useState } from 'react'
import { Layout, Input, Button, Typography, Space, theme, Empty, Spin } from 'antd'
import { SendOutlined, StopOutlined } from '@ant-design/icons'
import { useSessionStore } from '@/stores/sessionStore'
import { useChat } from '@/hooks/useChat'
import { useMessages } from '@/hooks/useSessions'
import { SessionSidebar } from './SessionSidebar'
import { MessageBubble } from './MessageBubble'
import type { Message } from '@/types'

const { Content } = Layout
const { Text } = Typography

interface Props {
  datasource?: string
  /** Query pre-set by InsightsPanel "Ask about this" CTA */
  prefillQuery?: string | null
  onPrefillConsumed?: () => void
}

/**
 * ChatPanel — full RAG chat with streaming, session management, and source citations.
 *
 * Layout:
 *   SessionSidebar (left) | message list + input box (right)
 */
export function ChatPanel({ datasource, prefillQuery, onPrefillConsumed }: Props) {
  const { token }    = theme.useToken()
  const { sendMessage, isStreaming, cancel } = useChat()
  const { activeSessionId, messages, streaming, pendingQuery, setPendingQuery } = useSessionStore()

  const [input, setInput]         = useState('')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const bottomRef                 = useRef<HTMLDivElement>(null)

  // Load messages when session changes
  const { data: fetchedMsgs, isLoading } = useMessages(activeSessionId)
  const setMessages = useSessionStore((s) => s.setMessages)
  useEffect(() => {
    if (fetchedMsgs) setMessages(fetchedMsgs)
  }, [fetchedMsgs])

  // Pre-fill from InsightsPanel "Ask about this" or from pendingQuery store
  useEffect(() => {
    const q = prefillQuery || pendingQuery
    if (q) {
      setInput(q)
      if (prefillQuery) onPrefillConsumed?.()
      if (pendingQuery) setPendingQuery(null)
    }
  }, [prefillQuery, pendingQuery])

  // Scroll to bottom when new messages arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming])

  const handleSend = () => {
    const q = input.trim()
    if (!q) return
    setInput('')
    sendMessage(q)
  }

  // Combine persisted messages + the in-progress streaming message
  const allMessages: (Message & { streaming?: boolean })[] = [
    ...messages,
    ...(streaming
      ? [{
          id:         streaming.id,
          session_id: activeSessionId ?? '',
          role:       'assistant' as const,
          content:    streaming.content,
          sources:    streaming.sources,
          created_at: streaming.created_at,
          streaming:  true,
        }]
      : []),
  ]

  return (
    <Layout style={{ height: '100%', minHeight: 0, background: 'transparent' }}>
      <SessionSidebar datasource={datasource} collapsed={sidebarCollapsed} />

      <Layout style={{ background: 'transparent', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Messages area */}
        <Content
          style={{
            flex:      1,
            overflowY: 'auto',
            padding:   '16px',
            display:   'flex',
            flexDirection: 'column',
            gap:       12,
          }}
        >
          {isLoading && <Spin style={{ alignSelf: 'center', marginTop: 40 }} />}

          {!isLoading && allMessages.length === 0 && (
            <Empty
              style={{ marginTop: 60 }}
              description={
                <Text style={{ color: token.colorTextDescription }}>
                  {activeSessionId
                    ? 'No messages yet — ask a question to begin.'
                    : 'Select or create a session from the sidebar to start chatting.'}
                </Text>
              }
            />
          )}

          {allMessages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={bottomRef} />
        </Content>

        {/* Input box */}
        <div
          style={{
            padding:    '12px 16px',
            borderTop:  `1px solid ${token.colorBorderSecondary}`,
            background: token.colorBgContainer,
            flexShrink: 0,
          }}
        >
          <Space.Compact style={{ width: '100%' }}>
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => { if (!e.shiftKey) handleSend() }}
              placeholder={
                activeSessionId
                  ? 'Ask about the data… (Enter to send)'
                  : 'Create or select a session first'
              }
              disabled={!activeSessionId || isStreaming}
              style={{ fontSize: 13 }}
              autoComplete="off"
            />
            {isStreaming ? (
              <Button
                type="default"
                icon={<StopOutlined />}
                onClick={cancel}
                style={{ flexShrink: 0 }}
              >
                Stop
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handleSend}
                disabled={!activeSessionId || !input.trim()}
                style={{ flexShrink: 0 }}
              >
                Send
              </Button>
            )}
          </Space.Compact>

          {isStreaming && (
            <Text style={{ fontSize: 11, color: token.colorTextDescription, marginTop: 4, display: 'block' }}>
              Generating response…
            </Text>
          )}
        </div>
      </Layout>
    </Layout>
  )
}
