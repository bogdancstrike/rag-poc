import {
  Button, Descriptions, Tag, Space, Typography, Alert, Collapse,
  theme, Popconfirm, Tooltip, Row, Col, Spin, Card, Statistic,
} from 'antd'
import {
  ArrowLeftOutlined, ReloadOutlined, DeleteOutlined, CheckCircleOutlined,
  SyncOutlined, ClockCircleOutlined, WarningOutlined, BulbOutlined, RobotOutlined,
  LinkOutlined,
} from '@ant-design/icons'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import { useTask, useRestartTask, useDeleteTask } from '@/hooks/useTasks'
import type { Task } from '@/api/tasks'

dayjs.extend(utc)

const { Text, Title } = Typography

// ── Helpers ─────────────────────────────────────────────────────────────────

function LocalTimestamp({ value }: { value?: string | null }) {
  if (!value) return <Text type="secondary">—</Text>
  const local = dayjs.utc(value).local()
  return (
    <Tooltip title={`UTC: ${value}`}>
      <span>{local.format('YYYY-MM-DD HH:mm:ss')}</span>
    </Tooltip>
  )
}

function StatusTag({ status }: { status: string }) {
  const map: Record<string, any> = {
    pending:    { icon: <ClockCircleOutlined />, color: 'default' },
    processing: { icon: <SyncOutlined spin />,  color: 'processing' },
    complete:   { icon: <CheckCircleOutlined />, color: 'success' },
    error:      { icon: <WarningOutlined />,     color: 'error' },
  }
  const { icon, color } = map[status] ?? { icon: null, color: 'default' }
  return <Tag icon={icon} color={color}>{status}</Tag>
}

function durationLabel(from?: string | null, to?: string | null): string {
  if (!from || !to) return '—'
  const ms = dayjs(to).diff(dayjs(from))
  if (ms < 0) return '—'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  return `${(ms / 60_000).toFixed(1)} min`
}

// ── Latency bar ──────────────────────────────────────────────────────────────

function LatencyBar({ task }: { task: Task }) {
  const { token } = theme.useToken()
  const created = task.generated_at ? dayjs(task.generated_at) : null
  const started = task.started_at   ? dayjs(task.started_at)   : null
  const updated = task.updated_at   ? dayjs(task.updated_at)   : null

  if (!created || !updated) return null

  const totalMs  = Math.max(updated.diff(created), 1)
  const queueMs  = started ? Math.max(started.diff(created), 0) : 0
  const queuePct = Math.round((queueMs / totalMs) * 100)
  const execPct  = 100 - queuePct

  return (
    <div style={{ marginBottom: 20 }}>
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>
        LATENCY BREAKDOWN
      </Text>
      <div style={{ display: 'flex', borderRadius: 4, overflow: 'hidden', height: 22 }}>
        {queuePct > 0 && (
          <Tooltip title={`Queue wait: ${durationLabel(task.generated_at, task.started_at)}`}>
            <div style={{
              width: `${queuePct}%`, background: token.colorWarning,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {queuePct > 12 && (
                <Text style={{ fontSize: 10, color: '#fff' }}>Queue</Text>
              )}
            </div>
          </Tooltip>
        )}
        {execPct > 0 && (
          <Tooltip title={`Execution: ${durationLabel(task.started_at, task.updated_at)}`}>
            <div style={{
              width: `${execPct}%`,
              background: task.status === 'error' ? token.colorError : token.colorSuccess,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {execPct > 12 && (
                <Text style={{ fontSize: 10, color: '#fff' }}>Exec</Text>
              )}
            </div>
          </Tooltip>
        )}
      </div>
      <Row gutter={24} style={{ marginTop: 6 }}>
        <Col>
          <Text type="secondary" style={{ fontSize: 11 }}>Queue: </Text>
          <Text style={{ fontSize: 11 }}>{durationLabel(task.generated_at, task.started_at)}</Text>
        </Col>
        <Col>
          <Text type="secondary" style={{ fontSize: 11 }}>Execution: </Text>
          <Text style={{ fontSize: 11 }}>{durationLabel(task.started_at, task.updated_at)}</Text>
        </Col>
        <Col>
          <Text type="secondary" style={{ fontSize: 11 }}>Total: </Text>
          <Text style={{ fontSize: 11 }}>{durationLabel(task.generated_at, task.updated_at)}</Text>
        </Col>
      </Row>
    </div>
  )
}

// ── Timing stats card ────────────────────────────────────────────────────────

function TimingStats({ task }: { task: Task }) {
  const { token } = theme.useToken()

  const queueMs = task.generated_at && task.started_at
    ? Math.max(dayjs(task.started_at).diff(dayjs(task.generated_at)), 0)
    : null
  const execMs = task.started_at && task.updated_at && task.status !== 'pending'
    ? Math.max(dayjs(task.updated_at).diff(dayjs(task.started_at)), 0)
    : null
  const totalMs = task.generated_at && task.updated_at
    ? Math.max(dayjs(task.updated_at).diff(dayjs(task.generated_at)), 0)
    : null

  const fmt = (ms: number | null) => {
    if (ms == null) return '—'
    if (ms < 1000) return `${ms} ms`
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
    return `${(ms / 60_000).toFixed(1)} min`
  }

  const chartData = [
    { name: 'Queue',  ms: queueMs ?? 0, color: token.colorWarning  },
    { name: 'Exec',   ms: execMs  ?? 0, color: task.status === 'error' ? token.colorError : token.colorSuccess },
  ].filter((d) => d.ms > 0)

  return (
    <Card size="small" style={{ border: `1px solid ${token.colorBorderSecondary}`, marginBottom: 20 }}>
      <Row gutter={[16, 0]} style={{ marginBottom: chartData.length ? 16 : 0 }}>
        {[
          { label: 'Queue time',  value: fmt(queueMs), tip: 'Created → worker started', color: token.colorWarning   },
          { label: 'Exec time',   value: fmt(execMs),  tip: 'Worker start → complete',  color: token.colorSuccess   },
          { label: 'Total time',  value: fmt(totalMs), tip: 'Created → complete',        color: token.colorPrimary  },
        ].map(({ label, value, tip, color }) => (
          <Col key={label} xs={8}>
            <Tooltip title={tip}>
              <Statistic
                title={<span style={{ fontSize: 11 }}>{label}</span>}
                value={value}
                valueStyle={{ fontSize: 18, fontFamily: 'monospace', color }}
              />
            </Tooltip>
          </Col>
        ))}
      </Row>
      {chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={80}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 0, right: 24, left: 0, bottom: 0 }}>
            <XAxis type="number" hide />
            <YAxis dataKey="name" type="category" tick={{ fontSize: 11 }} width={46} />
            <RTooltip formatter={(v: number) => [fmt(v), 'duration']} />
            <Bar dataKey="ms" radius={[0, 4, 4, 0]}>
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Card>
  )
}

// ── Props ────────────────────────────────────────────────────────────────────

interface Props {
  taskId: string
  onBack: () => void
}

// ── Main component ──────────────────────────────────────────────────────────

export function TaskDetailPanel({ taskId, onBack }: Props) {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const { data: task, isLoading } = useTask(taskId)
  const restartMut = useRestartTask()
  const deleteMut  = useDeleteTask()

  if (isLoading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!task) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="warning"
          message="Task not found"
          action={<Button onClick={onBack}>Back</Button>}
        />
      </div>
    )
  }

  const taskKey = task.category === 'insight' ? task.task_type : (task.doc_id ?? '')

  const handleRestart = () =>
    restartMut.mutate({ category: task.category, datasource: task.datasource, task: taskKey })

  const handleDelete = () =>
    deleteMut.mutate(
      { category: task.category, datasource: task.datasource, task: taskKey },
      { onSuccess: onBack },
    )

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>

      {/* Back link */}
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} type="text" onClick={onBack}>
          Task Monitor
        </Button>
        <Text type="secondary">/</Text>
        <Text code style={{ fontSize: 11 }}>{taskId}</Text>
      </Space>

      {/* Title bar */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 20 }}>
        <Space>
          {task.category === 'insight'
            ? <BulbOutlined style={{ fontSize: 20, color: '#1890ff' }} />
            : <RobotOutlined style={{ fontSize: 20, color: '#722ed1' }} />}
          <Title level={4} style={{ margin: 0 }}>{task.task_type}</Title>
          <StatusTag status={task.status} />
          <Tag color={task.category === 'insight' ? 'blue' : 'purple'}>{task.category}</Tag>
        </Space>
        <Space>
          {/* Navigate to the relevant index page */}
          {task.datasource && task.category === 'enrichment' && task.doc_id ? (
            <Tooltip title="Open document in Data Exploration">
              <Button
                icon={<LinkOutlined />}
                onClick={() => navigate(`/index/${encodeURIComponent(task.datasource)}/${encodeURIComponent(task.doc_id!)}`)}
              >
                Go to doc
              </Button>
            </Tooltip>
          ) : task.datasource ? (
            <Tooltip title="Open Intelligence Report for this datasource">
              <Button
                icon={<LinkOutlined />}
                onClick={() => navigate(`/index/${encodeURIComponent(task.datasource)}`, { state: { tab: 'insights' } })}
              >
                Go to report
              </Button>
            </Tooltip>
          ) : null}
          <Button icon={<ReloadOutlined />} loading={restartMut.isPending} onClick={handleRestart}>
            Restart
          </Button>
          <Popconfirm
            title="Delete this task record?"
            okText="Delete"
            okButtonProps={{ danger: true }}
            onConfirm={handleDelete}
          >
            <Button danger icon={<DeleteOutlined />} loading={deleteMut.isPending}>Delete</Button>
          </Popconfirm>
        </Space>
      </Row>

      {/* Metadata */}
      <Descriptions bordered size="small" column={2} style={{ marginBottom: 20 }}>
        <Descriptions.Item label="Status"><StatusTag status={task.status} /></Descriptions.Item>
        <Descriptions.Item label="Category">
          <Tag color={task.category === 'insight' ? 'blue' : 'purple'}>{task.category}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Type"><Tag>{task.task_type}</Tag></Descriptions.Item>
        <Descriptions.Item label="Datasource"><Text code>{task.datasource}</Text></Descriptions.Item>
        {task.doc_id && (
          <Descriptions.Item label="Document ID" span={2}>
            <Text code style={{ fontSize: 11 }}>{task.doc_id}</Text>
          </Descriptions.Item>
        )}
        <Descriptions.Item label="Retries">
          {task.retry_count > 0
            ? <Tag color={task.retry_count > 2 ? 'red' : 'orange'}>{task.retry_count}</Tag>
            : <Text>0</Text>}
        </Descriptions.Item>
        <Descriptions.Item label="Has output">
          <Tag color={task.has_output ? 'success' : 'default'}>{task.has_output ? 'Yes' : 'No'}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="Created"><LocalTimestamp value={task.generated_at} /></Descriptions.Item>
        <Descriptions.Item label="Started"><LocalTimestamp value={task.started_at} /></Descriptions.Item>
        <Descriptions.Item label="Updated" span={2}><LocalTimestamp value={task.updated_at} /></Descriptions.Item>
        {task.sample_hash && (
          <Descriptions.Item label="Sample hash" span={2}>
            <Text code style={{ fontSize: 10 }}>{task.sample_hash.slice(0, 16)}…</Text>
          </Descriptions.Item>
        )}
      </Descriptions>

      {/* Timing stats */}
      <TimingStats task={task} />

      {/* Error */}
      {task.status === 'error' && task.error && (
        <Alert
          type="error"
          message="Task failed"
          description={task.error}
          style={{ marginBottom: 16 }}
          action={
            <Button size="small" icon={<ReloadOutlined />} onClick={handleRestart}
              loading={restartMut.isPending}>
              Retry
            </Button>
          }
        />
      )}

      {/* Running indicator */}
      {(task.status === 'pending' || task.status === 'processing') && (
        <Alert
          type="info"
          icon={<SyncOutlined spin />}
          showIcon
          message={task.status === 'pending' ? 'Waiting for worker…' : 'Task is running…'}
          description="Auto-refreshes every 3 s."
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Output payload */}
      {task.payload && (
        <Collapse
          size="small"
          defaultActiveKey={['payload']}
          items={[{
            key: 'payload',
            label: <Text strong>Task Output</Text>,
            children: (
              <pre style={{
                background: token.colorFillAlter,
                borderRadius: token.borderRadius,
                padding: 12, fontSize: 12,
                overflow: 'auto', maxHeight: 400, margin: 0,
              }}>
                {JSON.stringify(task.payload, null, 2)}
              </pre>
            ),
          }]}
        />
      )}
    </div>
  )
}
