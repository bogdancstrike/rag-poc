import { useMemo } from 'react'
import { Row, Col, Card, Statistic, Typography, Table, theme, Tooltip, Empty } from 'antd'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RTooltip,
  ResponsiveContainer, LineChart, Line, Legend, Cell,
} from 'recharts'
import dayjs from 'dayjs'
import { useTaskAnalytics } from '@/hooks/useTasks'
import type { TimingRow } from '@/api/tasks'

const { Text } = Typography

function ms(val: number | null): string {
  if (val == null) return '—'
  if (val < 1000) return `${val} ms`
  if (val < 60_000) return `${(val / 1000).toFixed(1)} s`
  return `${(val / 60_000).toFixed(1)} m`
}

interface Props {
  datasource?: string
  category?: string
}

export function TaskAnalyticsPanel({ datasource, category }: Props) {
  const { token } = theme.useToken()
  const { data, isLoading } = useTaskAnalytics(datasource || undefined, category || undefined)

  // ── Throughput bar chart ────────────────────────────────────────────────────
  const throughputData = useMemo(() => {
    if (!data) return []
    const order = ['5m', '1h', '12h', '1d', '7d']
    return order.map((w) => ({ window: w, completed: data.throughput[w] ?? 0 }))
  }, [data])

  // ── Time series line chart (hourly buckets) ─────────────────────────────────
  const timeSeriesData = useMemo(() => {
    if (!data) return []
    return data.time_series.map((p) => ({
      time: dayjs(p.ts).format('MM-DD HH:00'),
      count: p.count,
    }))
  }, [data])

  // ── Status distribution bars ────────────────────────────────────────────────
  const statusData = useMemo(() => {
    if (!data) return []
    return Object.entries(data.status_dist).map(([s, v]) => ({ status: s, count: v }))
  }, [data])

  // ── Type distribution ───────────────────────────────────────────────────────
  const typeData = useMemo(() => {
    if (!data) return []
    return Object.entries(data.type_dist).map(([t, v]) => ({ type: t, count: v }))
  }, [data])

  // ── Overall avg timings (across all task types) ─────────────────────────────
  const overallAvg = useMemo(() => {
    if (!data?.timing.length) return null
    const all = data.timing
    const avgOf = (key: keyof TimingRow) => {
      const vals = all.map((r) => r[key] as number | null).filter((v): v is number => v != null)
      return vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : null
    }
    return {
      queue: avgOf('avg_queue_ms'),
      exec:  avgOf('avg_exec_ms'),
      total: avgOf('avg_total_ms'),
    }
  }, [data])

  const STATUS_COLORS: Record<string, string> = {
    complete:   token.colorSuccess,
    processing: token.colorPrimary,
    pending:    token.colorWarning,
    error:      token.colorError,
  }

  const timingColumns = [
    { title: 'Category',   dataIndex: 'category',     key: 'category',     width: 100 },
    { title: 'Type',       dataIndex: 'task_type',    key: 'task_type',    width: 100 },
    { title: 'Samples',    dataIndex: 'sample_count', key: 'sample_count', width: 80,  align: 'right' as const },
    {
      title: 'Avg Queue',
      dataIndex: 'avg_queue_ms',
      key: 'avg_queue_ms',
      width: 110,
      align: 'right' as const,
      render: (v: number | null) => (
        <Tooltip title="Time between task created and worker picked it up">
          <Text style={{ fontFamily: 'monospace', fontSize: 12 }}>{ms(v)}</Text>
        </Tooltip>
      ),
    },
    {
      title: 'Avg Exec',
      dataIndex: 'avg_exec_ms',
      key: 'avg_exec_ms',
      width: 110,
      align: 'right' as const,
      render: (v: number | null) => (
        <Tooltip title="Time from worker start to completion">
          <Text style={{ fontFamily: 'monospace', fontSize: 12 }}>{ms(v)}</Text>
        </Tooltip>
      ),
    },
    {
      title: 'Avg Total',
      dataIndex: 'avg_total_ms',
      key: 'avg_total_ms',
      width: 110,
      align: 'right' as const,
      render: (v: number | null) => (
        <Tooltip title="End-to-end: created → complete">
          <Text style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>{ms(v)}</Text>
        </Tooltip>
      ),
    },
  ]

  if (!data && !isLoading) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* ── Overall timing KPIs ─────────────────────────────────────────── */}
      <Row gutter={[10, 10]}>
        {[
          { label: 'Avg Queue Time',  value: overallAvg?.queue ?? null, tip: 'Created → worker picked up' },
          { label: 'Avg Exec Time',   value: overallAvg?.exec  ?? null, tip: 'Worker start → complete'    },
          { label: 'Avg Total Time',  value: overallAvg?.total ?? null, tip: 'Created → complete'         },
        ].map(({ label, value, tip }) => (
          <Col key={label} xs={24} sm={8}>
            <Tooltip title={tip}>
              <Card size="small" variant="borderless"
                style={{ border: `1px solid ${token.colorBorderSecondary}`, textAlign: 'center' }}>
                <Statistic
                  title={<Text style={{ fontSize: 11 }}>{label}</Text>}
                  value={value != null ? ms(value) : '—'}
                  valueStyle={{ fontSize: 20, fontFamily: 'monospace', color: token.colorPrimary }}
                />
              </Card>
            </Tooltip>
          </Col>
        ))}
      </Row>

      {/* ── Charts row ─────────────────────────────────────────────────── */}
      <Row gutter={[12, 12]}>

        {/* Throughput by window */}
        <Col xs={24} md={12}>
          <Card size="small" title="Completed tasks by window"
            style={{ border: `1px solid ${token.colorBorderSecondary}` }}>
            {throughputData.every((d) => d.completed === 0) ? (
              <Empty description="No completed tasks yet" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: '24px 0' }} />
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={throughputData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={token.colorBorderSecondary} />
                  <XAxis dataKey="window" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <RTooltip formatter={(v) => [v, 'completed']} />
                  <Bar dataKey="completed" fill={token.colorPrimary} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>

        {/* Status distribution */}
        <Col xs={24} md={6}>
          <Card size="small" title="Status distribution"
            style={{ border: `1px solid ${token.colorBorderSecondary}` }}>
            {!statusData.length ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: '24px 0' }} />
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={statusData} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={token.colorBorderSecondary} horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} />
                  <YAxis dataKey="status" type="category" tick={{ fontSize: 11 }} width={72} />
                  <RTooltip />
                  <Bar dataKey="count" radius={[0, 3, 3, 0]}>
                    {statusData.map((entry) => (
                      <Cell key={entry.status} fill={STATUS_COLORS[entry.status] ?? token.colorFill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>

        {/* Type distribution */}
        <Col xs={24} md={6}>
          <Card size="small" title="Task type distribution"
            style={{ border: `1px solid ${token.colorBorderSecondary}` }}>
            {!typeData.length ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: '24px 0' }} />
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={typeData} layout="vertical" margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={token.colorBorderSecondary} horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} />
                  <YAxis dataKey="type" type="category" tick={{ fontSize: 11 }} width={80} />
                  <RTooltip />
                  <Bar dataKey="count" fill="#722ed1" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Col>
      </Row>

      {/* ── Time series (7d hourly completed tasks) ─────────────────────── */}
      {timeSeriesData.length > 1 && (
        <Card size="small" title="Completed tasks over time (7 days, hourly)"
          style={{ border: `1px solid ${token.colorBorderSecondary}` }}>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={timeSeriesData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={token.colorBorderSecondary} />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
              <RTooltip />
              <Legend />
              <Line type="monotone" dataKey="count" stroke={token.colorPrimary} dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* ── Per-type timing table ────────────────────────────────────────── */}
      {data?.timing.length ? (
        <Card size="small" title="Timing breakdown by task type"
          style={{ border: `1px solid ${token.colorBorderSecondary}` }}>
          <Table<TimingRow>
            rowKey={(r) => `${r.category}_${r.task_type}`}
            dataSource={data.timing}
            columns={timingColumns}
            size="small"
            pagination={false}
          />
        </Card>
      ) : null}
    </div>
  )
}
