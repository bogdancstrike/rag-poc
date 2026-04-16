import { useEffect, useRef, useState } from 'react'
import { Layout, Input, Button, Typography, Space, theme, Spin, Avatar, Tag } from 'antd'
import { SendOutlined, StopOutlined, PlusOutlined, RobotOutlined } from '@ant-design/icons'
import { useSessionStore } from '@/stores/sessionStore'
import { useChat } from '@/hooks/useChat'
import { useMessages } from '@/hooks/useSessions'
import { SessionSidebar } from './SessionSidebar'
import { MessageBubble } from './MessageBubble'
import { PageHeader } from '../common/PageHeader'
import type { Message } from '@/types'

const { Content } = Layout
const { Text, Title } = Typography
const { TextArea } = Input

interface Props {
  datasource?: string
  /** Query pre-set by InsightsPanel "Ask about this" CTA */
  prefillQuery?: string | null
  onPrefillConsumed?: () => void
}

/**
 * ChatPanel — full RAG chat with streaming, session management, and source citations.
 */
export function ChatPanel({ datasource, prefillQuery, onPrefillConsumed }: Props) {
  const { token }    = theme.useToken()
  const { sendMessage, isStreaming, cancel } = useChat()
  const { activeSessionId, messages, streaming, pendingQuery, setPendingQuery, setActiveSession } = useSessionStore()

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
    // Small delay to ensure rendering is complete
    const timer = setTimeout(() => {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, 100)
    return () => clearTimeout(timer)
  }, [messages, streaming])

  const handleSend = () => {
    const q = input.trim()
    if (!q || isStreaming) return
    setInput('')
    sendMessage(q)
  }

  const handleNewChat = () => {
    setActiveSession(null)
    setInput('')
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
    <Layout style={{ height: '100%', minHeight: 0, background: token.colorBgLayout }}>
      <SessionSidebar datasource={datasource} collapsed={sidebarCollapsed} />

      <Layout style={{ background: 'transparent', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '0 20px', background: token.colorBgContainer }}>
          <PageHeader 
            title="Intelligence Assistant" 
            icon={<RobotOutlined />}
            info="Uses hybrid RAG (Semantic + Keyword) to synthesize answers from the intelligence corpus. Every claim is cited with source documents."
            extra={
              activeSessionId ? (
                <Tag color="processing" style={{ margin: 0, fontSize: 10, borderRadius: 4 }}>
                  ACTIVE SESSION
                </Tag>
              ) : null
            }
          />
        </div>

        {/* Messages area */}
        <Content
          style={{
            flex:      1,
            overflowY: 'auto',
            padding:   '24px 20px',
            display:   'flex',
            flexDirection: 'column',
            gap:       20,
            maxWidth:  1000,
            width:     '100%',
            margin:    '0 auto',
          }}
        >
          {isLoading && <Spin style={{ alignSelf: 'center', marginTop: 40 }} />}

          {!isLoading && allMessages.length === 0 && (
            <div style={{ 
                display: 'flex', 
                flexDirection: 'column', 
                alignItems: 'center', 
                justifyContent: 'center',
                height: '70%',
                opacity: 0.8
            }}>
              <RobotOutlined style={{ fontSize: 48, color: token.colorPrimary, marginBottom: 20 }} />
              <Title level={4} style={{ margin: '0 0 8px' }}>How can I assist your investigation?</Title>
              <Text type="secondary" style={{ textAlign: 'center', maxWidth: 400 }}>
                Ask questions about the current intelligence corpus. I can help synthesize narratives, 
                identify key actors, and track emerging signals.
              </Text>
            </div>
          )}

          {allMessages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={bottomRef} style={{ height: 1 }} />
        </Content>

        {/* Improved Input area */}
        <div
          style={{
            padding:    '16px 20px 24px',
            background: 'transparent',
            maxWidth:   1000,
            width:      '100%',
            margin:     '0 auto',
            flexShrink: 0,
          }}
        >
          <div style={{
            background: token.colorBgContainer,
            border: `1px solid ${token.colorBorder}`,
            borderRadius: 12,
            padding: '8px 12px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.05)',
            display: 'flex',
            flexDirection: 'column',
            gap: 4
          }}>
            <TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => { 
                if (!e.shiftKey) {
                  e.preventDefault()
                  handleSend() 
                }
              }}
              placeholder={
                activeSessionId
                  ? 'Ask about the data… (Shift+Enter for new line)'
                  : 'Create a new investigation to start chatting'
              }
              disabled={isStreaming}
              variant="borderless"
              autoSize={{ minRows: 1, maxRows: 6 }}
              style={{ padding: '4px 0', fontSize: 14 }}
            />
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text style={{ fontSize: 11, color: token.colorTextQuaternary }}>
                {isStreaming ? 'Synthesizing intelligence...' : 'Press Enter to send'}
              </Text>
              
              {isStreaming ? (
                <Button
                  type="text"
                  danger
                  icon={<StopOutlined />}
                  onClick={cancel}
                  size="small"
                >
                  Stop
                </Button>
              ) : (
                <Button
                  type="primary"
                  shape="circle"
                  icon={<SendOutlined style={{ fontSize: 12 }} />}
                  onClick={handleSend}
                  disabled={!input.trim()}
                  size="small"
                />
              )}
            </div>
          </div>
          
          <Text style={{ fontSize: 10, color: token.colorTextQuaternary, marginTop: 8, display: 'block', textAlign: 'center' }}>
            AI-generated content may require human verification. Sources are provided for every claim.
          </Text>
        </div>
      </Layout>
    </Layout>
  )
}
