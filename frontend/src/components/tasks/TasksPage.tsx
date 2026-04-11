import { useState, useMemo, useRef, useEffect } from 'react'
import {
  Table, Tag, Button, Space, Tooltip, Popconfirm, Typography, Badge,
  Select, Segmented, DatePicker, Row, Col, Card, Statistic, theme,
  Alert, Input, Collapse,
} from 'antd'
import {
  ReloadOutlined, DeleteOutlined, CheckCircleOutlined, SyncOutlined,
  ClockCircleOutlined, WarningOutlined, ClearOutlined,
  RightOutlined, RobotOutlined, BulbOutlined, BarChartOutlined, SearchOutlined,
} from '@ant-design/icons'
import type { ColumnsType, SortOrder, FilterDropdownProps } from 'antd/es/table/interface'
import type { InputRef } from 'antd'
import { useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useTasks, useRestartTask, useDeleteTask } from '@/hooks/useTasks'
import type { Task, TaskStatus, TaskCategory, TaskFilters } from '@/api/tasks'
import { useIndices } from '@/hooks/useExplore'
import { TaskAnalyticsPanel } from './TaskAnalyticsPanel'

dayjs.extend(utc)
dayjs.extend(relativeTime)

const { Text, Title } = Typography
const { RangePicker } = DatePicker

// ── Status helpers ──────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  pending:    'default',
  processing: 'processing',
  complete:   'success',
  error:      'error',
}

function StatusTag({ status }: { status: string }) {
  const icons: Record<string, any> = {
    pending:    <ClockCircleOutlined />,
    processing: <SyncOutlined spin />,
    complete:   <CheckCircleOutlined />,
    error:      <WarningOutlined />,
  }
  return (
    <Tag icon={icons[status]} color={STATUS_COLOR[status] ?? 'default'}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </Tag>
  )
}

function LocalTimestamp({ value }: { value?: string | null }) {
  if (!value) return <Text type="secondary">—</Text>
  const local = dayjs.utc(value).local()
  return (
    <Tooltip title={`UTC: ${value}`}>
      <Text style={{ fontSize: 12 }}>{local.format('MM-DD HH:mm:ss')}</Text>
    </Tooltip>
  )
}

function Duration({ from, to }: { from?: string | null; to?: string | null }) {
  if (!from || !to) return <Text type="secondary">—</Text>
  const ms = dayjs(to).diff(dayjs(from))
  if (ms < 0) return <Text type="secondary">—</Text>
  if (ms < 1000) return <Text style={{ fontSize: 12 }}>{ms} ms</Text>
  if (ms < 60_000) return <Text style={{ fontSize: 12 }}>{(ms / 1000).toFixed(1)} s</Text>
  return <Text style={{ fontSize: 12 }}>{(ms / 60_000).toFixed(1)} m</Text>
}

// ── Queue routing ────────────────────────────────────────────────────────────
// Mirrors kafka_producer.py: insight_ai / enrich_doc / enrich_field → llm_tasks
//                            insight_stats                           → fast_tasks
const QUEUE_TYPE: Record<string, 'llm' | 'fast'> = {
  summary:    'llm',
  graph:      'llm',
  enrichment: 'llm',
  stats:      'fast',
}

const QUEUE_LABEL: Record<'llm' | 'fast', { label: string; color: string; title: string }> = {
  llm:  { label: 'LLM',  color: 'purple', title: 'Routed through llm_tasks topic (bounded by LLM_PARALLEL)' },
  fast: { label: 'FAST', color: 'cyan',   title: 'Routed through fast_tasks topic (no LLM, always 4 workers)' },
}

function QueueTag({ taskType }: { taskType: string }) {
  const q = QUEUE_TYPE[taskType]
  if (!q) return null
  const { label, color, title } = QUEUE_LABEL[q]
  return (
    <Tooltip title={title}>
      <Tag color={color} style={{ fontSize: 9, padding: '0 4px', lineHeight: '16px', marginTop: 2 }}>
        {label}
      </Tag>
    </Tooltip>
  )
}

// ── Props ───────────────────────────────────────────────────────────────────

interface Props {
  onViewTask?: (task: Task) => void
}

// ── Main component ──────────────────────────────────────────────────────────

export function TasksPage({ onViewTask }: Props) {
  const { token } = theme.useToken()
  const { data: indices } = useIndices()
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialise from URL so refresh / shared links restore the same view
  const [filters, setFilters] = useState<TaskFilters>(() => ({
    sort:           searchParams.get('sort')     || 'updated_at:desc',
    page:           Number(searchParams.get('page'))  || 1,
    size:           Number(searchParams.get('size'))  || 50,
    status:         (searchParams.get('status')   as TaskStatus)   || undefined,
    category:       (searchParams.get('category') as TaskCategory) || undefined,
    datasource:     searchParams.get('ds')       || undefined,
    task_type:      searchParams.get('type')     || undefined,
    created_after:  searchParams.get('after')    || undefined,
    created_before: searchParams.get('before')   || undefined,
  }))
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [showAnalytics, setShowAnalytics] = useState(() => searchParams.get('analytics') === '1')
  const searchInputRef = useRef<InputRef>(null)

  // Keep URL in sync whenever filters or analytics panel visibility changes
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      const set = (k: string, v: string | undefined) =>
        v ? next.set(k, v) : next.delete(k)

      set('sort',     filters.sort !== 'updated_at:desc' ? filters.sort : undefined)
      set('page',     filters.page && filters.page > 1   ? String(filters.page) : undefined)
      set('size',     filters.size && filters.size !== 50 ? String(filters.size) : undefined)
      set('status',   filters.status)
      set('category', filters.category)
      set('ds',       filters.datasource)
      set('type',     filters.task_type)
      set('after',    filters.created_after)
      set('before',   filters.created_before)
      set('analytics', showAnalytics ? '1' : undefined)
      return next
    }, { replace: true })
  }, [filters, showAnalytics])

  const { data, isLoading, error, refetch, isFetching } = useTasks(filters)
  const restartMut = useRestartTask()
  const deleteMut  = useDeleteTask()

  const tasks  = data?.tasks  ?? []
  const stats  = data?.stats  ?? {}
  const total  = data?.total  ?? 0

  const setFilter = (patch: Partial<TaskFilters>) =>
    setFilters((f) => ({ ...f, ...patch, page: 1 }))

  const resetFilters = () =>
    setFilters({ sort: 'updated_at:desc', page: 1, size: 50 })

  // Derive the sort state for antd Table column headers
  const [sortField, sortDir] = (filters.sort ?? 'updated_at:desc').split(':')

  const handleTableChange = (_: any, tableFilters: any, sorter: any) => {
    const patch: Partial<TaskFilters> = {}
    if (sorter?.columnKey && sorter?.order) {
      patch.sort = `${sorter.columnKey}:${sorter.order === 'ascend' ? 'asc' : 'desc'}`
    }
    // status filter comes from column filters
    if (tableFilters?.status?.length) {
      patch.status = tableFilters.status[0] as TaskStatus
    } else if (tableFilters?.status !== undefined) {
      patch.status = undefined
    }
    setFilters((f) => ({ ...f, ...patch, page: 1 }))
  }

  // Bulk delete
  const handleBulkDelete = () => {
    selectedKeys.forEach((id) => {
      const [cat, ds, key] = id.split('__')
      deleteMut.mutate({ category: cat as TaskCategory, datasource: ds, task: key })
    })
    setSelectedKeys([])
  }

  // ── Inline column search filter helper ────────────────────────────────────
  const colSearch = (filterKey: keyof TaskFilters, placeholder: string) => ({
    filterDropdown: ({ setSelectedKeys, selectedKeys, confirm, clearFilters }: FilterDropdownProps) => (
      <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <Input
          ref={searchInputRef}
          placeholder={placeholder}
          value={selectedKeys[0] as string}
          onChange={(e) => setSelectedKeys(e.target.value ? [e.target.value] : [])}
          onPressEnter={() => {
            confirm()
            setFilter({ [filterKey]: selectedKeys[0] as string || undefined })
          }}
          style={{ width: 180 }}
          size="small"
        />
        <Space>
          <Button
            type="primary" size="small" icon={<SearchOutlined />}
            onClick={() => {
              confirm()
              setFilter({ [filterKey]: selectedKeys[0] as string || undefined })
            }}
          >Search</Button>
          <Button size="small" onClick={() => {
            clearFilters?.()
            setFilter({ [filterKey]: undefined })
          }}>Reset</Button>
        </Space>
      </div>
    ),
    filterIcon: (filtered: boolean) => (
      <SearchOutlined style={{ color: filtered ? token.colorPrimary : undefined }} />
    ),
    filterDropdownProps: {
      onOpenChange: (open: boolean) => {
        if (open) setTimeout(() => searchInputRef.current?.select(), 100)
      },
    },
  })

  const columns: ColumnsType<Task> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 160,
      filteredValue: null,
      render: (id: string, r: Task) => (
        <Space orientation="vertical" size={0}>
          <Tooltip title={id}>
            <Text code style={{ fontSize: 11 }}>{id.slice(0, 22)}…</Text>
          </Tooltip>
          <Tag
            color={r.category === 'insight' ? 'blue' : 'purple'}
            style={{ fontSize: 10, margin: 0 }}
            icon={r.category === 'insight' ? <BulbOutlined /> : <RobotOutlined />}
          >
            {r.category}
          </Tag>
        </Space>
      ),
    },
    {
      title: 'Type',
      dataIndex: 'task_type',
      key: 'task_type',
      width: 120,
      ...colSearch('task_type', 'Filter by type'),
      filteredValue: filters.task_type ? [filters.task_type] : null,
      render: (v: string) => (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
          <Tag>{v}</Tag>
          <QueueTag taskType={v} />
        </div>
      ),
    },
    {
      title: 'Datasource',
      dataIndex: 'datasource',
      key: 'datasource',
      width: 140,
      ellipsis: true,
      sortOrder: sortField === 'datasource' ? (sortDir + 'end') as SortOrder : undefined,
      sorter: true,
      ...colSearch('datasource', 'Filter by datasource'),
      filteredValue: filters.datasource ? [filters.datasource] : null,
      render: (v: string) => <Text style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: 'Doc ID',
      dataIndex: 'doc_id',
      key: 'doc_id',
      width: 130,
      ellipsis: true,
      filteredValue: null,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text style={{ fontSize: 11, fontFamily: 'monospace' }}>{v.slice(0, 14)}…</Text>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      sortOrder: sortField === 'status' ? (sortDir + 'end') as SortOrder : undefined,
      sorter: true,
      filters: [
        { text: 'Pending',    value: 'pending'    },
        { text: 'Processing', value: 'processing' },
        { text: 'Complete',   value: 'complete'   },
        { text: 'Error',      value: 'error'      },
      ],
      filteredValue: filters.status ? [filters.status] : null,
      onFilter: () => true, // server-side — just track selection
      filterMultiple: false,
      render: (v: string) => <StatusTag status={v} />,
    },
    {
      title: 'Retries',
      dataIndex: 'retry_count',
      key: 'retry_count',
      width: 70,
      align: 'center',
      filteredValue: null,
      sortOrder: sortField === 'retry_count' ? (sortDir + 'end') as SortOrder : undefined,
      sorter: true,
      render: (v: number) =>
        v > 0 ? <Badge count={v} color={v > 2 ? 'red' : 'orange'} /> : <Text type="secondary">0</Text>,
    },
    {
      title: 'Created',
      dataIndex: 'generated_at',
      key: 'generated_at',
      width: 130,
      filteredValue: null,
      sortOrder: sortField === 'generated_at' ? (sortDir + 'end') as SortOrder : undefined,
      sorter: true,
      render: (v: string) => <LocalTimestamp value={v} />,
    },
    {
      title: 'Started',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 130,
      filteredValue: null,
      sortOrder: sortField === 'started_at' ? (sortDir + 'end') as SortOrder : undefined,
      sorter: true,
      render: (v: string) => <LocalTimestamp value={v} />,
    },
    {
      title: 'Updated',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 130,
      filteredValue: null,
      sortOrder: sortField === 'updated_at' ? (sortDir + 'end') as SortOrder : undefined,
      sorter: true,
      defaultSortOrder: 'descend',
      render: (v: string) => <LocalTimestamp value={v} />,
    },
    {
      title: 'Queue',
      key: 'queue_time',
      width: 80,
      align: 'right' as const,
      filteredValue: null,
      render: (_: any, r: Task) => (
        <Tooltip title="Time between created and started (queue wait)">
          <Duration from={r.generated_at} to={r.started_at} />
        </Tooltip>
      ),
    },
    {
      title: 'Exec',
      key: 'exec_time',
      width: 80,
      align: 'right' as const,
      filteredValue: null,
      render: (_: any, r: Task) => (
        <Tooltip title="Execution time (started → last update)">
          <Duration from={r.started_at} to={r.updated_at} />
        </Tooltip>
      ),
    },
    {
      title: 'Error',
      dataIndex: 'error',
      key: 'error',
      ellipsis: true,
      ...colSearch('task_type', 'Filter by error text'),
      filteredValue: null,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text type="danger" style={{ fontSize: 11 }}>{v.slice(0, 60)}</Text>
          </Tooltip>
        ) : null,
    },
    {
      title: 'Actions',
      key: 'actions',
      fixed: 'right',
      width: 110,
      render: (_: any, r: Task) => {
        const taskKey = r.category === 'insight' ? r.task_type : r.doc_id ?? ''
        return (
          <Space size={2}>
            <Tooltip title="Restart">
              <Button
                size="small"
                type="text"
                icon={<ReloadOutlined />}
                loading={restartMut.isPending && (restartMut.variables as any)?.task === taskKey}
                onClick={(e) => {
                  e.stopPropagation()
                  restartMut.mutate({ category: r.category, datasource: r.datasource, task: taskKey })
                }}
              />
            </Tooltip>
            <Popconfirm
              title="Delete this task record?"
              okText="Delete"
              okButtonProps={{ danger: true }}
              onConfirm={(e) => {
                e?.stopPropagation()
                deleteMut.mutate({ category: r.category, datasource: r.datasource, task: taskKey })
              }}
              onCancel={(e) => e?.stopPropagation()}
            >
              <Tooltip title="Delete">
                <Button
                  size="small"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()}
                />
              </Tooltip>
            </Popconfirm>
            {onViewTask && (
              <Tooltip title="View detail">
                <Button
                  size="small"
                  type="text"
                  icon={<RightOutlined />}
                  onClick={(e) => {
                    e.stopPropagation()
                    onViewTask(r)
                  }}
                />
              </Tooltip>
            )}
          </Space>
        )
      },
    },
  ]

  const statCards = [
    { label: 'Total',      value: stats.total       ?? 0, color: token.colorText },
    { label: 'Pending',    value: stats.pending     ?? 0, color: token.colorWarning },
    { label: 'Processing', value: stats.processing  ?? 0, color: token.colorPrimary },
    { label: 'Complete',   value: stats.complete    ?? 0, color: token.colorSuccess },
    { label: 'Error',      value: stats.error       ?? 0, color: (stats.error ?? 0) > 0 ? token.colorError : token.colorSuccess },
    { label: 'Insights',   value: stats.insights    ?? 0, color: '#1890ff' },
    { label: 'Enrichments',value: stats.enrichments ?? 0, color: '#722ed1' },
  ]

  const hasFilters = !!(
    filters.status || filters.category || filters.datasource ||
    filters.task_type || filters.created_after || filters.created_before
  )

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, height: '100%', overflowY: 'auto' }}>

      {/* Header */}
      <Row align="middle" justify="space-between">
        <Space>
          <Title level={4} style={{ margin: 0 }}>Task Monitor</Title>
          <Tooltip title="Auto-refreshing every 2s">
            <Tag
              icon={<SyncOutlined spin={isFetching} />}
              color={isFetching ? 'processing' : 'default'}
              style={{ fontSize: 11 }}
            >
              LIVE
            </Tag>
          </Tooltip>
        </Space>
        <Space>
          {selectedKeys.length > 0 && (
            <Popconfirm
              title={`Delete ${selectedKeys.length} task(s)?`}
              okText="Delete"
              okButtonProps={{ danger: true }}
              onConfirm={handleBulkDelete}
            >
              <Button danger size="small" icon={<DeleteOutlined />}>
                Delete {selectedKeys.length} selected
              </Button>
            </Popconfirm>
          )}
          <Button
            size="small"
            icon={<BarChartOutlined />}
            type={showAnalytics ? 'primary' : 'default'}
            onClick={() => setShowAnalytics((v) => !v)}
          >
            Analytics
          </Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => refetch()}>
            Refresh
          </Button>
        </Space>
      </Row>

      {/* Stat cards */}
      <Row gutter={[10, 10]}>
        {statCards.map((s) => (
          <Col key={s.label} xs={12} sm={8} md={6} lg={3}>
            <Card size="small" variant="borderless"
              style={{ border: `1px solid ${token.colorBorderSecondary}`, textAlign: 'center' }}>
              <Statistic
                title={<Text style={{ fontSize: 11 }}>{s.label}</Text>}
                value={s.value}
                styles={{ content: { fontSize: 22, color: s.color } }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* Analytics panel */}
      {showAnalytics && (
        <Collapse
          ghost
          defaultActiveKey={['analytics']}
          style={{ background: token.colorFillAlter, borderRadius: token.borderRadius, border: `1px solid ${token.colorBorderSecondary}` }}
          items={[{
            key: 'analytics',
            label: <Text strong style={{ fontSize: 12 }}>Analytics & Charts</Text>,
            children: (
              <TaskAnalyticsPanel
                datasource={filters.datasource || undefined}
                category={filters.category || undefined}
              />
            ),
          }]}
        />
      )}

      {/* Filter bar */}
      <Card
        size="small"
        variant="borderless"
        style={{ border: `1px solid ${token.colorBorderSecondary}` }}
        styles={{ body: { padding: '10px 14px' } }}
      >
        <Row gutter={[10, 8]} align="middle" wrap>
          <Col>
            <Text type="secondary" style={{ fontSize: 11 }}>STATUS</Text>
            <div>
              <Segmented
                size="small"
                value={filters.status ?? ''}
                onChange={(v) => setFilter({ status: v as TaskStatus | '' })}
                options={[
                  { label: 'All',        value: '' },
                  { label: 'Pending',    value: 'pending' },
                  { label: 'Running',    value: 'processing' },
                  { label: 'Complete',   value: 'complete' },
                  { label: 'Error',      value: 'error' },
                ]}
              />
            </div>
          </Col>
          <Col>
            <Text type="secondary" style={{ fontSize: 11 }}>CATEGORY</Text>
            <div>
              <Select
                size="small"
                value={filters.category ?? ''}
                onChange={(v) => setFilter({ category: v as TaskCategory | '' })}
                style={{ width: 130 }}
                options={[
                  { label: 'All categories', value: '' },
                  { label: 'Insight',        value: 'insight' },
                  { label: 'Enrichment',     value: 'enrichment' },
                ]}
              />
            </div>
          </Col>
          <Col>
            <Text type="secondary" style={{ fontSize: 11 }}>DATASOURCE</Text>
            <div>
              <Select
                size="small"
                value={filters.datasource ?? ''}
                onChange={(v) => setFilter({ datasource: v })}
                style={{ width: 160 }}
                allowClear
                placeholder="All datasources"
                options={[
                  { label: 'All datasources', value: '' },
                  ...(indices ?? []).map((idx) => ({ label: idx, value: idx })),
                ]}
              />
            </div>
          </Col>
          <Col>
            <Text type="secondary" style={{ fontSize: 11 }}>TASK TYPE</Text>
            <div>
              <Select
                size="small"
                value={filters.task_type ?? ''}
                onChange={(v) => setFilter({ task_type: v })}
                style={{ width: 130 }}
                allowClear
                placeholder="All types"
                options={[
                  { label: 'All types',   value: '' },
                  { label: 'summary',     value: 'summary' },
                  { label: 'ner',         value: 'ner' },
                  { label: 'graph',       value: 'graph' },
                  { label: 'stats',       value: 'stats' },
                  { label: 'enrichment',  value: 'enrichment' },
                ]}
              />
            </div>
          </Col>
          <Col>
            <Text type="secondary" style={{ fontSize: 11 }}>DATE RANGE</Text>
            <div>
              <RangePicker
                size="small"
                showTime
                style={{ width: 340 }}
                onChange={(dates) => {
                  setFilter({
                    created_after:  dates?.[0]?.toISOString() ?? undefined,
                    created_before: dates?.[1]?.toISOString() ?? undefined,
                  })
                }}
              />
            </div>
          </Col>
          {hasFilters && (
            <Col style={{ alignSelf: 'flex-end' }}>
              <Button size="small" icon={<ClearOutlined />} onClick={resetFilters}>
                Reset
              </Button>
            </Col>
          )}
        </Row>
      </Card>

      {/* Error state */}
      {error && (
        <Alert type="error" message="Failed to load tasks" description={(error as Error).message} />
      )}

      {/* Task table */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <Table<Task>
          rowKey="id"
          dataSource={tasks}
          columns={columns}
          loading={isLoading}
          size="small"
          scroll={{ x: 1400, y: 'calc(100vh - 460px)' }}
          onChange={handleTableChange}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys as string[]),
          }}
          onRow={(r) => ({
            onClick: () => onViewTask?.(r),
            style: {
              cursor: onViewTask ? 'pointer' : 'default',
              background: r.status === 'error' ? 'rgba(255,77,79,0.04)' : undefined,
            },
          })}
          pagination={{
            current: filters.page ?? 1,
            pageSize: filters.size ?? 50,
            total,
            onChange: (p, s) => setFilters((f) => ({ ...f, page: p, size: s })),
            showSizeChanger: true,
            pageSizeOptions: ['10', '25', '50', '100', '200'],
            showTotal: (t) => `${t} tasks`,
            size: 'small',
          }}
        />
      </div>
    </div>
  )
}
