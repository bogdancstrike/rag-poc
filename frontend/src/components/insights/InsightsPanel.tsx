import {
  Row, Col, Card, Spin, Alert, Button, Tag, Typography, Space, Tooltip,
  Divider, theme, Table, Tabs,
} from 'antd'
import {
  ReloadOutlined, FireOutlined, RiseOutlined, TeamOutlined, WarningOutlined,
  ClockCircleOutlined, SyncOutlined, BarChartOutlined, NodeIndexOutlined,
  DeleteOutlined, SendOutlined, TableOutlined, BulbOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useInsights, useRefreshInsights, useDeleteInsights, useRefreshTask } from '@/hooks/useInsights'
import { TopicBubbleChart } from './TopicBubbleChart'
import { TrendAreaChart } from './TrendAreaChart'
import { EntityBarChart } from './EntityBarChart'
import { NarrativeCard } from './NarrativeCard'
import { DataTable } from '@/components/explore/DataTable'

dayjs.extend(utc)
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
  /** Called when the user clicks "Send to RAG" from the insights panel. */
  onSendToRag?: (docs: any[]) => void
}

/**
 * InsightsPanel — Intelligence Report + Data Table tabs for a datasource.
 *
 * Shows background AI task results (summary, NER, graph, stats) and
 * a raw data table. Provides "Ask about this" and "Send to RAG" actions.
 */
export function InsightsPanel({ datasource = 'default', onAskAbout, onSendToRag }: Props) {
  const { token } = theme.useToken()
  const { data: insights, isLoading, error } = useInsights(datasource)
  const refreshMut = useRefreshInsights(datasource)
  const deleteMut = useDeleteInsights(datasource)
  const refreshTaskMut = useRefreshTask(datasource)

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
  const generatedAt = summaryTask.generated_at
    ? dayjs.utc(summaryTask.generated_at).local().fromNow()
    : '—'

  /** Compose an intelligence summary context and send it to the RAG chat. */
  const handleSendInsightsToRag = () => {
    if (!onSendToRag) return
    const parts: string[] = []
    if (summaryTask.payload?.hot_topics?.length) {
      parts.push(
        'Hot Topics:\n' +
          summaryTask.payload.hot_topics
            .map((t: any) => `- ${t.topic}: ${t.summary}`)
            .join('\n'),
      )
    }
    if (nerTask.payload?.entities?.length) {
      parts.push(
        'Identified Entities:\n' +
          nerTask.payload.entities
            .slice(0, 10)
            .map((e: any) => `- ${e.name} (${e.type})`)
            .join('\n'),
      )
    }
    if (summaryTask.payload?.narratives?.length) {
      parts.push(
        'Narratives:\n' +
          summaryTask.payload.narratives
            .map((n: any) => `- ${n.title}: ${n.description}`)
            .join('\n'),
      )
    }
    const context = parts.join('\n\n')
    onSendToRag([{ title: 'Intelligence Report', text: context }])
  }

  const renderTaskHeader = (title: string, task: any, icon: any, taskKey: string, type: 'ai' | 'static' = 'ai') => (
    <Row justify="space-between" align="middle" style={{ width: '100%' }}>
      <Space>
        {icon}
        <Text strong>{title}</Text>
        <Tag color={type === 'ai' ? 'purple' : 'cyan'} style={{ fontSize: 10, lineHeight: '14px', margin: 0 }}>
          {type === 'ai' ? 'AI-GENERATED' : 'STATIC ANALYSIS'}
        </Tag>
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

  const renderLoadingState = () => (
    <div style={{ padding: '20px 0', textAlign: 'center' }}>
      <Spin size="small" />
      <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>Analyzing documents...</Text>
    </div>
  )

  const staticCols = [
    { title: 'Label', dataIndex: 'label', key: 'label' },
    { title: 'Count', dataIndex: 'value', key: 'value', width: 80, align: 'right' as const },
  ]

  /** The full Intelligence Report tab content. */
  const reportTabContent = (
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
            {onSendToRag && (
              <Tooltip title="Send intelligence summary to RAG Chat">
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
        title={renderTaskHeader("Corpus Statistics", statsTask, <BarChartOutlined style={{ color: token.colorInfo }} />, 'stats', 'static')}
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '16px' } }}
      >
        {statsTask.payload ? (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Row gutter={16} align="middle">
              <Col span={6}>
                <div style={{ textAlign: 'center', background: '#fafafa', padding: 16, borderRadius: 8 }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>TOTAL DOCS</Text>
                  <Title level={3} style={{ margin: 0, color: token.colorPrimary }}>{statsTask.payload.doc_count}</Title>
                </div>
              </Col>
              <Col span={18}>
                <Row gutter={16}>
                  <Col span={8}>
                    <Text strong style={{ fontSize: 12 }}>Top Platforms</Text>
                    <Table dataSource={statsTask.payload.platforms || []} columns={staticCols} size="small" pagination={false} rowKey="label" scroll={{ y: 150 }} />
                  </Col>
                  <Col span={8}>
                    <Text strong style={{ fontSize: 12 }}>Top Regions</Text>
                    <Table dataSource={statsTask.payload.regions || []} columns={staticCols} size="small" pagination={false} rowKey="label" scroll={{ y: 150 }} />
                  </Col>
                  <Col span={8}>
                    <Text strong style={{ fontSize: 12 }}>Top Static Entities</Text>
                    <Table dataSource={statsTask.payload.entities || []} columns={staticCols} size="small" pagination={false} rowKey="label" scroll={{ y: 150 }} />
                  </Col>
                </Row>
              </Col>
            </Row>
          </Space>
        ) : renderLoadingState()}
      </Card>

      {/* ── Hot Topics ── */}
      <Card
        variant="borderless"
        title={renderTaskHeader("Hot Topics", summaryTask, <FireOutlined style={{ color: token.colorWarning }} />, 'summary')}
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
        title={renderTaskHeader("Trends", summaryTask, <RiseOutlined style={{ color: token.colorSuccess }} />, 'summary')}
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
        title={renderTaskHeader("Identified Entities", nerTask, <TeamOutlined style={{ color: token.colorPrimary }} />, 'ner')}
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
        title={renderTaskHeader("Relationship Network", graphTask, <NodeIndexOutlined style={{ color: '#722ed1' }} />, 'graph')}
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
                  <Tag>{e.source}</Tag> 
                  <Text type="secondary" style={{ fontSize: 10 }}> —[{e.relationship}]—&gt; </Text>
                  <Tag>{e.target}</Tag>
                </div>
              ))}
            </div>
          </div>
        ) : renderLoadingState()}
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
          children: reportTabContent,
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
