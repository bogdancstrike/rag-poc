import {
  Card, Col, Row, Typography, Tag, Space, Spin, Alert,
  Button, Tooltip, Progress, theme, Statistic, Descriptions,
} from 'antd'
import {
  DashboardOutlined, CheckCircleOutlined, SyncOutlined, ClockCircleOutlined,
  WarningOutlined, RightOutlined, BulbOutlined, RobotOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { useTasks } from '@/hooks/useTasks'
import { useLLMStats } from '@/hooks/useLLMStats'

dayjs.extend(utc)

const { Title, Text } = Typography

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
      color: '#1890ff',
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
      color: token.colorPrimary,
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
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header */}
      <Row align="middle" justify="space-between">
        <Space>
          <DashboardOutlined style={{ fontSize: 18, color: token.colorPrimary }} />
          <Title level={4} style={{ margin: 0 }}>Platform Overview</Title>
        </Space>
        <Space>
          <Text type="secondary" style={{ fontSize: 12 }}>Auto-refreshes every 10 s</Text>
          {onGoToTasks && (
            <Button size="small" icon={<RightOutlined />} onClick={onGoToTasks}>
              Task Monitor
            </Button>
          )}
        </Space>
      </Row>

      {/* Stat cards */}
      <Row gutter={[12, 12]}>
        {statCards.map((s) => (
          <Col key={s.label} xs={12} sm={8} md={24 / statCards.length}>
            <Card
              size="small"
              variant="borderless"
              style={{
                textAlign: 'center',
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
                styles={{ content: { fontSize: 28, color: s.color } }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* Completion bar */}
      <Card
        size="small"
        variant="borderless"
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Row align="middle" gutter={12}>
          <Col flex="auto">
            <Text strong style={{ fontSize: 12 }}>Overall task completion</Text>
            <Progress
              percent={pct}
              size="small"
              status={errors > 0 ? 'exception' : undefined}
              format={() => `${complete} / ${total}`}
              style={{ marginBottom: 0, marginTop: 4 }}
            />
          </Col>
        </Row>
      </Card>

      {/* LLM Engine Details */}
      <Card
        size="small"
        variant="borderless"
        title={
          <Space>
            <SettingOutlined style={{ color: token.colorPrimary }} />
            <span style={{ fontSize: 14 }}>LLM Engine Details</span>
          </Space>
        }
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
      >
        {isLlmLoading ? (
          <div style={{ textAlign: 'center', padding: 20 }}><Spin size="small" /></div>
        ) : llmStats?.error ? (
          <Alert type="warning" message="Could not fetch detailed model info" showIcon />
        ) : (
          <Descriptions column={{ xs: 1, sm: 2, md: 3, lg: 4 }} size="small" bordered>
            <Descriptions.Item label="Model">
              <Text strong>{llmStats?.model_path?.split('/').pop() ?? llmStats?.model ?? 'Unknown'}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Architecture">
              {llmStats?.model_type ?? llmStats?.architectures?.[0] ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Quantization">
              <Tag color="processing">{llmStats?.quantization ?? '—'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Context Window">
              {(llmStats?.max_model_len ?? llmStats?.context_length ?? 0).toLocaleString()} tokens
            </Descriptions.Item>
            <Descriptions.Item label="dtype">
              {llmStats?.dtype ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="KV Cache dtype">
              {llmStats?.kv_cache_dtype ?? '—'}
            </Descriptions.Item>
            <Descriptions.Item label="VRAM (static)">
              {llmStats?.mem_fraction_static != null ? `${(llmStats.mem_fraction_static * 100).toFixed(0)}%` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="Max Concurrent">
              {llmStats?.max_running_requests ?? '—'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Card>

      {/* Go-to link */}
      {onGoToTasks && (
        <Card
          size="small"
          variant="borderless"
          style={{
            border: `1px solid ${token.colorBorderSecondary}`,
            cursor: 'pointer',
          }}
          onClick={onGoToTasks}
        >
          <Row align="middle" justify="space-between">
            <Text>View all tasks with filters, sorting and detail view</Text>
            <Button type="link" icon={<RightOutlined />}>
              Open Task Monitor
            </Button>
          </Row>
        </Card>
      )}
    </div>
  )
}
