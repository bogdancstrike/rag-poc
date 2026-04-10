import { Card, Tag, Typography, Button, Space, theme } from 'antd'
import { CommentOutlined } from '@ant-design/icons'
import type { Narrative } from '@/types'
import { useSessionStore } from '@/stores/sessionStore'

const { Text, Paragraph } = Typography

const SENTIMENT_TAG: Record<string, { color: string; label: string }> = {
  positive: { color: 'success', label: 'Positive' },
  negative: { color: 'error',   label: 'Negative' },
  neutral:  { color: 'default', label: 'Neutral'  },
  mixed:    { color: 'warning', label: 'Mixed'     },
}

interface Props {
  narrative: Narrative
  sentiment?: string
  onAskAbout: (question: string) => void
}

/**
 * Card showing a single narrative with a "Ask about this" CTA.
 * Clicking the CTA pre-populates the chat input via sessionStore.
 */
export function NarrativeCard({ narrative, sentiment = 'neutral', onAskAbout }: Props) {
  const { token } = theme.useToken()
  const tag = SENTIMENT_TAG[sentiment] ?? SENTIMENT_TAG.neutral

  const handleAsk = () => {
    onAskAbout(`Tell me more about the narrative: "${narrative.title}"`)
  }

  return (
    <Card
      size="small"
      variant="borderless"
      style={{
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
      }}
      styles={{ body: { padding: '12px 16px' } }}
    >
      <Space orientation="vertical" size={4} style={{ width: '100%' }}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Text strong style={{ fontSize: 13 }}>{narrative.title}</Text>
          <Tag color={tag.color}>{tag.label}</Tag>
        </Space>
        <Paragraph
          style={{ fontSize: 12, color: token.colorTextSecondary, margin: 0 }}
          ellipsis={{ rows: 3, expandable: true, symbol: 'more' }}
        >
          {narrative.description}
        </Paragraph>
        {narrative.evidence_docs?.length > 0 && (
          <Text style={{ fontSize: 11, color: token.colorTextDescription }}>
            Evidence: {narrative.evidence_docs.slice(0, 3).join(', ')}
            {narrative.evidence_docs.length > 3 && ` +${narrative.evidence_docs.length - 3} more`}
          </Text>
        )}
        <Button
          type="link"
          size="small"
          icon={<CommentOutlined />}
          onClick={handleAsk}
          style={{ padding: 0, height: 'auto', fontSize: 12 }}
        >
          Ask about this
        </Button>
      </Space>
    </Card>
  )
}
