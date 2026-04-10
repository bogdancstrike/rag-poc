import {
  Row, Col, Card, Spin, Alert, Button, Tag, Typography, Space, Tooltip,
  Divider, theme, Empty, Progress
} from 'antd'
import {
  ReloadOutlined, InfoCircleOutlined, FireOutlined, RiseOutlined,
  TeamOutlined, WarningOutlined, ClockCircleOutlined, SyncOutlined,
  BarChartOutlined, NodeIndexOutlined, DeleteOutlined
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useInsights, useRefreshInsights, useDeleteInsights } from '@/hooks/useInsights'
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
 * InsightsPanel — Displays background task results and progress.
 */
export function InsightsPanel({ datasource = 'default', onAskAbout }: Props) {
  const { token } = theme.useToken()
  const { data: insights, isLoading, error } = useInsights(datasource)
  const refreshMut = useRefreshInsights(datasource)
  const deleteMut = useDeleteInsights(datasource)

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
        message="Failed to load insights"
        description={(error as Error).message}
        action={<Button size="small" onClick={() => refreshMut.mutate()}>Retry</Button>}
      />
    )
  }

  if (!insights) return null

  const tasks = insights.tasks || {}
  const meta = insights._meta
  const summaryTask = tasks.summary || { status: 'pending' }
  const nerTask     = tasks.ner || { status: 'pending' }
  const graphTask   = tasks.graph || { status: 'pending' }
  const statsTask   = tasks.stats || { status: 'pending' }

  const isProcessing = meta?.is_processing || Object.values(tasks).some((t: any) => t.status === 'processing' || t.status === 'pending')
  const generatedAt = summaryTask.generated_at ? dayjs(summaryTask.generated_at).fromNow() : '—'

  const renderTaskHeader = (title: string, task: any, icon: any) => (
    <Row justify="space-between" align="middle" style={{ width: '100%' }}>
      <Space>
        {icon}
        <Text strong>{title}</Text>
      </Space>
      <Space>
        {(task.status === 'processing' || task.status === 'pending') && (
          <SyncOutlined spin style={{ color: token.colorPrimary }} />
        )}
        {task.status === 'error' && (
          <Tooltip title={task.error}>
            <WarningOutlined style={{ color: token.colorError }} />
          </Tooltip>
        )}
      </Space>
    </Row>
  )

  const renderLoadingState = () => (
    <div style={{ padding: '20px 0', textAlign: 'center' }}>
      <Spin size="small" />
      <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>Analyzing documents...</Text>
    </div>
  )

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
            {isProcessing && <Tag color="processing" icon={<SyncOutlined spin />}>UPDATING</Tag>}
          </Space>
          <Space size={8}>
            <Text style={{ fontSize: 11, color: token.colorTextDescription }}>
              <ClockCircleOutlined /> {generatedAt}
            </Text>
            <Tooltip title="Delete cached insights">
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={deleteMut.isPending}
                onClick={() => deleteMut.mutate()}
              >
                Clear
              </Button>
            </Tooltip>
            <Tooltip title="Force full background regeneration">
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={refreshMut.isPending || isProcessing}
                onClick={() => refreshMut.mutate()}
              >
                Refresh
              </Button>
            </Tooltip>
          </Space>
        </Row>
      </Card>

      {/* ── Stats ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader("Corpus Statistics", statsTask, <BarChartOutlined style={{ color: token.colorInfo }} />)}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '12px 16px' } }}
      >
        {statsTask.payload ? (
          <Row gutter={16}>
            <Col span={8}>
              <div style={{ textAlign: 'center' }}>
                <Text type="secondary" style={{ fontSize: 11 }}>TOTAL DOCS</Text>
                <Title level={4} style={{ margin: 0 }}>{statsTask.payload.doc_count}</Title>
              </div>
            </Col>
            <Col span={16}>
              <div style={{ display: 'flex', gap: 8, overflowX: 'auto' }}>
                {statsTask.payload.distribution?.map((d: any, i: number) => (
                  <div key={i} style={{ minWidth: 80 }}>
                    <Text style={{ fontSize: 10 }}>{d.label}</Text>
                    <Progress percent={d.value} size="small" strokeColor={token.colorPrimary} />
                  </div>
                ))}
              </div>
            </Col>
          </Row>
        ) : renderLoadingState()}
      </Card>

      {/* ── Hot Topics ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader("Hot Topics", summaryTask, <FireOutlined style={{ color: token.colorWarning }} />)}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {summaryTask.payload ? (
          <Row gutter={[16, 12]}>
            <Col xs={24} md={14}>
              <TopicBubbleChart topics={summaryTask.payload.hot_topics || []} height={200} />
            </Col>
            <Col xs={24} md={10}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingTop: 8 }}>
                {(summaryTask.payload.hot_topics || []).map((t: any, i: number) => (
                  <Tag
                    key={i}
                    color={SENTIMENT_COLOR[t.sentiment]}
                    style={{ cursor: 'pointer', fontSize: 11 }}
                    onClick={() => onAskAbout(`What can you tell me about "${t.topic}"?`)}
                  >
                    {t.topic}
                  </Tag>
                ))}
              </div>
            </Col>
          </Row>
        ) : renderLoadingState()}
      </Card>

      {/* ── Trends ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader("Trends", summaryTask, <RiseOutlined style={{ color: token.colorSuccess }} />)}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {summaryTask.payload ? (
          <TrendAreaChart trends={summaryTask.payload.trends || []} height={200} />
        ) : renderLoadingState()}
      </Card>

      {/* ── Entities ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader("Identified Entities", nerTask, <TeamOutlined style={{ color: token.colorPrimary }} />)}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {nerTask.payload ? (
          <EntityBarChart entities={nerTask.payload.entities || []} height={200} />
        ) : renderLoadingState()}
      </Card>

      {/* ── Graph ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader("Relationship Network", graphTask, <NodeIndexOutlined style={{ color: token.colorPurple }} />)}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '16px' } }}
      >
        {graphTask.payload ? (
          <div style={{ background: '#f5f5f5', borderRadius: 8, padding: 12, fontSize: 12 }}>
            <Text type="secondary">Graph visualization coming soon. Current detections:</Text>
            <Divider style={{ margin: '8px 0' }} />
            <div style={{ maxHeight: 150, overflowY: 'auto' }}>
              {graphTask.payload.edges?.map((e: any, i: number) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  <Tag size="small">{e.source}</Tag> 
                  <Text type="secondary" style={{ fontSize: 10 }}> —[{e.relationship}]—&gt; </Text>
                  <Tag size="small">{e.target}</Tag>
                </div>
              ))}
            </div>
          </div>
        ) : renderLoadingState()}
      </Card>
    </div>
  )
}
