import { Tooltip, theme, Typography } from 'antd'

const { Text } = Typography

interface RelevanceBarProps {
  score: number
  showPercent?: boolean
}

/**
 * Visual indicator of search relevance score.
 */
export function RelevanceBar({ score, showPercent = true }: RelevanceBarProps) {
  const { token } = theme.useToken()
  
  let color = token.colorError
  if (score >= 0.75) color = token.colorSuccess
  else if (score >= 0.45) color = token.colorWarning

  const percent = Math.round(score * 100)

  return (
    <Tooltip title={`Relevance: ${percent}% of best match`}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ 
          width: 60, 
          height: 4, 
          background: token.colorFillTertiary, 
          borderRadius: 2,
          overflow: 'hidden'
        }}>
          <div style={{ 
            width: `${percent}%`, 
            height: '100%', 
            background: color, 
            borderRadius: 2,
            transition: 'width 0.3s ease'
          }} />
        </div>
        {showPercent && (
          <Text style={{ fontSize: 11, color: token.colorTextDescription, width: 32 }}>
            {percent}%
          </Text>
        )}
      </div>
    </Tooltip>
  )
}
