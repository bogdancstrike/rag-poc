import { Tooltip, theme } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'

interface InfoPointProps {
  content: string
  title?: string
}

/**
 * Small info icon that reveals explanatory text on hover.
 * Used for "Info points for main features".
 */
export function InfoPoint({ content, title }: InfoPointProps) {
  const { token } = theme.useToken()

  return (
    <Tooltip 
      title={
        <div style={{ padding: '4px 2px' }}>
          {title && <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 12 }}>{title}</div>}
          <div style={{ fontSize: 11, lineHeight: 1.4 }}>{content}</div>
        </div>
      }
      placement="top"
      overlayStyle={{ maxWidth: 280 }}
    >
      <InfoCircleOutlined 
        style={{ 
          fontSize: 14, 
          color: token.colorTextTertiary, 
          cursor: 'help',
          verticalAlign: 'middle',
          transition: 'color 0.2s'
        }} 
        onMouseEnter={(e) => (e.currentTarget.style.color = token.colorPrimary)}
        onMouseLeave={(e) => (e.currentTarget.style.color = token.colorTextTertiary)}
      />
    </Tooltip>
  )
}
