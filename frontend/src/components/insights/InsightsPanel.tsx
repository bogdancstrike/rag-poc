import {
  Row, Col, Card, Spin, Alert, Button, Tag, Typography, Space, Tooltip,
  Divider, theme, Empty, Collapse
} from 'antd'
import {
  ReloadOutlined, InfoCircleOutlined, FireOutlined, RiseOutlined,
  TeamOutlined, WarningOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useInsights, useRefreshInsights } from '@/hooks/useInsights'
import { TopicBubbleChart } from './TopicBubbleChart'
import { TrendAreaChart } from './TrendAreaChart'
import { EntityBarChart } from './EntityBarChart'
import { NarrativeCard } from './NarrativeCard'

dayjs.extend(relativeTime)

const { Title, Text } = Typography

const SENTIMENT_COLOR: Record<string, string> = {
  positive: 'success',
  negative: 'error',
  neutral:  'default',
  mixed:    'warning',
}

interface Props {
  datasource?: string
  onAskAbout: (question: string) => void
}

/**
 * InsightsPanel — the left pane showing LLM-generated intelligence.
 *
 * Sections:
 *   1. Hot Topics    — bubble chart + tag list
 *   2. Trends        — horizontal bar chart
 *   3. Narratives    — collapsible cards with "Ask about this" CTA
 *   4. Entities      — bar chart
 *   5. Anomalies     — alert list
 */
export function InsightsPanel({ datasource = 'default', onAskAbout }: Props) {
  const { token } = theme.useToken()
  const { data: insights, isLoading, error } = useInsights(datasource)
  const refreshMut = useRefreshInsights(datasource)

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
        <Spin description="Generating intelligence report…" size="large" />
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="error"
        title="Failed to load insights"
        description={(error as Error).message}
        action={<Button size="small" onClick={() => refreshMut.mutate()}>Retry</Button>}
      />
    )
  }

  if (!insights) return null

  const meta = insights._meta
  const generatedAt = meta?.generated_at ? dayjs(meta.generated_at).fromNow() : '—'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Header bar */}
      <Card
        variant="borderless"
        styles={{ body: { padding: '10px 16px' } }}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Row align="middle" justify="space-between">
          <Space>
            <FireOutlined style={{ color: token.colorWarning }} />
            <Text strong style={{ fontSize: 13 }}>Intelligence Report</Text>
            {meta?.cached && (
              <Tag color="blue" style={{ fontSize: 10 }}>CACHED</Tag>
            )}
          </Space>
          <Space size={8}>
            <Text style={{ fontSize: 11, color: token.colorTextDescription }}>
              <ClockCircleOutlined /> {generatedAt}
            </Text>
            {meta?.doc_count && (
              <Text style={{ fontSize: 11, color: token.colorTextDescription }}>
                · {meta.doc_count} docs sampled
              </Text>
            )}
            <Tooltip title="Regenerate intelligence from corpus">
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={refreshMut.isPending}
                onClick={() => refreshMut.mutate()}
              >
                Refresh
              </Button>
            </Tooltip>
          </Space>
        </Row>
      </Card>

      {/* ── Hot Topics ─────────────────────────────────────────────────────── */}
      {insights.hot_topics?.length > 0 && (
        <Card
          variant="borderless"
          title={
            <Space><FireOutlined style={{ color: token.colorWarning }} />
              <Text strong>Hot Topics</Text>
            </Space>
          }
          style={{ border: `1px solid ${token.colorBorderSecondary}` }}
          styles={{ body: { padding: '8px 16px 16px' } }}
        >
          <Row gutter={[16, 12]}>
            <Col xs={24} md={14}>
              <TopicBubbleChart topics={insights.hot_topics} height={240} />
            </Col>
            <Col xs={24} md={10}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingTop: 8 }}>
                {insights.hot_topics.map((t, i) => (
                  <Tag
                    key={i}
                    color={SENTIMENT_COLOR[t.sentiment]}
                    style={{ cursor: 'pointer', fontSize: 11, padding: '2px 8px' }}
                    onClick={() => onAskAbout(`What can you tell me about "${t.topic}"?`)}
                  >
                    {t.topic}
                  </Tag>
                ))}
              </div>
            </Col>
          </Row>
        </Card>
      )}

      {/* ── Trends ─────────────────────────────────────────────────────────── */}
      {insights.trends?.length > 0 && (
        <Card
          variant="borderless"
          title={<Space><RiseOutlined style={{ color: token.colorSuccess }} /><Text strong>Trends</Text></Space>}
          style={{ border: `1px solid ${token.colorBorderSecondary}` }}
          styles={{ body: { padding: '8px 16px 16px' } }}
        >
          <TrendAreaChart trends={insights.trends} height={240} />
        </Card>
      )}

      {/* ── Narratives ─────────────────────────────────────────────────────── */}
      {insights.narratives?.length > 0 && (
        <Card
          variant="borderless"
          title={<Space><InfoCircleOutlined style={{ color: token.colorInfo }} /><Text strong>Key Narratives</Text></Space>}
          style={{ border: `1px solid ${token.colorBorderSecondary}` }}
          styles={{ body: { padding: '8px 16px 16px' } }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {insights.narratives.map((n, i) => (
              <NarrativeCard
                key={i}
                narrative={n}
                sentiment={insights.hot_topics?.[i % (insights.hot_topics.length || 1)]?.sentiment}
                onAskAbout={onAskAbout}
              />
            ))}
          </div>
        </Card>
      )}

      {/* ── Entities + Anomalies ────────────────────────────────────────────── */}
      <Row gutter={[16, 16]}>
        {insights.entities?.length > 0 && (
          <Col xs={24} lg={insights.anomalies?.length > 0 ? 14 : 24}>
            <Card
              variant="borderless"
              title={<Space><TeamOutlined style={{ color: token.colorPrimary }} /><Text strong>Key Entities</Text></Space>}
              style={{ border: `1px solid ${token.colorBorderSecondary}` }}
              styles={{ body: { padding: '8px 16px 16px' } }}
            >
              <EntityBarChart entities={insights.entities} height={240} />
            </Card>
          </Col>
        )}

        {insights.anomalies?.length > 0 && (
          <Col xs={24} lg={insights.entities?.length > 0 ? 10 : 24}>
            <Card
              variant="borderless"
              title={<Space><WarningOutlined style={{ color: token.colorError }} /><Text strong>Anomalies</Text></Space>}
              style={{ border: `1px solid ${token.colorBorderSecondary}` }}
              styles={{ body: { padding: '8px 16px 16px' } }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {insights.anomalies.map((a, i) => (
                  <Alert
                    key={i}
                    type="warning"
                    title={a.description}
                    description={a.docs?.length > 0 ? `Docs: ${a.docs.slice(0, 3).join(', ')}` : undefined}
                    action={
                      <Button
                        size="small"
                        type="link"
                        onClick={() => onAskAbout(`Explain the anomaly: "${a.description}"`)}
                      >
                        Ask
                      </Button>
                    }
                  />
                ))}
              </div>
            </Card>
          </Col>
        )}
      </Row>

      {/* Empty state */}
      {!insights.hot_topics?.length && !insights.narratives?.length && (
        <Card variant="borderless" style={{ border: `1px solid ${token.colorBorderSecondary}` }}>
          <Empty description="No insights available yet. Add data to the corpus and click Refresh." />
        </Card>
      )}
    </div>
  )
}
