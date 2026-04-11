import {
  Row, Col, Card, Spin, Alert, Button, Tag, Typography, Space, Tooltip,
  Divider, theme, Table, List, Badge, Progress,
} from 'antd'
import {
  ReloadOutlined, FireOutlined, RiseOutlined, WarningOutlined, BookOutlined,
  ClockCircleOutlined, SyncOutlined, BarChartOutlined, NodeIndexOutlined,
  DeleteOutlined, SendOutlined,
  GlobalOutlined, AlertOutlined, MessageOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useInsights, useRefreshInsights, useDeleteInsights, useRefreshTask } from '@/hooks/useInsights'
import { TrendAreaChart } from './TrendAreaChart'
import { RelationshipGraph } from './RelationshipGraph'
import { WordCloud } from './WordCloud'

dayjs.extend(utc)
dayjs.extend(relativeTime)

const { Title, Text, Paragraph } = Typography

/** Normalise any LLM sentiment value to the three canonical values. */
function normaliseSentiment(raw?: string): 'positive' | 'negative' | 'neutral' {
  const s = (raw || '').toLowerCase()
  if (s === 'positive' || s === 'supportive') return 'positive'
  if (s === 'negative' || s === 'hostile' || s === 'mixed') return 'negative'
  return 'neutral'
}

const SENTIMENT_COLOR: Record<string, string> = {
  positive: 'success',
  negative: 'error',
  neutral:  'default',
}

const DIRECTION_ICON: Record<string, any> = {
  rising:  <span style={{ color: '#52c41a' }}>↑</span>,
  falling: <span style={{ color: '#f5222d' }}>↓</span>,
  stable:  <span style={{ color: '#8c8c8c' }}>→</span>,
}

interface Props {
  datasource?: string
  onAskAbout: (question: string) => void
  onSendToRag?: (docs: any[]) => void
}

export function InsightsPanel({ datasource = 'default', onAskAbout, onSendToRag }: Props) {
  const { token } = theme.useToken()
  const { data: insights, isLoading, error } = useInsights(datasource)
  const refreshMut  = useRefreshInsights(datasource)
  const deleteMut   = useDeleteInsights(datasource)
  const refreshTaskMut = useRefreshTask(datasource)

  if (isLoading && !insights) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
        <Spin description="Loading intelligence report…" size="large" />
      </div>
    )
  }

  if (error && !insights) {
    return (
      <Alert
        type="error"
        message="Failed to load insights"
        description={(error as Error).message}
        action={<Button size="small" onClick={() => refreshMut.mutate()}>Retry</Button>}
      />
    )
  }

  const tasks = insights?.tasks || {}
  const meta  = insights?._meta

  // ── AI Tasks ──
  const trendingTask    = tasks.trending_signals     || { status: 'pending' }
  const narrativesTask  = tasks.active_narratives     || { status: 'pending' }
  const topicsTask      = tasks.hot_topics_sentiment || { status: 'pending' }
  const networkTask     = tasks.relationship_network || { status: 'pending' }

  // ── Fast Tasks ──
  const statsTask       = tasks.corpus_statistics    || { status: 'pending' }
  const regionsTask     = tasks.top_regions          || { status: 'pending' }
  const entitiesTask    = tasks.top_entities         || { status: 'pending' }
  const platformsTask   = tasks.top_platforms        || { status: 'pending' }

  const aiTaskKeys    = ['trending_signals', 'active_narratives', 'hot_topics_sentiment', 'relationship_network']
  const statsTaskKeys = ['corpus_statistics', 'top_regions', 'top_entities', 'top_platforms']
  const allTaskKeys   = [...aiTaskKeys, ...statsTaskKeys]

  const isProcessing = meta?.is_processing ||
    allTaskKeys.some((k) => tasks[k]?.status === 'processing' || tasks[k]?.status === 'pending')

  const generatedAt = topicsTask.generated_at
    ? dayjs.utc(topicsTask.generated_at).local().fromNow()
    : '—'

  /** Task card header with status indicator and restart button. */
  const renderTaskHeader = (
    title: string,
    task: any,
    icon: any,
    taskKey: string,
    badge?: 'ai' | 'static',
  ) => (
    <Row justify="space-between" align="middle" style={{ width: '100%' }}>
      <Space>
        {icon}
        <Text strong>{title}</Text>
        {badge === 'ai' && (
          <Tag color="purple" style={{ fontSize: 10, margin: 0 }}>AI</Tag>
        )}
        {badge === 'static' && (
          <Tag color="cyan" style={{ fontSize: 10, margin: 0 }}>STATIC</Tag>
        )}
      </Space>
      <Space>
        {(task.status === 'processing' || task.status === 'pending') && (
          <SyncOutlined spin style={{ color: token.colorPrimary }} />
        )}
        {task.status === 'error' && (
          <Space>
            <Tooltip title={task.error}>
              <WarningOutlined style={{ color: token.colorError }} />
            </Tooltip>
            <Button
              size="small"
              type="text"
              icon={<ReloadOutlined />}
              onClick={() => refreshTaskMut.mutate(taskKey)}
              loading={refreshTaskMut.isPending && refreshTaskMut.variables === taskKey}
            >
              Restart
            </Button>
          </Space>
        )}
      </Space>
    </Row>
  )

  const renderLoading = () => (
    <div style={{ padding: '24px 0', textAlign: 'center' }}>
      <Spin size="small" />
      <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
        AI is analyzing documents…
      </Text>
    </div>
  )

  const staticCols = [
    { title: 'Label', dataIndex: 'label', key: 'label', render: (v: string) => <Text>{v}</Text> },
    {
      title: 'Count', dataIndex: 'value', key: 'value', width: 70, align: 'right' as const,
      render: (v: number) => <Badge count={v} color="blue" overflowCount={9999} />,
    },
  ]

  /** Build context for "Send to RAG" */
  const handleSendInsightsToRag = () => {
    if (!onSendToRag) return
    const parts: string[] = []
    if (topicsTask.payload?.hot_topics?.length) {
      parts.push(
        'Hot Topics:\n' +
          topicsTask.payload.hot_topics
            .map((t: any) => `- ${t.topic} [${t.sentiment_label}]: ${t.brief_context}`)
            .join('\n'),
      )
    }
    if (narrativesTask.payload?.active_narratives?.length) {
      parts.push(
        'Active Narratives:\n' +
          narrativesTask.payload.active_narratives
            .map((n: any) => `- ${n.title}: ${n.description}`)
            .join('\n'),
      )
    }
    if (trendingTask.payload?.trending_signals?.length) {
      parts.push(
        'Trending Signals:\n' +
          trendingTask.payload.trending_signals
            .map((s: any) => `- ${s.label} [${s.direction}]: ${s.change_summary}`)
            .join('\n'),
      )
    }
    onSendToRag([{ title: 'Intelligence Report Summary', text: parts.join('\n\n') }])
  }

  /** ── Full intelligence report tab content ── */
  const reportTab = (
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
            <Text style={{ fontSize: 11, color: token.colorTextDescription }}>
              <ClockCircleOutlined style={{ marginRight: 4 }} />
              {generatedAt}
            </Text>
          </Space>
          <Space size={6}>
            {onSendToRag && (
              <Tooltip title="Send current intelligence data to RAG Chat">
                <Button
                  size="small"
                  icon={<SendOutlined />}
                  onClick={handleSendInsightsToRag}
                  disabled={!topicsTask.payload && !narrativesTask.payload}
                >
                  Send to RAG
                </Button>
              </Tooltip>
            )}
            <Tooltip title="Delete cached insights and re-generate">
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
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={refreshMut.isPending || isProcessing}
              onClick={() => refreshMut.mutate()}
            >
              Refresh
            </Button>
          </Space>
        </Row>
      </Card>

      {/* ── Corpus Statistics (Combined Fast Tasks) ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Corpus Statistics', statsTask,
          <BarChartOutlined style={{ color: token.colorInfo }} />, 'corpus_statistics', 'static')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '12px 16px 16px' } }}
      >
        {statsTask.payload ? (
          <div>
            <Row gutter={16} align="top">
              {/* Doc count */}
              <Col span={4}>
                <div style={{
                  textAlign: 'center',
                  background: token.colorFillAlter,
                  padding: '14px 8px',
                  borderRadius: token.borderRadius,
                  border: `1px solid ${token.colorBorderSecondary}`,
                }}>
                  <Text type="secondary" style={{ fontSize: 10, display: 'block' }}>TOTAL DOCS</Text>
                  <Title level={3} style={{ margin: 0, color: token.colorPrimary }}>
                    {statsTask.payload.doc_count?.toLocaleString()}
                  </Title>
                </div>
              </Col>
              {/* Stats tables */}
              <Col span={20}>
                <Row gutter={12}>
                  <Col span={8}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong style={{ fontSize: 12 }}>Top Platforms</Text>
                      {platformsTask.status === 'processing' && <SyncOutlined spin style={{ fontSize: 10 }} />}
                    </div>
                    <Table
                      dataSource={platformsTask.payload?.platforms || []}
                      columns={staticCols}
                      size="small"
                      pagination={false}
                      rowKey="label"
                      scroll={{ y: 160 }}
                      locale={{ emptyText: platformsTask.status === 'pending' ? 'Waiting...' : 'No data' }}
                    />
                  </Col>
                  <Col span={8}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong style={{ fontSize: 12 }}>Top Regions</Text>
                      {regionsTask.status === 'processing' && <SyncOutlined spin style={{ fontSize: 10 }} />}
                    </div>
                    <Table
                      dataSource={regionsTask.payload?.regions || []}
                      columns={staticCols}
                      size="small"
                      pagination={false}
                      rowKey="label"
                      scroll={{ y: 160 }}
                      locale={{ emptyText: regionsTask.status === 'pending' ? 'Waiting...' : 'No data' }}
                    />
                  </Col>
                  <Col span={8}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong style={{ fontSize: 12 }}>Top Entities</Text>
                      {entitiesTask.status === 'processing' && <SyncOutlined spin style={{ fontSize: 10 }} />}
                    </div>
                    <Table
                      dataSource={entitiesTask.payload?.entities || []}
                      columns={staticCols}
                      size="small"
                      pagination={false}
                      rowKey="label"
                      scroll={{ y: 160 }}
                      locale={{ emptyText: entitiesTask.status === 'pending' ? 'Waiting...' : 'No data' }}
                    />
                  </Col>
                </Row>
              </Col>
            </Row>

            {/* Word cloud from topics */}
            {statsTask.payload.topics?.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Text strong style={{ fontSize: 12 }}>Topic Word Cloud</Text>
                <div style={{ marginTop: 8 }}>
                  <WordCloud
                    words={statsTask.payload.topics.map((t: any) => ({
                      label: t.label,
                      value: t.value,
                    }))}
                    maxWords={50}
                    height={280}
                  />
                </div>
              </div>
            )}
          </div>
        ) : renderLoading()}
      </Card>

      {/* ── Hot Topics ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Hot Topics & Sentiment', topicsTask,
          <FireOutlined style={{ color: token.colorWarning }} />, 'hot_topics_sentiment', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {topicsTask.payload ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(topicsTask.payload.hot_topics || []).map((t: any, i: number) => {
              const sent = normaliseSentiment(t.sentiment_label)
              const sentColor =
                sent === 'positive' ? token.colorSuccess :
                sent === 'negative' ? token.colorError :
                token.colorTextSecondary
              const bgColor =
                sent === 'positive' ? 'rgba(82,196,26,0.06)' :
                sent === 'negative' ? 'rgba(255,77,79,0.06)' :
                token.colorFillAlter
              
              return (
                <div
                  key={i}
                  style={{
                    background: bgColor,
                    border: `1px solid ${token.colorBorderSecondary}`,
                    borderLeft: `3px solid ${sentColor}`,
                    borderRadius: token.borderRadius,
                    padding: '8px 12px',
                  }}
                >
                  <Row align="middle" justify="space-between" wrap={false}>
                    <Space size={8} style={{ flex: 1, minWidth: 0 }}>
                      <Text strong style={{ fontSize: 13 }}>{t.topic}</Text>
                      <Tag
                        color={SENTIMENT_COLOR[sent]}
                        style={{ fontSize: 10, margin: 0, flexShrink: 0 }}
                      >
                        {(t.sentiment_label || sent).toUpperCase()}
                      </Tag>
                    </Space>
                    <Space size={6} style={{ flexShrink: 0, marginLeft: 12 }}>
                      <Tooltip title={`Ask RAG Chat about "${t.topic}"`}>
                        <Button
                          size="small"
                          type="primary"
                          ghost
                          icon={<MessageOutlined />}
                          onClick={() => onAskAbout(`What can you tell me about "${t.topic}"? Include sentiment analysis, key actors, and any notable developments.`)}
                        >
                          Ask AI
                        </Button>
                      </Tooltip>
                    </Space>
                  </Row>
                  {t.brief_context && (
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                      {t.brief_context}
                    </Text>
                  )}
                </div>
              )
            })}
          </div>
        ) : renderLoading()}
      </Card>

      {/* ── Active Narratives ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Active Narratives', narrativesTask,
          <BookOutlined style={{ color: '#fa541c' }} />, 'active_narratives', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {narrativesTask.payload ? (
          narrativesTask.payload.active_narratives?.length > 0 ? (
            <List
              size="small"
              dataSource={(narrativesTask.payload.active_narratives || []).slice(0, 5)}
              renderItem={(narrative: any, i: number) => (
                <List.Item
                  key={i}
                  actions={[
                    <Button
                      key="ask"
                      size="small"
                      type="link"
                      onClick={() => onAskAbout(`Tell me more about the narrative: "${narrative.title}"`)}
                    >
                      Ask AI
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<AlertOutlined style={{ color: '#fa541c', fontSize: 16, marginTop: 2 }} />}
                    title={<Text strong style={{ fontSize: 13 }}>{narrative.title}</Text>}
                    description={
                      <div>
                        <Paragraph style={{ margin: '4px 0', fontSize: 13 }}>
                          {narrative.description}
                        </Paragraph>
                        {narrative.key_actors?.length > 0 && (
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            Actors: {narrative.key_actors.join(', ')}
                          </Text>
                        )}
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          ) : (
            <Text type="secondary">No significant narratives detected</Text>
          )
        ) : renderLoading()}
      </Card>

      {/* ── Trending Signals ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Trending Signals', trendingTask,
          <RiseOutlined style={{ color: token.colorSuccess }} />, 'trending_signals', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {trendingTask.payload ? (
          <div>
            {/* We can still use the chart if payload has trends, or add logic to adapt it */}
            <TrendAreaChart trends={trendingTask.payload.trending_signals || []} height={180} />
            {trendingTask.payload.trending_signals?.length > 0 && (
              <Row gutter={[10, 10]} style={{ marginTop: 12 }}>
                {(trendingTask.payload.trending_signals || []).slice(0, 10).map((t: any, i: number) => {
                  const trendColor =
                    t.direction === 'rising' ? token.colorSuccess :
                    t.direction === 'falling' ? token.colorError :
                    token.colorTextSecondary
                  return (
                    <Col key={i} xs={12} sm={8} md={6}>
                      <div style={{
                        background: token.colorFillAlter,
                        borderRadius: token.borderRadius,
                        padding: '8px 10px',
                        border: `1px solid ${token.colorBorderSecondary}`,
                        borderTop: `3px solid ${trendColor}`,
                        height: '100%',
                      }}>
                        <Text style={{ fontSize: 11, display: 'block', lineHeight: 1.3 }}>
                          {DIRECTION_ICON[t.direction]} {t.label}
                        </Text>
                        {t.change_summary && (
                          <Text type="secondary" style={{ fontSize: 10, display: 'block', marginTop: 4 }}>
                            {t.change_summary}
                          </Text>
                        )}
                      </div>
                    </Col>
                  )
                })}
              </Row>
            )}
          </div>
        ) : renderLoading()}
      </Card>

      {/* ── Relationship Network (D3 graph) ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Relationship Network', networkTask,
          <NodeIndexOutlined style={{ color: '#722ed1' }} />, 'relationship_network', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '16px' } }}
      >
        {networkTask.payload ? (
          <RelationshipGraph
            nodes={networkTask.payload.nodes || []}
            edges={networkTask.payload.edges || []}
            height={560}
          />
        ) : renderLoading()}
      </Card>
    </div>
  )

  return reportTab
}
