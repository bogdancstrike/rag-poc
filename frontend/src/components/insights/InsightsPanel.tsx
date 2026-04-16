import {
  Row, Col, Card, Spin, Alert, Button, Tag, Typography, Space, Tooltip,
  theme, Table, List, Badge,
} from 'antd'
import {
  ReloadOutlined, FireOutlined, RiseOutlined, WarningOutlined, BookOutlined,
  ClockCircleOutlined, SyncOutlined, BarChartOutlined, NodeIndexOutlined,
  DeleteOutlined, SendOutlined, AlertOutlined, MessageOutlined, BulbOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useInsights, useRefreshInsights, useDeleteInsights, useRefreshTask } from '@/hooks/useInsights'
import { TrendAreaChart } from './TrendAreaChart'
import { RelationshipGraph } from './RelationshipGraph'
import { WordCloud } from './WordCloud'
import { PageHeader } from '../common/PageHeader'
import { SentimentTag } from '../common/IntelligenceTags'

dayjs.extend(utc)
dayjs.extend(relativeTime)

const { Title, Text, Paragraph } = Typography

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
      <Space size={10}>
        {icon}
        <Text strong style={{ fontSize: 14 }}>{title}</Text>
        {badge === 'ai' && (
          <Tag color="purple" style={{ fontSize: 9, margin: 0, borderRadius: 4, fontWeight: 600 }}>AI ANALYZED</Tag>
        )}
        {badge === 'static' && (
          <Tag color="cyan" style={{ fontSize: 9, margin: 0, borderRadius: 4, fontWeight: 600 }}>AGGREGATED</Tag>
        )}
      </Space>
      <Space>
        {(task.status === 'processing' || task.status === 'pending') && (
          <SyncOutlined spin style={{ color: token.colorPrimary, fontSize: 12 }} />
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
    { title: 'Label', dataIndex: 'label', key: 'label', render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text> },
    {
      title: 'Count', dataIndex: 'value', key: 'value', width: 70, align: 'right' as const,
      render: (v: number) => <Badge count={v} color="blue" overflowCount={9999} style={{ fontSize: 10 }} />,
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, padding: '0 20px 24px' }}>

      <PageHeader 
        title="Intelligence Report" 
        icon={<BulbOutlined />}
        subtitle={`Automated synthesis of ${datasource} intelligence corpus.`}
        info="Multi-task AI analysis identifying emerging narratives, sentiment trends, and entity networks. High-level summaries are generated using semantic sampling."
        extra={
          <Space size={8}>
            <Text style={{ fontSize: 11, color: token.colorTextDescription, marginRight: 8 }}>
              <ClockCircleOutlined style={{ marginRight: 4 }} />
              Updated {generatedAt}
            </Text>
            {onSendToRag && (
              <Button
                size="small"
                icon={<SendOutlined />}
                onClick={handleSendInsightsToRag}
                disabled={!topicsTask.payload && !narrativesTask.payload}
              >
                Send to RAG
              </Button>
            )}
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={deleteMut.isPending}
              onClick={() => deleteMut.mutate()}
            >
              Clear
            </Button>
            <Button
              size="small"
              type="primary"
              icon={<ReloadOutlined />}
              loading={refreshMut.isPending || isProcessing}
              onClick={() => refreshMut.mutate()}
            >
              Refresh
            </Button>
          </Space>
        }
      />

      {isProcessing && (
        <Alert 
          message="Intelligence synthesis in progress" 
          description="AI agents are currently analyzing the corpus. Sections will update automatically as they complete."
          type="info"
          showIcon
          icon={<SyncOutlined spin />}
          style={{ borderRadius: 8 }}
        />
      )}

      {/* ── Corpus Statistics (Combined Fast Tasks) ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Corpus Statistics', statsTask,
          <BarChartOutlined style={{ color: token.colorInfo }} />, 'corpus_statistics', 'static')}
        style={{ border: `1px solid ${token.colorBorderSecondary}`, boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}
        styles={{ body: { padding: '12px 16px 16px' } }}
      >
        {statsTask.payload ? (
          <div>
            <Row gutter={24} align="top">
              {/* Doc count */}
              <Col span={5}>
                <div style={{
                  textAlign: 'center',
                  background: token.colorFillAlter,
                  padding: '24px 8px',
                  borderRadius: 8,
                  border: `1px solid ${token.colorBorderSecondary}`,
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center'
                }}>
                  <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>TOTAL DOCUMENTS</Text>
                  <Title level={2} style={{ margin: 0, color: token.colorPrimary }}>
                    {statsTask.payload.doc_count?.toLocaleString()}
                  </Title>
                </div>
              </Col>
              {/* Stats tables */}
              <Col span={19}>
                <Row gutter={16}>
                  <Col span={8}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
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
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
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
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
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
              <div style={{ marginTop: 24, paddingTop: 20, borderTop: `1px solid ${token.colorBorderSecondary}` }}>
                <Text strong style={{ fontSize: 12 }}>Key Topic Distribution</Text>
                <div style={{ marginTop: 12 }}>
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

      <Row gutter={[20, 20]}>
        <Col span={12}>
          {/* ── Hot Topics ── */}
          <Card
            variant="borderless"
            title={renderTaskHeader('Hot Topics & Sentiment', topicsTask,
              <FireOutlined style={{ color: token.colorWarning }} />, 'hot_topics_sentiment', 'ai')}
            style={{ border: `1px solid ${token.colorBorderSecondary}`, boxShadow: '0 1px 2px rgba(0,0,0,0.03)', height: '100%' }}
            styles={{ body: { padding: '12px 16px 16px' } }}
          >
            {topicsTask.payload ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {(topicsTask.payload.hot_topics || []).map((t: any, i: number) => (
                  <div
                    key={i}
                    style={{
                      background: token.colorBgLayout,
                      border: `1px solid ${token.colorBorderSecondary}`,
                      borderRadius: 8,
                      padding: '10px 14px',
                    }}
                  >
                    <Row align="middle" justify="space-between" wrap={false}>
                      <Space size={8} style={{ flex: 1, minWidth: 0 }}>
                        <Text strong style={{ fontSize: 13 }}>{t.topic}</Text>
                        <SentimentTag value={t.sentiment_label} />
                      </Space>
                      <Tooltip title={`Ask Assistant about "${t.topic}"`}>
                        <Button
                          size="small"
                          type="text"
                          icon={<MessageOutlined style={{ color: token.colorPrimary }} />}
                          onClick={() => onAskAbout(`What can you tell me about "${t.topic}"? Include sentiment analysis, key actors, and any notable developments.`)}
                        />
                      </Tooltip>
                    </Row>
                    {t.brief_context && (
                      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6, lineHeight: 1.4 }}>
                        {t.brief_context}
                      </Text>
                    )}
                  </div>
                ))}
              </div>
            ) : renderLoading()}
          </Card>
        </Col>

        <Col span={12}>
          {/* ── Active Narratives ── */}
          <Card
            variant="borderless"
            title={renderTaskHeader('Active Narratives', narrativesTask,
              <BookOutlined style={{ color: '#fa541c' }} />, 'active_narratives', 'ai')}
            style={{ border: `1px solid ${token.colorBorderSecondary}`, boxShadow: '0 1px 2px rgba(0,0,0,0.03)', height: '100%' }}
            styles={{ body: { padding: '12px 16px 16px' } }}
          >
            {narrativesTask.payload ? (
              narrativesTask.payload.active_narratives?.length > 0 ? (
                <List
                  size="small"
                  dataSource={(narrativesTask.payload.active_narratives || []).slice(0, 5)}
                  renderItem={(narrative: any, i: number) => (
                    <List.Item
                      key={i}
                      style={{ padding: '12px 0' }}
                      actions={[
                        <Tooltip key="ask" title="Analyze Narrative">
                          <Button
                            size="small"
                            type="text"
                            icon={<MessageOutlined style={{ color: token.colorPrimary }} />}
                            onClick={() => onAskAbout(`Tell me more about the narrative: "${narrative.title}"`)}
                          />
                        </Tooltip>,
                      ]}
                    >
                      <List.Item.Meta
                        avatar={<AlertOutlined style={{ color: '#fa541c', fontSize: 16, marginTop: 4 }} />}
                        title={<Text strong style={{ fontSize: 13 }}>{narrative.title}</Text>}
                        description={
                          <div>
                            <Paragraph style={{ margin: '4px 0', fontSize: 12, lineHeight: 1.5 }}>
                              {narrative.description}
                            </Paragraph>
                            {narrative.key_actors?.length > 0 && (
                              <div style={{ marginTop: 4 }}>
                                {narrative.key_actors.map((actor: string) => (
                                  <Tag key={actor} size="small" style={{ fontSize: 9, borderRadius: 3 }}>{actor}</Tag>
                                ))}
                              </div>
                            )}
                          </div>
                        }
                      />
                    </List.Item>
                  )}
                />
              ) : (
                <div style={{ padding: '20px 0', textAlign: 'center' }}>
                  <Text type="secondary">No significant narratives detected</Text>
                </div>
              )
            ) : renderLoading()}
          </Card>
        </Col>
      </Row>

      {/* ── Trending Signals ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Trending Signals', trendingTask,
          <RiseOutlined style={{ color: token.colorSuccess }} />, 'trending_signals', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}`, boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}
        styles={{ body: { padding: '12px 16px 16px' } }}
      >
        {trendingTask.payload ? (
          <div>
            <TrendAreaChart trends={trendingTask.payload.trending_signals || []} height={180} />
            {trendingTask.payload.trending_signals?.length > 0 && (
              <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
                {(trendingTask.payload.trending_signals || []).slice(0, 10).map((t: any, i: number) => {
                  const trendColor =
                    t.direction === 'rising' ? token.colorSuccess :
                    t.direction === 'falling' ? token.colorError :
                    token.colorTextSecondary
                  return (
                    <Col key={i} xs={12} sm={8} md={6}>
                      <div style={{
                        background: token.colorFillAlter,
                        borderRadius: 8,
                        padding: '10px 12px',
                        border: `1px solid ${token.colorBorderSecondary}`,
                        borderLeft: `3px solid ${trendColor}`,
                        height: '100%',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                          {DIRECTION_ICON[t.direction]}
                          <Text strong style={{ fontSize: 12 }}>{t.label}</Text>
                        </div>
                        {t.change_summary && (
                          <Text type="secondary" style={{ fontSize: 11, display: 'block', lineHeight: 1.4 }}>
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
        style={{ border: `1px solid ${token.colorBorderSecondary}`, boxShadow: '0 1px 2px rgba(0,0,0,0.03)' }}
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
