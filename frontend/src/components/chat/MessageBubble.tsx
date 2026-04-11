import { useMemo } from 'react'
import { Typography, Tag, Space, theme, Button, Tooltip, Progress, Collapse } from 'antd'
import { LinkOutlined, CalendarOutlined, TagOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { useNavigate } from 'react-router-dom'
import type { Message } from '@/types'

const { Text } = Typography

interface Source {
  id: string
  score: number
  text?: string
  title?: string
  date?: string
  datasource?: string
  classification?: string
  sentiment?: string
}

interface Props {
  message: Message & { streaming?: boolean }
}

/** Replace [doc:ID] or [doc:ID "Title"] citations with styled inline markers. */
function CitedContent({ content, sources }: { content: string; sources: Source[] }) {
  const { token } = theme.useToken()

  // Build a lookup: id → rank (1-based)
  const rankMap = useMemo(
    () => Object.fromEntries(sources.map((s, i) => [s.id, i + 1])),
    [sources],
  )

  // Split on [doc:ID] or [doc:ID "Title"] patterns
  const parts = useMemo(() => {
    const regex = /\[doc:([^\]"]+?)(?:\s+"[^"]*")?\]/g
    const result: Array<{ type: 'text' | 'cite'; value: string; docId?: string; rank?: number }> = []
    let last = 0
    let m: RegExpExecArray | null
    while ((m = regex.exec(content)) !== null) {
      if (m.index > last) result.push({ type: 'text', value: content.slice(last, m.index) })
      const docId = m[1].trim()
      result.push({ type: 'cite', value: m[0], docId, rank: rankMap[docId] })
      last = m.index + m[0].length
    }
    if (last < content.length) result.push({ type: 'text', value: content.slice(last) })
    return result
  }, [content, rankMap])

  // If no citations found, render plain markdown
  const hasCitations = parts.some((p) => p.type === 'cite')
  if (!hasCitations) {
    return (
      <ReactMarkdown components={mdComponents(token)}>
        {content}
      </ReactMarkdown>
    )
  }

  // Render text segments via markdown, citations as inline superscript badges
  return (
    <span>
      {parts.map((p, i) =>
        p.type === 'cite' ? (
          <Tooltip key={i} title={`Source ${p.rank ?? p.docId}`}>
            <Tag
              color="blue"
              style={{
                fontSize: 9,
                padding: '0 4px',
                lineHeight: '16px',
                margin: '0 1px',
                verticalAlign: 'super',
                cursor: 'default',
                borderRadius: 3,
              }}
            >
              [{p.rank ?? p.docId}]
            </Tag>
          </Tooltip>
        ) : (
          <ReactMarkdown key={i} components={mdComponents(token)}>
            {p.value}
          </ReactMarkdown>
        ),
      )}
    </span>
  )
}

function mdComponents(token: ReturnType<typeof theme.useToken>['token']) {
  return {
    p: ({ children }: any) => (
      <p style={{ margin: '0 0 8px', fontSize: 13, lineHeight: 1.65 }}>{children}</p>
    ),
    ul: ({ children }: any) => (
      <ul style={{ paddingLeft: 18, margin: '4px 0 8px' }}>{children}</ul>
    ),
    ol: ({ children }: any) => (
      <ol style={{ paddingLeft: 18, margin: '4px 0 8px' }}>{children}</ol>
    ),
    li: ({ children }: any) => (
      <li style={{ marginBottom: 2, fontSize: 13 }}>{children}</li>
    ),
    strong: ({ children }: any) => (
      <strong style={{ fontWeight: 600 }}>{children}</strong>
    ),
    code: ({ children }: any) => (
      <code style={{
        background:   token.colorFillTertiary,
        padding:      '1px 5px',
        borderRadius: 3,
        fontSize:     12,
        fontFamily:   'monospace',
      }}>
        {children}
      </code>
    ),
    h3: ({ children }: any) => (
      <h3 style={{ fontSize: 13, fontWeight: 600, margin: '12px 0 4px' }}>{children}</h3>
    ),
  }
}

function scoreColor(score: number, token: any) {
  if (score >= 0.75) return token.colorSuccess
  if (score >= 0.45) return token.colorWarning
  return token.colorError
}

function SourceCard({ src, rank, navigate }: { src: Source; rank: number; navigate: (url: string) => void }) {
  const { token } = theme.useToken()
  const score  = src.score ?? 0
  const color  = scoreColor(score, token)
  const canNav = !!(src.datasource && src.id)

  const navUrl = canNav
    ? `/explore?doc=${encodeURIComponent(src.id)}&idx=${encodeURIComponent(src.datasource!)}`
    : null

  return (
    <div
      style={{
        borderLeft:   `3px solid ${color}`,
        background:   token.colorFillAlter,
        borderRadius: `0 ${token.borderRadius}px ${token.borderRadius}px 0`,
        padding:      '8px 12px',
        fontSize:     12,
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
        <Space size={4} wrap style={{ flex: 1 }}>
          <Tag color="blue" style={{ fontSize: 10, margin: 0, flexShrink: 0 }}>
            #{rank}
          </Tag>
          {src.title ? (
            <Text strong style={{ fontSize: 12 }}>{src.title}</Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>
              {src.id.slice(0, 16)}…
            </Text>
          )}
        </Space>
        <Space size={4} style={{ flexShrink: 0 }}>
          <Tooltip title={`Relevance: ${(score * 100).toFixed(0)}% of best match`}>
            <Tag
              style={{ fontSize: 10, margin: 0 }}
              color={score >= 0.75 ? 'success' : score >= 0.45 ? 'warning' : 'error'}
            >
              {(score * 100).toFixed(0)}%
            </Tag>
          </Tooltip>
          {navUrl && (
            <Tooltip title="Open in Data Exploration">
              <Button
                size="small"
                type="text"
                icon={<LinkOutlined />}
                style={{ height: 20, padding: '0 4px', fontSize: 11 }}
                onClick={() => navigate(navUrl)}
              />
            </Tooltip>
          )}
        </Space>
      </div>

      {/* Relevance bar */}
      <Progress
        percent={Math.round(score * 100)}
        showInfo={false}
        size={[undefined, 2]}
        strokeColor={color}
        style={{ margin: '4px 0 6px' }}
      />

      {/* Metadata chips */}
      {(src.date || src.classification || src.sentiment) && (
        <Space size={4} wrap style={{ marginBottom: 6 }}>
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
                src.sentiment === 'positive' || src.sentiment === 'supportive' ? 'green'
                  : src.sentiment === 'negative' || src.sentiment === 'hostile' ? 'red'
                  : 'default'
              }
              style={{ fontSize: 10, margin: 0 }}
            >
              {src.sentiment}
            </Tag>
          )}
        </Space>
      )}

      {/* Text preview */}
      {src.text && (
        <Text type="secondary" style={{ fontSize: 11, lineHeight: 1.5, display: 'block' }}>
          {src.text.slice(0, 260)}{(src.text.length ?? 0) > 260 ? '…' : ''}
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

  const bubbleStyle: React.CSSProperties = {
    maxWidth:     '88%',
    padding:      '10px 14px',
    borderRadius: token.borderRadiusLG,
    fontSize:     13,
    lineHeight:   1.6,
    ...(isUser
      ? {
          background: token.colorPrimary,
          color:      '#fff',
          alignSelf:  'flex-end',
          marginLeft: 'auto',
        }
      : {
          background: token.colorBgContainer,
          border:     `1px solid ${token.colorBorderSecondary}`,
          alignSelf:  'flex-start',
        }),
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', gap: 6 }}>
      {/* Message bubble */}
      <div style={bubbleStyle}>
        {isUser ? (
          <Text style={{ color: '#fff', fontSize: 13, whiteSpace: 'pre-wrap' }}>
            {message.content}
          </Text>
        ) : (
          <div style={{ color: token.colorText }}>
            <CitedContent content={message.content} sources={sources} />
            {message.streaming && (
              <span
                style={{
                  display:     'inline-block',
                  width:       8,
                  height:      14,
                  background:  token.colorPrimary,
                  borderRadius: 2,
                  animation:   'blink 1s step-end infinite',
                  verticalAlign: 'middle',
                }}
              />
            )}
          </div>
        )}
      </div>

      {/* Sources panel — only for assistant messages with sources */}
      {!isUser && sources.length > 0 && (
        <div style={{ maxWidth: '88%' }}>
          {sources.length <= 3 ? (
            /* ≤ 3 sources: always visible */
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Text style={{ fontSize: 11, color: token.colorTextTertiary, marginBottom: 2 }}>
                {sources.length} source{sources.length > 1 ? 's' : ''} used
              </Text>
              {sources.map((src, i) => (
                <SourceCard key={src.id} src={src} rank={i + 1} navigate={navigate} />
              ))}
            </div>
          ) : (
            /* > 3 sources: collapsible */
            <Collapse
              ghost
              size="small"
              items={[{
                key: '1',
                label: (
                  <Text style={{ fontSize: 11, color: token.colorTextTertiary }}>
                    {sources.length} sources used — click to expand
                  </Text>
                ),
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {sources.map((src, i) => (
                      <SourceCard key={src.id} src={src} rank={i + 1} navigate={navigate} />
                    ))}
                  </div>
                ),
              }]}
            />
          )}
        </div>
      )}

      {/* "No sources" hint when LLM responded but retrieval found nothing */}
      {!isUser && !message.streaming && sources.length === 0 && message.content && (
        <Text style={{ fontSize: 11, color: token.colorTextQuaternary, maxWidth: '88%' }}>
          No documents retrieved for this query
        </Text>
      )}
    </div>
  )
}
