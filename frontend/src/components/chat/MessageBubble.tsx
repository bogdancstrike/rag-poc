import { useMemo } from 'react'
import { Typography, Tag, Space, theme, Button, Tooltip, Progress, Collapse, Avatar } from 'antd'
import { LinkOutlined, CalendarOutlined, TagOutlined, RobotOutlined, UserOutlined, InfoCircleOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useNavigate } from 'react-router-dom'
import type { Message, Source } from '@/types'

const { Text } = Typography

interface Props {
  message: Message & { streaming?: boolean }
}

/** Replace [#1] or [doc:ID] citations with styled inline markers. */
function CitedContent({ content, sources }: { content: string; sources: Source[] }) {
  const { token } = theme.useToken()

  // Build a lookup: id → rank (for old [doc:ID] citations)
  const rankMap = useMemo(
    () => Object.fromEntries(sources.map((s, i) => [s.id, i + 1])),
    [sources],
  )

  // Split on [#N] or [doc:ID] patterns
  const parts = useMemo(() => {
    const regex = /\[(?:#(\d+)|doc:([^\]"]+?)(?:\s+"[^"]*")?)\]/g
    const result: Array<{ type: 'text' | 'cite'; value: string; rank?: string | number }> = []
    let last = 0
    let m: RegExpExecArray | null
    
    while ((m = regex.exec(content)) !== null) {
      if (m.index > last) result.push({ type: 'text', value: content.slice(last, m.index) })
      
      const numericRank = m[1]
      const docId = m[2]
      
      if (numericRank) {
        result.push({ type: 'cite', value: m[0], rank: numericRank })
      } else if (docId) {
        result.push({ type: 'cite', value: m[0], rank: rankMap[docId.trim()] || docId })
      }
      
      last = m.index + m[0].length
    }
    if (last < content.length) result.push({ type: 'text', value: content.slice(last) })
    return result
  }, [content, rankMap])

  // If no citations found, render plain markdown
  const hasCitations = parts.some((p) => p.type === 'cite')
  if (!hasCitations) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents(token)}>
        {content}
      </ReactMarkdown>
    )
  }

  return (
    <div className="cited-content">
      {parts.map((p, i) =>
        p.type === 'cite' ? (
          <Tooltip key={i} title={`Source #${p.rank}`} mouseEnterDelay={0.5}>
            <Tag
              color="blue"
              style={{
                fontSize: 10,
                padding: '0 4px',
                lineHeight: '14px',
                margin: '0 2px',
                verticalAlign: 'super',
                cursor: 'pointer',
                borderRadius: 4,
                fontWeight: 600,
              }}
            >
              #{p.rank}
            </Tag>
          </Tooltip>
        ) : (
          <ReactMarkdown key={i} remarkPlugins={[remarkGfm]} components={mdComponents(token)}>
            {p.value}
          </ReactMarkdown>
        ),
      )}
    </div>
  )
}

function mdComponents(token: any) {
  return {
    p: ({ children }: any) => (
      <p style={{ margin: '0 0 12px', fontSize: 14, lineHeight: 1.6, color: 'inherit' }}>{children}</p>
    ),
    ul: ({ children }: any) => (
      <ul style={{ paddingLeft: 20, margin: '8px 0 12px' }}>{children}</ul>
    ),
    ol: ({ children }: any) => (
      <ol style={{ paddingLeft: 20, margin: '8px 0 12px' }}>{children}</ol>
    ),
    li: ({ children }: any) => (
      <li style={{ marginBottom: 4, fontSize: 14 }}>{children}</li>
    ),
    strong: ({ children }: any) => (
      <strong style={{ fontWeight: 600, color: token.colorPrimaryActive }}>{children}</strong>
    ),
    code: ({ children }: any) => (
      <code style={{
        background:   token.colorFillTertiary,
        padding:      '2px 6px',
        borderRadius: 4,
        fontSize:     '0.9em',
        fontFamily:   'monospace',
      }}>
        {children}
      </code>
    ),
    h1: ({ children }: any) => <h1 style={{ fontSize: 20, margin: '16px 0 8px' }}>{children}</h1>,
    h2: ({ children }: any) => <h2 style={{ fontSize: 18, margin: '14px 0 8px' }}>{children}</h2>,
    h3: ({ children }: any) => <h3 style={{ fontSize: 16, margin: '12px 0 6px' }}>{children}</h3>,
    table: ({ children }: any) => (
      <div style={{ overflowX: 'auto', marginBottom: 16, borderRadius: 8, border: `1px solid ${token.colorBorderSecondary}` }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>{children}</table>
      </div>
    ),
    thead: ({ children }: any) => <thead style={{ background: token.colorFillAlter }}>{children}</thead>,
    th: ({ children }: any) => (
      <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: `2px solid ${token.colorBorderSecondary}`, fontWeight: 600 }}>{children}</th>
    ),
    td: ({ children }: any) => (
      <td style={{ padding: '8px 12px', borderBottom: `1px solid ${token.colorBorderSecondary}` }}>{children}</td>
    ),
    blockquote: ({ children }: any) => (
      <blockquote style={{ 
        margin: '0 0 12px', 
        paddingLeft: 16, 
        borderLeft: `4px solid ${token.colorBorder}`,
        color: token.colorTextDescription,
        fontStyle: 'italic'
      }}>
        {children}
      </blockquote>
    ),
  }
}

function scoreColor(score: number, token: any) {
  if (score >= 0.75) return token.colorSuccess
  if (score >= 0.45) return token.colorWarning
  return token.colorError
}

function SourceCard({ src, fallbackRank, navigate }: { src: Source; fallbackRank: number; navigate: (url: string) => void }) {
  const { token } = theme.useToken()
  const score  = src.score ?? 0
  const color  = scoreColor(score, token)
  const canNav = !!(src.datasource && src.id)
  const rankLabel = src.index || `#${fallbackRank}`

  const navUrl = canNav
    ? `/explore?doc=${encodeURIComponent(src.id)}&idx=${encodeURIComponent(src.datasource!)}`
    : null

  return (
    <div
      style={{
        borderLeft:   `3px solid ${color}`,
        background:   token.colorBgElevated,
        borderRadius: `0 ${token.borderRadius}px ${token.borderRadius}px 0`,
        padding:      '10px 14px',
        fontSize:     12,
        boxShadow:    '0 1px 2px rgba(0,0,0,0.03)',
        transition:   'all 0.2s',
        marginBottom: 4
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
        <Space size={6} wrap style={{ flex: 1 }}>
          <Tag color="blue" style={{ fontSize: 11, margin: 0, fontWeight: 600 }}>
            {rankLabel}
          </Tag>
          {src.title ? (
            <Text strong style={{ fontSize: 13, color: token.colorTextHeading }}>{src.title}</Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12, fontFamily: 'monospace' }}>
              {src.id.slice(0, 16)}…
            </Text>
          )}
        </Space>
        <Space size={4}>
          <Tooltip title={`Relevance: ${(score * 100).toFixed(0)}%`}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
               <div style={{ width: 40, height: 4, background: token.colorFillTertiary, borderRadius: 2 }}>
                  <div style={{ width: `${score * 100}%`, height: '100%', background: color, borderRadius: 2 }} />
               </div>
               <Text style={{ fontSize: 10, color: token.colorTextDescription }}>{(score * 100).toFixed(0)}%</Text>
            </div>
          </Tooltip>
          {navUrl && (
            <Button
              size="small"
              type="text"
              icon={<LinkOutlined />}
              style={{ height: 24, width: 24, fontSize: 12 }}
              onClick={() => navigate(navUrl)}
            />
          )}
        </Space>
      </div>

      {(src.date || src.classification || src.sentiment) && (
        <Space size={4} wrap style={{ marginBottom: 8 }}>
          {src.date && (
            <Tag icon={<CalendarOutlined />} style={{ fontSize: 10, margin: 0 }}>
              {src.date}
            </Tag>
          )}
          {src.classification && (
            <Tag icon={<TagOutlined />} style={{ fontSize: 10, margin: 0 }}>
              {src.classification}
            </Tag>
          )}
          {src.sentiment && (
            <Tag
              color={
                src.sentiment === 'positive' || src.sentiment === 'supportive' ? 'success'
                  : src.sentiment === 'negative' || src.sentiment === 'hostile' ? 'error'
                  : 'default'
              }
              style={{ fontSize: 10, margin: 0 }}
            >
              {src.sentiment}
            </Tag>
          )}
        </Space>
      )}

      {src.text && (
        <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.6, display: 'block', fontStyle: 'italic' }}>
          "{src.text.slice(0, 300)}{(src.text.length ?? 0) > 300 ? '…' : ''}"
        </Text>
      )}
    </div>
  )
}

export function MessageBubble({ message }: Props) {
  const { token }  = theme.useToken()
  const navigate   = useNavigate()
  const isUser     = message.role === 'user'
  const sources    = (message.sources ?? []) as Source[]

  const containerStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: isUser ? 'row-reverse' : 'row',
    gap: 12,
    width: '100%',
    padding: '4px 0',
  }

  const bubbleStyle: React.CSSProperties = {
    maxWidth:     'calc(100% - 48px)',
    padding:      '12px 16px',
    borderRadius: isUser 
        ? `${token.borderRadiusLG}px 4px ${token.borderRadiusLG}px ${token.borderRadiusLG}px`
        : `4px ${token.borderRadiusLG}px ${token.borderRadiusLG}px ${token.borderRadiusLG}px`,
    fontSize:     14,
    lineHeight:   1.6,
    boxShadow:    isUser ? 'none' : '0 1px 2px rgba(0,0,0,0.05)',
    ...(isUser
      ? {
          background: token.colorPrimary,
          color:      '#fff',
        }
      : {
          background: token.colorBgContainer,
          border:     `1px solid ${token.colorBorderSecondary}`,
          color:      token.colorText,
        }),
  }

  return (
    <div style={containerStyle}>
      <Avatar 
        size="small" 
        icon={isUser ? <UserOutlined /> : <RobotOutlined />}
        style={{ 
            backgroundColor: isUser ? token.colorPrimary : token.colorInfo,
            flexShrink: 0,
            marginTop: 4
        }} 
      />
      
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, maxWidth: '85%' }}>
        <div style={bubbleStyle}>
          {isUser ? (
            <Text style={{ color: '#fff', fontSize: 14, whiteSpace: 'pre-wrap' }}>
              {message.content}
            </Text>
          ) : (
            <div style={{ position: 'relative' }}>
              <CitedContent content={message.content} sources={sources} />
              {message.streaming && (
                <span
                  style={{
                    display:     'inline-block',
                    width:       8,
                    height:      15,
                    background:  token.colorPrimary,
                    borderRadius: 2,
                    animation:   'blink 1s step-end infinite',
                    verticalAlign: 'middle',
                    marginLeft: 4,
                    opacity: 0.7
                  }}
                />
              )}
            </div>
          )}
        </div>

        {!isUser && sources.length > 0 && (
          <div style={{ marginTop: 4 }}>
            <Collapse
              ghost
              size="small"
              expandIconPlacement="end"
              style={{ background: 'transparent' }}
              items={[{
                key: '1',
                label: (
                  <Space size={6}>
                    <InfoCircleOutlined style={{ fontSize: 12, color: token.colorTextTertiary }} />
                    <Text style={{ fontSize: 12, color: token.colorTextTertiary, fontWeight: 500 }}>
                      {sources.length} intelligence source{sources.length > 1 ? 's' : ''} cited
                    </Text>
                  </Space>
                ),
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 4 }}>
                    {sources.map((src, i) => (
                      <SourceCard key={src.id} src={src} fallbackRank={i + 1} navigate={navigate} />
                    ))}
                  </div>
                ),
              }]}
            />
          </div>
        )}

        {!isUser && !message.streaming && sources.length === 0 && message.content && (
          <Text style={{ fontSize: 12, color: token.colorTextQuaternary, fontStyle: 'italic', paddingLeft: 4 }}>
            No classified documents retrieved for this query.
          </Text>
        )}
      </div>
    </div>
  )
}
