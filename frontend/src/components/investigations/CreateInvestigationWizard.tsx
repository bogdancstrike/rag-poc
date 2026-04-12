import { useState, useEffect } from 'react'
import {
  Modal, Steps, Form, Input, Button, Space, Typography, Table, Tag,
  Alert, Switch, InputNumber, DatePicker, theme, Divider, Spin,
} from 'antd'
import {
  PlusOutlined, SearchOutlined, ApiOutlined, ThunderboltOutlined,
  YoutubeOutlined, GlobalOutlined, QuestionCircleOutlined,
} from '@ant-design/icons'
import type { SavedSearch } from '@/types'
import { useSavedSearches } from '@/hooks/useSavedSearches'
import { useCreateInvestigation } from '@/hooks/useInvestigations'
import { apiClient } from '@/api/client'
import dayjs from 'dayjs'

const { Text, Paragraph } = Typography
const { TextArea } = Input
const { RangePicker } = DatePicker

// ── Types ──────────────────────────────────────────────────────────────────────

interface ScraperConfig {
  platform: string
  urls: string
  dateRange: [string, string] | null
}

interface WizardState {
  name: string
  description: string
  selectedSearchIds: string[]
  scrapers: ScraperConfig[]
  autoEnrich: boolean
  autoEnrichCount: number
}

const INITIAL: WizardState = {
  name: '',
  description: '',
  selectedSearchIds: [],
  scrapers: [],
  autoEnrich: false,
  autoEnrichCount: 20,
}

const TOTAL_STEPS = 5   // 0=Name · 1=Searches · 2=Scrapers · 3=Enrich · 4=Review

const PLATFORMS = [
  { key: 'youtube',  label: 'YouTube',   icon: <YoutubeOutlined style={{ color: '#FF0000' }} />,  placeholder: 'https://youtube.com/@channel or playlist URL' },
  { key: 'facebook', label: 'Facebook',  icon: <GlobalOutlined  style={{ color: '#1877F2' }} />,  placeholder: 'https://facebook.com/group or page URL' },
  { key: 'tiktok',   label: 'TikTok',   icon: <GlobalOutlined  style={{ color: '#010101' }} />,  placeholder: 'https://tiktok.com/@account or hashtag URL' },
  { key: 'telegram', label: 'Telegram',  icon: <GlobalOutlined  style={{ color: '#2AABEE' }} />,  placeholder: 'https://t.me/channel or @handle' },
]

// ── Props ──────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean
  onClose: () => void
  /** Called on success. autoEnrichCount > 0 means auto-enrichment was requested. */
  onCreated: (id: string, autoEnrichCount: number) => void
}

// ── Component ──────────────────────────────────────────────────────────────────

export function CreateInvestigationWizard({ open, onClose, onCreated }: Props) {
  const { token } = theme.useToken()
  const [step, setStep]               = useState(0)
  const [form]                        = Form.useForm()
  const [state, setState]             = useState<WizardState>(INITIAL)
  const { data: searches = [], isLoading } = useSavedSearches()
  const createInv                     = useCreateInvestigation()

  // Scraper enabled platforms (separate from state.scrapers for toggle UX)
  const [enabledPlatforms, setEnabledPlatforms] = useState<Set<string>>(new Set())
  const [platformUrls, setPlatformUrls]         = useState<Record<string, string>>({})
  const [platformDates, setPlatformDates]       = useState<Record<string, [string, string] | null>>({})

  // Estimated total document count for the enrichment step
  const [estimatedTotal, setEstimatedTotal] = useState<number | null>(null)
  const [estimating, setEstimating]         = useState(false)

  // When entering enrichment step (step 3), compute a document count estimate
  // by querying each selected search's indices with its query string.
  useEffect(() => {
    if (step !== 3 || state.selectedSearchIds.length === 0) {
      if (step === 3 && state.selectedSearchIds.length === 0) setEstimatedTotal(0)
      return
    }
    setEstimating(true)
    setEstimatedTotal(null)

    const selectedSearches = searches.filter((s) => state.selectedSearchIds.includes(s.id))

    // For each search, query each of its index_patterns (or global) with limit=1
    // to get the total doc count. Sum across all searches (may double-count overlap
    // between searches, but serves as an upper-bound estimate).
    const tasks = selectedSearches.flatMap((s) => {
      const patterns: string[] = s.filters.index_patterns?.length
        ? s.filters.index_patterns
        : ['']   // empty = global explore (all indices)
      return patterns.map((ds) =>
        apiClient
          .get<{ total: number }>('/v1/documents', {
            params: {
              datasource:        ds || undefined,
              query:             s.query || undefined,
              filter_sentiment:  s.filters.sentiment || undefined,
              filter_date_from:  s.filters.date_from || undefined,
              filter_date_to:    s.filters.date_to   || undefined,
              limit:             1,
              offset:            0,
            },
          })
          .then((r) => r.data.total ?? 0)
          .catch(() => 0),
      )
    })

    Promise.all(tasks).then((counts) => {
      setEstimatedTotal(counts.reduce((a, b) => a + b, 0))
      setEstimating(false)
    })
  }, [step, state.selectedSearchIds, searches])

  const reset = () => {
    setStep(0)
    setState(INITIAL)
    form.resetFields()
    setEnabledPlatforms(new Set())
    setPlatformUrls({})
    setPlatformDates({})
    setEstimatedTotal(null)
    setEstimating(false)
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleNext = async () => {
    if (step === 0) {
      try {
        const vals = await form.validateFields()
        setState((s) => ({ ...s, name: vals.name, description: vals.description || '' }))
        setStep(1)
      } catch {}
      return
    }

    if (step === 1) {
      setStep(2)
      return
    }

    if (step === 2) {
      // Collect scraper configs from UI state
      const scrapers: ScraperConfig[] = PLATFORMS
        .filter((p) => enabledPlatforms.has(p.key))
        .map((p) => ({
          platform:  p.key,
          urls:      platformUrls[p.key] || '',
          dateRange: platformDates[p.key] || null,
        }))
      setState((s) => ({ ...s, scrapers }))
      setStep(3)
      return
    }

    if (step === 3) {
      setStep(4)
      return
    }
  }

  const handleBack = () => setStep((s) => Math.max(0, s - 1))

  const handleCreate = () => {
    createInv.mutate(
      {
        name:        state.name,
        description: state.description || undefined,
        search_ids:  state.selectedSearchIds,
      },
      {
        onSuccess: (inv) => {
          const enrichCount = state.autoEnrich ? state.autoEnrichCount : 0
          reset()
          onClose()
          onCreated(inv.id, enrichCount)
        },
        onError: (err: any) => {
          // message imported by antd static method
          const antMessage = (window as any).__antd_message__
          if (antMessage) antMessage.error(err?.message || 'Failed to create investigation')
        },
      },
    )
  }

  const togglePlatform = (key: string) => {
    setEnabledPlatforms((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // ── Search table columns ────────────────────────────────────────────────────

  const searchColumns = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, s: SavedSearch) => (
        <div>
          <Text strong style={{ fontSize: 13 }}>{name}</Text>
          {s.description && (
            <Paragraph type="secondary" style={{ fontSize: 11, margin: 0 }} ellipsis={{ rows: 1 }}>
              {s.description}
            </Paragraph>
          )}
        </div>
      ),
    },
    {
      title: 'Query',
      dataIndex: 'query',
      key: 'query',
      ellipsis: true,
      render: (q: string) => q
        ? <Tag style={{ fontSize: 11 }}>{q.slice(0, 60)}</Tag>
        : <Text type="secondary">—</Text>,
    },
    {
      title: 'Filters',
      key: 'filters',
      width: 100,
      render: (_: any, s: SavedSearch) => {
        const count = Object.values(s.filters).filter(
          (v) => v !== undefined && v !== null && (Array.isArray(v) ? v.length > 0 : true),
        ).length
        return count > 0 ? <Tag>{count} filter{count !== 1 ? 's' : ''}</Tag> : '—'
      },
    },
  ]

  const selectedSearches = searches.filter((s) => state.selectedSearchIds.includes(s.id))

  // ── Step content ────────────────────────────────────────────────────────────

  const stepContent = [

    // ── Step 0: Name & Description ───────────────────────────────────────────
    <Form form={form} layout="vertical" size="small" key="step0">
      <Form.Item
        label="Investigation Name"
        name="name"
        rules={[{ required: true, message: 'Name is required' }]}
      >
        <Input placeholder="e.g. 2026 Election Disinfo Campaign" autoFocus />
      </Form.Item>
      <Form.Item label="Description (optional)" name="description">
        <TextArea
          placeholder="What is this investigation about?"
          rows={3}
          showCount
          maxLength={500}
        />
      </Form.Item>
    </Form>,

    // ── Step 1: Select saved searches ────────────────────────────────────────
    <div key="step1">
      <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
        Select the saved searches that will seed this investigation's document index.
        Documents matching any selected search will be included.
      </Text>
      {searches.length === 0 && !isLoading ? (
        <Alert
          type="info"
          showIcon
          message="No saved searches yet"
          description="Go to Data Exploration → Advanced Search and save some queries first."
        />
      ) : (
        <Table
          size="small"
          loading={isLoading}
          dataSource={searches}
          columns={searchColumns}
          rowKey="id"
          pagination={false}
          scroll={{ y: 280 }}
          rowSelection={{
            selectedRowKeys: state.selectedSearchIds,
            onChange: (keys) => setState((s) => ({ ...s, selectedSearchIds: keys as string[] })),
          }}
        />
      )}
    </div>,

    // ── Step 2: Configure Scrapers (mock) ─────────────────────────────────────
    <div key="step2">
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="Scraper integration — coming soon"
        description="Configure data collection sources for future automated ingestion. These settings are saved with the investigation but scrapers are not yet active."
      />
      <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
        Enable platforms and enter source URLs to collect data automatically once scraping is live.
      </Text>
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        {PLATFORMS.map((p) => {
          const enabled = enabledPlatforms.has(p.key)
          return (
            <div
              key={p.key}
              style={{
                border: `1px solid ${enabled ? token.colorPrimary : token.colorBorderSecondary}`,
                borderRadius: token.borderRadius,
                padding: '10px 14px',
                transition: 'border-color 0.2s',
              }}
            >
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Space>
                  {p.icon}
                  <Text strong style={{ fontSize: 13 }}>{p.label}</Text>
                </Space>
                <Switch
                  size="small"
                  checked={enabled}
                  onChange={() => togglePlatform(p.key)}
                />
              </Space>
              {enabled && (
                <div style={{ marginTop: 10 }}>
                  <Input
                    size="small"
                    placeholder={p.placeholder}
                    value={platformUrls[p.key] || ''}
                    onChange={(e) => setPlatformUrls((prev) => ({ ...prev, [p.key]: e.target.value }))}
                    style={{ marginBottom: 8 }}
                  />
                  <RangePicker
                    size="small"
                    style={{ width: '100%' }}
                    placeholder={['Scrape from', 'Scrape to']}
                    value={
                      platformDates[p.key]
                        ? [dayjs(platformDates[p.key]![0]), dayjs(platformDates[p.key]![1])]
                        : null
                    }
                    onChange={(_, strs) =>
                      setPlatformDates((prev) => ({
                        ...prev,
                        [p.key]: strs[0] && strs[1] ? [strs[0], strs[1]] : null,
                      }))
                    }
                  />
                </div>
              )}
            </div>
          )
        })}
      </Space>
    </div>,

    // ── Step 3: Auto-enrichment ───────────────────────────────────────────────
    <div key="step3">
      <Text type="secondary" style={{ display: 'block', marginBottom: 16, fontSize: 12 }}>
        Automatically enrich documents with AI analysis (entities, sentiment, IOCs, timelines,
        relationship graphs) once the investigation index is ready.
      </Text>

      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <div
          style={{
            border: `1px solid ${token.colorBorderSecondary}`,
            borderRadius: token.borderRadius,
            padding: '12px 16px',
          }}
        >
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space direction="vertical" size={2}>
              <Text strong>Enable auto-enrichment</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>
                Queue enrichment tasks immediately after the index is built
              </Text>
            </Space>
            <Switch
              checked={state.autoEnrich}
              onChange={(v) => setState((s) => ({ ...s, autoEnrich: v }))}
            />
          </Space>
        </div>

        {state.autoEnrich && (
          <div
            style={{
              border: `1px solid ${token.colorPrimary}`,
              borderRadius: token.borderRadius,
              padding: '12px 16px',
            }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size={10}>
              <div>
                <Text strong style={{ fontSize: 13 }}>Documents to enrich</Text>
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  The first <b>N</b> documents (sorted by date, newest first) will be
                  queued for enrichment. The total document count is determined after
                  the index is built — you can see progress on the investigation page.
                </Text>
              </div>
              <Space align="center" wrap>
                <InputNumber
                  min={1}
                  max={estimatedTotal ?? 500}
                  value={state.autoEnrichCount}
                  onChange={(v) => setState((s) => ({ ...s, autoEnrichCount: v ?? 20 }))}
                  style={{ width: 100 }}
                />
                <Text style={{ fontSize: 13 }}>of</Text>
                {estimating ? (
                  <Spin size="small" />
                ) : estimatedTotal !== null ? (
                  <Tag color="blue" style={{ fontSize: 13 }}>
                    ~{estimatedTotal.toLocaleString()} docs
                  </Tag>
                ) : (
                  <Tag icon={<QuestionCircleOutlined />} style={{ fontSize: 12 }}>
                    select searches to see total
                  </Tag>
                )}
              </Space>
              <Alert
                type="info"
                showIcon
                style={{ fontSize: 12 }}
                message={
                  estimatedTotal !== null
                    ? `Enriching ${Math.min(state.autoEnrichCount, estimatedTotal)} of ~${estimatedTotal.toLocaleString()} documents. Each takes ~10–30 s via the task queue.`
                    : `Each document takes ~10–30 s. Enrichment runs in parallel via the task queue.`
                }
              />
            </Space>
          </div>
        )}
      </Space>
    </div>,

    // ── Step 4: Review ────────────────────────────────────────────────────────
    <div key="step4">
      <Space direction="vertical" style={{ width: '100%' }} size={14}>
        {/* Name + description */}
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>NAME</Text>
          <Text strong style={{ display: 'block', fontSize: 15 }}>{state.name}</Text>
          {state.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>{state.description}</Text>
          )}
        </div>

        <Divider style={{ margin: '4px 0' }} />

        {/* Searches */}
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>
            SELECTED SEARCHES ({selectedSearches.length})
          </Text>
          {selectedSearches.length === 0 ? (
            <Text type="warning" style={{ display: 'block', fontSize: 12, marginTop: 4 }}>
              No searches selected — investigation will start with an empty index.
            </Text>
          ) : (
            <div style={{ marginTop: 4 }}>
              {selectedSearches.map((s) => (
                <div key={s.id} style={{ marginTop: 4 }}>
                  <Tag>{s.name}</Tag>
                  {s.query && (
                    <Text type="secondary" style={{ fontSize: 11 }}> — {s.query.slice(0, 50)}</Text>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Scrapers */}
        {enabledPlatforms.size > 0 && (
          <>
            <Divider style={{ margin: '4px 0' }} />
            <div>
              <Text type="secondary" style={{ fontSize: 11 }}>
                SCRAPERS (mock — {enabledPlatforms.size} platform{enabledPlatforms.size !== 1 ? 's' : ''})
              </Text>
              <div style={{ marginTop: 4 }}>
                {[...enabledPlatforms].map((key) => {
                  const p = PLATFORMS.find((x) => x.key === key)!
                  return (
                    <Tag key={key} style={{ marginTop: 4 }}>
                      {p.icon} {p.label}
                      {platformUrls[key] ? ` · ${platformUrls[key].slice(0, 30)}…` : ''}
                    </Tag>
                  )
                })}
              </div>
            </div>
          </>
        )}

        {/* Auto-enrichment */}
        <Divider style={{ margin: '4px 0' }} />
        <div>
          <Text type="secondary" style={{ fontSize: 11 }}>AUTO-ENRICHMENT</Text>
          <Text style={{ display: 'block', fontSize: 12, marginTop: 2 }}>
            {state.autoEnrich
              ? `Enabled — first ${state.autoEnrichCount} documents will be enriched after index build`
              : 'Disabled'}
          </Text>
        </div>

        <Alert
          type="info"
          showIcon
          message="Index creation runs in the background"
          description="After clicking Create, a background task builds the investigation index. Monitor progress in Task Monitor or on the investigation card."
        />
      </Space>
    </div>,
  ]

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <Modal
      title={
        <Space>
          <PlusOutlined />
          <Text strong>Create Investigation</Text>
        </Space>
      }
      open={open}
      onCancel={handleClose}
      width={660}
      footer={
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Button onClick={handleClose}>Cancel</Button>
          <Space>
            {step > 0 && <Button onClick={handleBack}>Back</Button>}
            {step < TOTAL_STEPS - 1 ? (
              <Button type="primary" onClick={handleNext}>
                Next
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<SearchOutlined />}
                loading={createInv.isPending}
                onClick={handleCreate}
              >
                Create Investigation
              </Button>
            )}
          </Space>
        </Space>
      }
    >
      <Steps
        current={step}
        size="small"
        style={{ marginBottom: 24 }}
        items={[
          { title: 'Name' },
          { title: 'Searches' },
          { title: 'Scrapers', icon: <ApiOutlined /> },
          { title: 'Enrichment', icon: <ThunderboltOutlined /> },
          { title: 'Review' },
        ]}
      />
      {stepContent[step]}
    </Modal>
  )
}
