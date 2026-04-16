import {
  Card, Col, Row, Typography, Tag, Space, Spin, Alert,
  Button, Progress, theme, Statistic, Descriptions,
} from 'antd'
import {
  DashboardOutlined, CheckCircleOutlined, SyncOutlined, 
  WarningOutlined, RightOutlined, BulbOutlined, RobotOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { useTasks } from '@/hooks/useTasks'
import { useLLMStats } from '@/hooks/useLLMStats'
import { PageHeader } from '../common/PageHeader'

dayjs.extend(utc)

const { Text } = Typography

interface Props {
  onGoToTasks?: () => void
}

export function OverviewDashboard({ onGoToTasks }: Props) {
  const { token } = theme.useToken()
  const { data, isLoading, error } = useTasks({ size: 1 })
  const { data: llmStats, isLoading: isLlmLoading } = useLLMStats()
  const stats = data?.stats

  if (isLoading) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: 12 }}>
          <Text type="secondary">Loading platform overview…</Text>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="error"
        message="Failed to load dashboard"
        description={(error as Error)?.message}
        style={{ margin: 16 }}
      />
    )
  }

  const total    = stats?.total      ?? 0
  const complete = stats?.complete   ?? 0
  const running  = (stats?.pending ?? 0) + (stats?.processing ?? 0)
  const errors   = stats?.error      ?? 0
  const pct      = total > 0 ? Math.round((complete / total) * 100) : 0

  const statCards = [
    {
      label: 'Insight Tasks',
      value: stats?.insights ?? 0,
      color: token.colorPrimary,
      icon: <BulbOutlined />,
    },
    {
      label: 'Enrichment Tasks',
      value: stats?.enrichments ?? 0,
      color: '#722ed1',
      icon: <RobotOutlined />,
    },
    {
      label: 'In Progress',
      value: running,
      color: token.colorInfo,
      icon: <SyncOutlined spin={running > 0} />,
    },
    {
      label: 'Complete',
      value: complete,
      color: token.colorSuccess,
      icon: <CheckCircleOutlined />,
    },
    {
      label: 'Errors',
      value: errors,
      color: errors > 0 ? token.colorError : token.colorSuccess,
      icon: <WarningOutlined />,
    },
  ]

  return (
    <div style={{ padding: '0 20px 24px' }}>
      <PageHeader 
        title="Platform Overview" 
        icon={<DashboardOutlined />}
        subtitle="Real-time status of background intelligence processing and LLM performance."
        info="This dashboard monitors the asynchronous processing of documents into structured intelligence. All metrics auto-refresh every 10 seconds."
        extra={
          <Space>
            {onGoToTasks && (
              <Button type="primary" icon={<RightOutlined />} onClick={onGoToTasks} size="small">
                Task Monitor
              </Button>
            )}
          </Space>
        }
      />

      <Space direction="vertical" size={20} style={{ width: '100%' }}>
        {/* Stat cards */}
        <Row gutter={[16, 16]}>
          {statCards.map((s) => (
            <Col key={s.label} xs={12} sm={8} md={24 / statCards.length}>
              <Card
                size="small"
                variant="borderless"
                style={{
                  textAlign: 'center',
                  background: token.colorBgContainer,
                  boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
                  border: `1px solid ${token.colorBorderSecondary}`,
                }}
              >
                <Statistic
                  title={
                    <Space style={{ fontSize: 12 }}>
                      {s.icon}
                      {s.label}
                    </Space>
                  }
                  value={s.value}
                  styles={{ content: { fontSize: 24, fontWeight: 600, color: s.color } }}
                />
              </Card>
            </Col>
          ))}
        </Row>

        {/* Completion bar */}
        <Card
          size="small"
          variant="borderless"
          style={{ 
            background: token.colorBgContainer,
            border: `1px solid ${token.colorBorderSecondary}`,
            boxShadow: '0 1px 2px rgba(0,0,0,0.03)'
          }}
        >
          <div style={{ padding: '4px 8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <Text strong style={{ fontSize: 13 }}>Overall Task Completion</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>{complete} / {total} tasks</Text>
            </div>
            <Progress
              percent={pct}
              size="small"
              status={errors > 0 ? 'exception' : 'active'}
              strokeColor={token.colorSuccess}
              style={{ marginBottom: 0 }}
            />
          </div>
        </Card>

        {/* LLM Engine Details */}
        <Card
          size="small"
          variant="borderless"
          title={
            <Space>
              <SettingOutlined style={{ color: token.colorPrimary }} />
              <span style={{ fontSize: 14, fontWeight: 600 }}>LLM Engine Configuration</span>
            </Space>
          }
          style={{ 
            background: token.colorBgContainer,
            border: `1px solid ${token.colorBorderSecondary}`,
            boxShadow: '0 1px 2px rgba(0,0,0,0.03)'
          }}
        >
          {isLlmLoading ? (
            <div style={{ textAlign: 'center', padding: 20 }}><Spin size="small" /></div>
          ) : llmStats?.error ? (
            <Alert type="warning" message="Could not fetch detailed model info" showIcon />
          ) : (
            <Descriptions column={{ xs: 1, sm: 2, md: 3, lg: 4 }} size="small" bordered={false}>
              <Descriptions.Item label={<Text type="secondary">Model</Text>}>
                <Text strong>{llmStats?.model_path?.split('/').pop() ?? llmStats?.model ?? 'Unknown'}</Text>
              </Descriptions.Item>
              <Descriptions.Item label={<Text type="secondary">Architecture</Text>}>
                {llmStats?.model_type ?? llmStats?.architectures?.[0] ?? '—'}
              </Descriptions.Item>
              <Descriptions.Item label={<Text type="secondary">Quantization</Text>}>
                <Tag color="processing" style={{ borderRadius: 4, fontSize: 10 }}>{llmStats?.quantization ?? '—'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label={<Text type="secondary">Context Window</Text>}>
                {(llmStats?.max_model_len ?? llmStats?.context_length ?? 0).toLocaleString()} tokens
              </Descriptions.Item>
              <Descriptions.Item label={<Text type="secondary">Inference Type</Text>}>
                {llmStats?.dtype ?? '—'}
              </Descriptions.Item>
              <Descriptions.Item label={<Text type="secondary">KV Cache</Text>}>
                {llmStats?.kv_cache_dtype ?? '—'}
              </Descriptions.Item>
              <Descriptions.Item label={<Text type="secondary">VRAM Utilization</Text>}>
                {llmStats?.mem_fraction_static != null ? `${(llmStats.mem_fraction_static * 100).toFixed(0)}%` : '—'}
              </Descriptions.Item>
              <Descriptions.Item label={<Text type="secondary">Concurrent Slots</Text>}>
                {llmStats?.max_running_requests ?? '—'}
              </Descriptions.Item>
            </Descriptions>
          )}
        </Card>
      </Space>
    </div>
  )
}
