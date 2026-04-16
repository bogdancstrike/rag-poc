import { Tag, theme } from 'antd'
import { TagOutlined } from '@ant-design/icons'

interface TagProps {
  value?: string
  bordered?: boolean
}

/**
 * Standardized tag for intelligence classifications.
 */
export function ClassificationTag({ value, bordered = true }: TagProps) {
  if (!value) return null
  
  return (
    <Tag 
      icon={<TagOutlined />} 
      bordered={bordered}
      style={{ 
        fontSize: 10, 
        margin: 0, 
        textTransform: 'uppercase', 
        fontWeight: 500,
        borderRadius: 4
      }}
    >
      {value}
    </Tag>
  )
}

/**
 * Standardized tag for sentiment analysis results.
 */
export function SentimentTag({ value, bordered = false }: TagProps) {
  if (!value) return null
  
  const val = value.toLowerCase()
  let color: string = 'default'
  
  if (val === 'positive' || val === 'supportive') color = 'success'
  else if (val === 'negative' || val === 'hostile') color = 'error'
  else if (val === 'mixed') color = 'warning'
  
  return (
    <Tag 
      color={color} 
      bordered={bordered}
      style={{ 
        fontSize: 10, 
        margin: 0, 
        borderRadius: 4,
        fontWeight: 600
      }}
    >
      {value}
    </Tag>
  )
}
