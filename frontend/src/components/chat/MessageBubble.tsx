import { Typography, Collapse, Tag, Space, theme } from 'antd'
import ReactMarkdown from 'react-markdown'
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
                  {message.sources.map((src, i) => (
                    <div
                      key={i}
                      style={{
                        padding:      '6px 10px',
                        background:   token.colorFillTertiary,
                        borderRadius: token.borderRadius,
                        fontSize:     11,
                      }}
                    >
                      <Space>
                        <Tag style={{ fontSize: 10, margin: 0 }} color="blue">
                          {src.id.slice(0, 8)}
                        </Tag>
                        <Text style={{ fontSize: 10, color: token.colorTextDescription }}>
                          score: {src.score?.toFixed(2)}
                        </Text>
                      </Space>
                      <div style={{ color: token.colorTextSecondary, marginTop: 4, fontSize: 11 }}>
                        {src.text?.slice(0, 180)}
                        {(src.text?.length ?? 0) > 180 && '…'}
                      </div>
                    </div>
                  ))}
                </div>
              ),
            }]}
          />
        </div>
      )}
    </div>
  )
}
