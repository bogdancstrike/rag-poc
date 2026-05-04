import {
  Card, Col, Row, Typography, Tag, Space, Spin, Alert,
  Button, Progress, theme, Statistic, Descriptions,
} from 'antd'
import {
  DashboardOutlined, CheckCircleOutlined, SyncOutlined,
  WarningOutlined, RightOutlined, BulbOutlined, RobotOutlined,
  SettingOutlined, ThunderboltOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { useTasks } from '@/hooks/useTasks'
import { useLLMStats, useLLMLive } from '@/hooks/useLLMStats'
import { PageHeader } from '../common/PageHeader'

dayjs.extend(utc)

const { Text } = Typography

/**
 * Format a byte count into a short human-readable string (e.g. 1.2 GB,
 * 350 MB, 12 KB). Used by the Live LLM Stats card for VRAM figures.
 */
function fmtBytes(b: number | null | undefined): string {
  if (b == null) return '—'
  if (b < 1024)            return `${b} B`
  if (b < 1024 ** 2)       return `${(b / 1024).toFixed(0)} KB`
  if (b < 1024 ** 3)       return `${(b / 1024 ** 2).toFixed(1)} MB`
  return `${(b / 1024 ** 3).toFixed(2)} GB`
}

interface Props {
  onGoToTasks?: () => void
}

export function OverviewDashboard({ onGoToTasks }: Props) {
  const { token } = theme.useToken()
  const { data, isLoading, error } = useTasks({ size: 1 })
  const { data: llmStats, isLoading: isLlmLoading } = useLLMStats()
  const { data: llmLive } = useLLMLive()
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

        {/* Live LLM stats — scraped from Prometheus /metrics every 3 s.
            vLLM only; SGLang shows the "not available" state cleanly. */}
        <Card
          size="small"
          variant="borderless"
          title={
            <Space>
              <ThunderboltOutlined style={{ color: token.colorWarning }} />
              <span style={{ fontSize: 14, fontWeight: 600 }}>Live LLM Stats</span>
              {llmLive?.available && (
                <Tag color="success" style={{ fontSize: 10, marginLeft: 4 }}>
                  <SyncOutlined spin /> live
                </Tag>
              )}
            </Space>
          }
          style={{
            background: token.colorBgContainer,
            border: `1px solid ${token.colorBorderSecondary}`,
            boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
          }}
        >
          {!llmLive ? (
            <div style={{ textAlign: 'center', padding: 20 }}><Spin size="small" /></div>
          ) : !llmLive.available ? (
            <Alert
              type="info"
              showIcon
              message="Live metrics unavailable"
              description={
                llmLive.reason
                  ? `Inference server didn't expose /metrics: ${llmLive.reason}`
                  : 'The current inference backend does not expose Prometheus metrics.'
              }
            />
          ) : (
            <>
              {/* Helper: bytes -> short human string (1.2 GB / 350 MB / 12 KB) */}
              <Row gutter={[16, 16]}>
                <Col xs={12} sm={8} md={6}>
                  <Statistic
                    title={<Text type="secondary">Requests Running</Text>}
                    value={llmLive.requests_running ?? 0}
                    suffix={
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        / {llmStats?.max_running_requests ?? '?'}
                      </Text>
                    }
                    valueStyle={{
                      color: (llmLive.requests_running ?? 0) > 0
                        ? token.colorPrimary
                        : token.colorTextSecondary,
                    }}
                  />
                </Col>
                <Col xs={12} sm={8} md={6}>
                  <Statistic
                    title={<Text type="secondary">Requests Waiting</Text>}
                    value={llmLive.requests_waiting ?? 0}
                    valueStyle={{
                      color: (llmLive.requests_waiting ?? 0) > 0
                        ? token.colorWarning
                        : token.colorTextSecondary,
                    }}
                  />
                </Col>
                <Col xs={12} sm={8} md={6}>
                  <Statistic
                    title={<Text type="secondary">Preemptions (total)</Text>}
                    value={llmLive.preemptions_total ?? 0}
                    valueStyle={{ color: token.colorTextSecondary }}
                  />
                </Col>
                <Col xs={12} sm={8} md={6}>
                  <Statistic
                    title={<Text type="secondary">Prefix Cache Hit Rate</Text>}
                    value={
                      llmLive.prefix_cache_hit_rate != null
                        ? (llmLive.prefix_cache_hit_rate * 100).toFixed(1)
                        : '—'
                    }
                    suffix={llmLive.prefix_cache_hit_rate != null ? '%' : ''}
                    valueStyle={{ color: token.colorSuccess }}
                  />
                </Col>
              </Row>

              {/* VRAM row — derived from KV-cache tokens × bytes-per-token
                  (computed from the model's HF config.json). */}
              {(llmLive.vram_per_request_bytes != null ||
                llmLive.kv_total_bytes != null) && (
                <Row gutter={[16, 16]} style={{ marginTop: 12 }}>
                  <Col xs={12} sm={8} md={8}>
                    <Statistic
                      title={
                        <Text type="secondary">
                          VRAM / Request
                          {llmLive.vram_per_request_basis === 'theoretical' && (
                            <Tag style={{ marginLeft: 6, fontSize: 10 }}>
                              theoretical max
                            </Tag>
                          )}
                          {llmLive.vram_per_request_basis === 'actual' && (
                            <Tag color="processing" style={{ marginLeft: 6, fontSize: 10 }}>
                              live
                            </Tag>
                          )}
                        </Text>
                      }
                      value={fmtBytes(llmLive.vram_per_request_bytes)}
                      valueStyle={{ color: token.colorPrimary, fontSize: 22 }}
                    />
                  </Col>
                  <Col xs={12} sm={8} md={8}>
                    <Statistic
                      title={<Text type="secondary">KV Cache In Use</Text>}
                      value={fmtBytes(llmLive.kv_used_bytes)}
                      suffix={
                        llmLive.kv_total_bytes != null ? (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            / {fmtBytes(llmLive.kv_total_bytes)}
                          </Text>
                        ) : null
                      }
                      valueStyle={{ fontSize: 22 }}
                    />
                  </Col>
                  <Col xs={12} sm={8} md={8}>
                    <Statistic
                      title={<Text type="secondary">Bytes / Token</Text>}
                      value={
                        llmLive.kv_bytes_per_token != null
                          ? `${(llmLive.kv_bytes_per_token / 1024).toFixed(1)} KB`
                          : '—'
                      }
                      valueStyle={{ fontSize: 22, color: token.colorTextSecondary }}
                    />
                  </Col>
                </Row>
              )}

              <div style={{ marginTop: 16 }}>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    <DatabaseOutlined /> KV Cache
                    {llmLive.kv_cache_dtype && (
                      <Tag style={{ marginLeft: 6, fontSize: 10 }}>
                        {llmLive.kv_cache_dtype}
                      </Tag>
                    )}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {llmLive.kv_cache_tokens_used != null && llmLive.kv_cache_capacity_tokens != null
                      ? `${llmLive.kv_cache_tokens_used.toLocaleString()} / ${llmLive.kv_cache_capacity_tokens.toLocaleString()} tokens`
                      : llmLive.kv_cache_capacity_tokens != null
                        ? `capacity ${llmLive.kv_cache_capacity_tokens.toLocaleString()} tokens`
                        : ''}
                  </Text>
                </Space>
                <Progress
                  percent={
                    llmLive.kv_cache_usage_perc != null
                      ? +(llmLive.kv_cache_usage_perc * 100).toFixed(1)
                      : 0
                  }
                  size="small"
                  status={
                    (llmLive.kv_cache_usage_perc ?? 0) > 0.9 ? 'exception' :
                    (llmLive.kv_cache_usage_perc ?? 0) > 0.7 ? 'active' : 'normal'
                  }
                />
              </div>

              {llmLive.gpu_memory_utilization != null && (
                <div style={{ marginTop: 12 }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      VRAM dedicated to LLM (configured)
                    </Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {llmLive.kv_cache_gpu_blocks != null && llmLive.kv_cache_block_size != null
                        ? `${llmLive.kv_cache_gpu_blocks.toLocaleString()} blocks × ${llmLive.kv_cache_block_size} tokens`
                        : ''}
                    </Text>
                  </Space>
                  <Progress
                    percent={+(llmLive.gpu_memory_utilization * 100).toFixed(0)}
                    size="small"
                    strokeColor={token.colorPrimary}
                  />
                </div>
              )}

              <Row gutter={[16, 8]} style={{ marginTop: 16 }}>
                <Col xs={12} sm={12} md={12}>
                  <Statistic
                    title={<Text type="secondary" style={{ fontSize: 11 }}>Prompt tokens (lifetime)</Text>}
                    value={llmLive.prompt_tokens_total ?? 0}
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
                <Col xs={12} sm={12} md={12}>
                  <Statistic
                    title={<Text type="secondary" style={{ fontSize: 11 }}>Generation tokens (lifetime)</Text>}
                    value={llmLive.generation_tokens_total ?? 0}
                    valueStyle={{ fontSize: 18 }}
                  />
                </Col>
              </Row>
            </>
          )}
        </Card>
      </Space>
    </div>
  )
}
