import {
  Row, Col, Card, Spin, Alert, Button, Tag, Typography, Space, Tooltip,
  Divider, theme, Table, Tabs, List, Badge, Progress,
} from 'antd'
import {
  ReloadOutlined, FireOutlined, RiseOutlined, TeamOutlined, WarningOutlined,
  ClockCircleOutlined, SyncOutlined, BarChartOutlined, NodeIndexOutlined,
  DeleteOutlined, SendOutlined, TableOutlined, BulbOutlined, BookOutlined,
  GlobalOutlined, AlertOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useInsights, useRefreshInsights, useDeleteInsights, useRefreshTask } from '@/hooks/useInsights'
import { TrendAreaChart } from './TrendAreaChart'
import { EntityBarChart } from './EntityBarChart'
import { RelationshipGraph } from './RelationshipGraph'
import { WordCloud } from './WordCloud'
import { DataTable } from '@/components/explore/DataTable'

dayjs.extend(utc)
dayjs.extend(relativeTime)

const { Title, Text, Paragraph } = Typography

const SENTIMENT_COLOR: Record<string, string> = {
  positive: 'success',
  negative: 'error',
  neutral:  'default',
  mixed:    'warning',
  hostile:  'error',
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

  const tasks       = insights?.tasks || {}
  const meta        = insights?._meta
  const summaryTask = tasks.summary || { status: 'pending' }
  const nerTask     = tasks.ner     || { status: 'pending' }
  const graphTask   = tasks.graph   || { status: 'pending' }
  const statsTask   = tasks.stats   || { status: 'pending' }

  const isProcessing = meta?.is_processing ||
    Object.values(tasks).some((t: any) => t.status === 'processing' || t.status === 'pending')

  const generatedAt = summaryTask.generated_at
    ? dayjs.utc(summaryTask.generated_at).local().fromNow()
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
    if (summaryTask.payload?.hot_topics?.length) {
      parts.push(
        'Hot Topics:\n' +
          summaryTask.payload.hot_topics
            .map((t: any) => `- ${t.topic} [${t.sentiment}]: ${t.summary}`)
            .join('\n'),
      )
    }
    if (summaryTask.payload?.narratives?.length) {
      parts.push(
        'Active Narratives:\n' +
          summaryTask.payload.narratives
            .map((n: any) => `- ${n.title}: ${n.description}`)
            .join('\n'),
      )
    }
    if (nerTask.payload?.entities?.length) {
      parts.push(
        'Key Entities:\n' +
          nerTask.payload.entities
            .slice(0, 10)
            .map((e: any) => `- ${e.name} (${e.type})`)
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
                  disabled={!summaryTask.payload && !nerTask.payload}
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

      {/* ── Corpus Statistics ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Corpus Statistics', statsTask,
          <BarChartOutlined style={{ color: token.colorInfo }} />, 'stats', 'static')}
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
                    <Text strong style={{ fontSize: 12 }}>Top Platforms</Text>
                    <Table
                      dataSource={statsTask.payload.platforms || []}
                      columns={staticCols}
                      size="small"
                      pagination={false}
                      rowKey="label"
                      scroll={{ y: 160 }}
                    />
                  </Col>
                  <Col span={8}>
                    <Text strong style={{ fontSize: 12 }}>Top Regions</Text>
                    <Table
                      dataSource={statsTask.payload.regions || []}
                      columns={staticCols}
                      size="small"
                      pagination={false}
                      rowKey="label"
                      scroll={{ y: 160 }}
                    />
                  </Col>
                  <Col span={8}>
                    <Text strong style={{ fontSize: 12 }}>Top Entities</Text>
                    <Table
                      dataSource={statsTask.payload.entities || []}
                      columns={staticCols}
                      size="small"
                      pagination={false}
                      rowKey="label"
                      scroll={{ y: 160 }}
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
                    height={120}
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
        title={renderTaskHeader('Hot Topics & Sentiment', summaryTask,
          <FireOutlined style={{ color: token.colorWarning }} />, 'summary', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {summaryTask.payload ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(summaryTask.payload.hot_topics || []).slice(0, 10).map((t: any, i: number) => {
              const sentColor =
                t.sentiment === 'positive' ? token.colorSuccess :
                t.sentiment === 'negative' || t.sentiment === 'hostile' ? token.colorError :
                t.sentiment === 'mixed' ? token.colorWarning :
                token.colorTextSecondary
              const bgColor =
                t.sentiment === 'positive' ? 'rgba(82,196,26,0.06)' :
                t.sentiment === 'negative' || t.sentiment === 'hostile' ? 'rgba(255,77,79,0.06)' :
                t.sentiment === 'mixed' ? 'rgba(250,173,20,0.06)' :
                token.colorFillAlter
              const max = Math.max(...(summaryTask.payload.hot_topics || []).map((x: any) => x.count_estimate || 0), 1)
              const pct = Math.round(((t.count_estimate || 0) / max) * 100)
              return (
                <div
                  key={i}
                  style={{
                    background: bgColor,
                    border: `1px solid ${token.colorBorderSecondary}`,
                    borderLeft: `3px solid ${sentColor}`,
                    borderRadius: token.borderRadius,
                    padding: '8px 12px',
                    cursor: 'pointer',
                  }}
                  onClick={() => onAskAbout(`What can you tell me about "${t.topic}"?`)}
                >
                  <Row align="middle" justify="space-between" wrap={false}>
                    <Space size={8} style={{ flex: 1, minWidth: 0 }}>
                      <Text strong style={{ fontSize: 13 }}>{t.topic}</Text>
                      <Tag
                        color={SENTIMENT_COLOR[t.sentiment] || 'default'}
                        style={{ fontSize: 10, margin: 0, flexShrink: 0 }}
                      >
                        {t.sentiment?.toUpperCase() || 'N/A'}
                      </Tag>
                    </Space>
                    <Space size={8} style={{ flexShrink: 0, marginLeft: 12 }}>
                      {t.count_estimate > 0 && (
                        <Text type="secondary" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                          ~{t.count_estimate} mentions
                        </Text>
                      )}
                    </Space>
                  </Row>
                  {t.summary && (
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                      {t.summary}
                    </Text>
                  )}
                  {pct > 0 && (
                    <Progress
                      percent={pct}
                      showInfo={false}
                      size={[undefined, 3]}
                      strokeColor={sentColor}
                      style={{ marginTop: 6, marginBottom: 0 }}
                    />
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
        title={renderTaskHeader('Active Narratives', summaryTask,
          <BookOutlined style={{ color: '#fa541c' }} />, 'summary', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {summaryTask.payload ? (
          summaryTask.payload.narratives?.length > 0 ? (
            <List
              size="small"
              dataSource={(summaryTask.payload.narratives || []).slice(0, 5)}
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
                        {narrative.evidence_docs?.length > 0 && (
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            Evidence: {narrative.evidence_docs.slice(0, 3).join(', ')}
                            {narrative.evidence_docs.length > 3 ? ` +${narrative.evidence_docs.length - 3} more` : ''}
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

      {/* ── Trends ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Trending Signals', summaryTask,
          <RiseOutlined style={{ color: token.colorSuccess }} />, 'summary', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {summaryTask.payload ? (
          <div>
            <TrendAreaChart trends={summaryTask.payload.trends || []} height={180} />
            {summaryTask.payload.trends?.length > 0 && (
              <Row gutter={[10, 10]} style={{ marginTop: 12 }}>
                {(summaryTask.payload.trends || []).slice(0, 10).map((t: any, i: number) => {
                  const trendColor =
                    t.direction === 'rising' ? token.colorSuccess :
                    t.direction === 'falling' ? token.colorError :
                    token.colorTextSecondary
                  return (
                    <Col key={i} xs={12} sm={8} md={6} lg={4}>
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
                        {t.change_pct !== undefined && (
                          <Text
                            style={{
                              fontSize: 15,
                              fontWeight: 700,
                              color: trendColor,
                              display: 'block',
                              marginTop: 4,
                            }}
                          >
                            {t.change_pct > 0 ? '+' : ''}{t.change_pct?.toFixed(1)}%
                          </Text>
                        )}
                        {t.time_period && (
                          <Text type="secondary" style={{ fontSize: 10, display: 'block' }}>
                            {t.time_period}
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

      {/* ── Named Entities ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Identified Entities (NER)', nerTask,
          <TeamOutlined style={{ color: token.colorPrimary }} />, 'ner', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '8px 16px 16px' } }}
      >
        {nerTask.payload ? (
          <div>
            <EntityBarChart entities={nerTask.payload.entities || []} height={200} />
            {nerTask.payload.entities?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <WordCloud
                  words={nerTask.payload.entities.map((e: any) => ({
                    label: e.name,
                    value: e.frequency || 1,
                  }))}
                  height={100}
                />
              </div>
            )}
          </div>
        ) : renderLoading()}
      </Card>

      {/* ── Relationship Network (D3 graph) ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader('Relationship Network', graphTask,
          <NodeIndexOutlined style={{ color: '#722ed1' }} />, 'graph', 'ai')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '16px' } }}
      >
        {graphTask.payload ? (
          <RelationshipGraph
            nodes={graphTask.payload.nodes || []}
            edges={graphTask.payload.edges || []}
            height={380}
          />
        ) : renderLoading()}
      </Card>
    </div>
  )

  return (
    <Tabs
      defaultActiveKey="report"
      size="small"
      items={[
        {
          key: 'report',
          label: (
            <Space>
              <BulbOutlined />
              Intelligence Report
              {isProcessing && <SyncOutlined spin style={{ fontSize: 10 }} />}
            </Space>
          ),
          children: reportTab,
        },
        {
          key: 'data',
          label: (
            <Space>
              <TableOutlined />
              Raw Data
            </Space>
          ),
          children: (
            <div style={{ height: 'calc(100vh - 180px)' }}>
              <DataTable datasource={datasource} onSendToRag={onSendToRag} />
            </div>
          ),
        },
      ]}
      tabBarStyle={{ marginBottom: 0, paddingBottom: 8 }}
    />
  )
}
