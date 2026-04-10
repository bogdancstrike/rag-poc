import { Typography, Collapse, Tag, Space, theme, Button, Tooltip, Progress } from 'antd'
import { LinkOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { useNavigate } from 'react-router-dom'
import type { Message } from '@/types'

const { Text } = Typography

interface Props {
  message: Message & { streaming?: boolean }
}

/**
 * Renders a single chat message with markdown support and collapsible sources.
 */
export function MessageBubble({ message }: Props) {
  const { token } = theme.useToken()
  const navigate  = useNavigate()
  const isUser = message.role === 'user'

  const bubbleStyle: React.CSSProperties = {
    maxWidth:     '85%',
    padding:      '10px 14px',
    borderRadius: token.borderRadiusLG,
    fontSize:     13,
    lineHeight:   1.6,
    position:     'relative',
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
        }
    ),
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
      <div style={bubbleStyle}>
        {isUser ? (
          <Text style={{ color: '#fff', fontSize: 13, whiteSpace: 'pre-wrap' }}>
            {message.content}
          </Text>
        ) : (
          <div style={{ color: token.colorText }}>
            <ReactMarkdown
              components={{
                p: ({ children }) => (
                  <p style={{ margin: '0 0 8px', fontSize: 13, lineHeight: 1.6 }}>{children}</p>
                ),
                ul: ({ children }) => (
                  <ul style={{ paddingLeft: 20, margin: '4px 0' }}>{children}</ul>
                ),
                code: ({ children }) => (
                  <code style={{
                    background:   token.colorFillTertiary,
                    padding:      '1px 4px',
                    borderRadius: 3,
                    fontSize:     12,
                    fontFamily:   'monospace',
                  }}>{children}</code>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
            {message.streaming && (
              <span style={{ display: 'inline-block', width: 8, height: 14,
                background: token.colorPrimary, borderRadius: 2,
                animation: 'blink 1s step-end infinite', verticalAlign: 'middle' }} />
            )}
          </div>
        )}
      </div>

      {/* Sources — only for assistant messages */}
      {!isUser && message.sources && message.sources.length > 0 && (
        <div style={{ maxWidth: '85%', marginTop: 4 }}>
          <Collapse
            ghost
            size="small"
            items={[{
              key: '1',
              label: (
                <Text style={{ fontSize: 11, color: token.colorTextDescription }}>
                  {message.sources.length} source{message.sources.length > 1 ? 's' : ''} retrieved
                </Text>
              ),
              children: (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {message.sources.map((src, i) => {
                    const score    = src.score ?? 0
                    const scoreColor = score >= 0.6 ? token.colorSuccess
                      : score >= 0.3 ? token.colorWarning
                      : token.colorError
                    const datasource = src.datasource || ''
                    const docId      = src.id || ''
                    const canNavigate = !!(datasource && docId)
                    return (
                      <div
                        key={i}
                        style={{
                          padding:      '8px 10px',
                          background:   token.colorFillTertiary,
                          borderRadius: token.borderRadius,
                          fontSize:     11,
                          borderLeft:   `3px solid ${scoreColor}`,
                        }}
                      >
                        <Space style={{ width: '100%', justifyContent: 'space-between' }} align="start">
                          <Space size={6} wrap>
                            <Tag style={{ fontSize: 10, margin: 0 }} color="blue">
                              #{i + 1}
                            </Tag>
                            {src.title && (
                              <Text strong style={{ fontSize: 11 }}>{src.title}</Text>
                            )}
                            <Tooltip title={`Relevance score: ${score.toFixed(4)}`}>
                              <Tag
                                style={{ fontSize: 10, margin: 0 }}
                                color={score >= 0.6 ? 'success' : score >= 0.3 ? 'warning' : 'error'}
                              >
                                {(score * 100).toFixed(1)}%
                              </Tag>
                            </Tooltip>
                          </Space>
                          {canNavigate && (
                            <Tooltip title="Open in Data Exploration">
                              <Button
                                size="small"
                                type="text"
                                icon={<LinkOutlined />}
                                style={{ fontSize: 11, height: 20, padding: '0 4px' }}
                                onClick={() =>
                                  navigate(
                                    `/explore/${encodeURIComponent(datasource)}/${encodeURIComponent(docId)}`
                                  )
                                }
                              >
                                Go to doc
                              </Button>
                            </Tooltip>
                          )}
                        </Space>
                        <Progress
                          percent={Math.round(score * 100)}
                          showInfo={false}
                          size={[undefined, 2]}
                          strokeColor={scoreColor}
                          style={{ margin: '4px 0 4px' }}
                        />
                        <div style={{ color: token.colorTextSecondary, fontSize: 11 }}>
                          {src.text?.slice(0, 220)}
                          {(src.text?.length ?? 0) > 220 && '…'}
                        </div>
                      </div>
                    )
                  })}
                </div>
              ),
            }]}
          />
        </div>
      )}
    </div>
  )
}
