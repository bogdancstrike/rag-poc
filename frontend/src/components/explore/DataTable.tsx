import { useState, useMemo, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Table, Input, Card, Typography, Space, Tooltip, Tag, Button, Divider,
  Row, Col, Spin, Alert, Badge, theme, Select, Collapse,
} from 'antd'
import {
  SearchOutlined, InfoCircleOutlined, SendOutlined, CloseOutlined,
  ReloadOutlined, RobotOutlined, FileTextOutlined,
  ClockCircleOutlined, CheckCircleOutlined, ApartmentOutlined,
  BugOutlined, EnvironmentOutlined, FieldTimeOutlined, TranslationOutlined,
  TagsOutlined, FilterOutlined, ClearOutlined, PlusOutlined, StarOutlined,
} from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { useDocuments, useDocumentById, useMultiEnrichedDocIds, useEnrichDocument, useForceReenrich, useReloadEnrichmentField, useDocumentStatuses, useSetDocumentStatus, useDocumentLabels, useSetDocumentLabels } from '@/hooks/useExplore'
import { Document, DocumentEnrichment, DocReviewStatus, EnrichmentField, DocumentFilters } from '@/api/explore'
import { RelationshipGraph } from '@/components/insights/RelationshipGraph'
import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)

/** Format a UTC ISO timestamp to local time with a UTC tooltip. */
function LocalTimestamp({ value }: { value?: string }) {
  if (!value) return <span>—</span>
  const local = dayjs.utc(value).local()
  return (
    <Tooltip title={`UTC: ${value}`}>
      <span>{local.format('YYYY-MM-DD HH:mm')}</span>
    </Tooltip>
  )
}

const { Text, Paragraph, Title } = Typography

/** Map entity type to a highlight background color */
const ENTITY_TYPE_BG: Record<string, string> = {
  person:   'rgba(255,120,117,0.25)',
  org:      'rgba(105,177,255,0.25)',
  location: 'rgba(149,222,100,0.25)',
  tool:     'rgba(255,214,102,0.3)',
  event:    'rgba(179,127,235,0.25)',
  default:  'rgba(140,140,140,0.2)',
}
const ENTITY_TYPE_BORDER: Record<string, string> = {
  person:   '#ff7875',
  org:      '#69b1ff',
  location: '#95de64',
  tool:     '#ffd666',
  event:    '#b37feb',
  default:  '#8c8c8c',
}

/** Sentiment → semi-transparent background colour for the text container */
function sentimentBg(sentiment?: string): string {
  if (!sentiment) return 'transparent'
  const s = sentiment.toLowerCase()
  if (s === 'hostile' || s === 'negative') return 'rgba(255,77,79,0.07)'
  if (s === 'positive' || s === 'supportive') return 'rgba(82,196,26,0.07)'
  return 'rgba(140,140,140,0.05)'
}

interface EntityInfo { name: string; type: string }

/**
 * HighlightedText — renders document text with entity names highlighted
 * and a sentiment-based background on the container.
 */
function HighlightedText({
  text, entities, sentiment,
}: {
  text: string
  entities: EntityInfo[]
  sentiment?: string
}) {
  const segments = useMemo(() => {
    if (!entities?.length || !text) return null

    // Deduplicate + sort longest first to avoid partial-match clobber
    const unique = Array.from(
      new Map(entities.map((e) => [e.name.toLowerCase(), e])).values(),
    ).sort((a, b) => b.name.length - a.name.length)

    // Build a single regex with named-ish groups — use index in replace
    const pattern = unique
      .map((e) => e.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
      .join('|')

    const regex = new RegExp(`(${pattern})`, 'gi')
    const parts = text.split(regex)

    return parts.map((part, i) => {
      const match = unique.find(
        (e) => e.name.toLowerCase() === part.toLowerCase(),
      )
      if (match) {
        const bg = ENTITY_TYPE_BG[match.type] || ENTITY_TYPE_BG.default
        const border = ENTITY_TYPE_BORDER[match.type] || ENTITY_TYPE_BORDER.default
        return (
          <Tooltip key={i} title={`${match.type.toUpperCase()}`}>
            <mark
              style={{
                background: bg,
                borderBottom: `2px solid ${border}`,
                borderRadius: 2,
                padding: '0 1px',
                cursor: 'help',
              }}
            >
              {part}
            </mark>
          </Tooltip>
        )
      }
      return <span key={i}>{part}</span>
    })
  }, [text, entities])

  return (
    <div
      style={{
        background: sentimentBg(sentiment),
        borderRadius: 6,
        padding: '10px 12px',
        border: sentiment ? '1px solid rgba(0,0,0,0.06)' : undefined,
        whiteSpace: 'pre-wrap',
        fontSize: 13,
        lineHeight: 1.6,
        transition: 'background 0.3s',
      }}
    >
      {segments ?? (text || '(no content)')}
    </div>
  )
}

// ── Enrichment section ──────────────────────────────────────────────────────

const ALL_PANEL_KEYS = ['core', 'graph', 'iocs', 'locations', 'timeline', 'translation']

interface EnrichmentSectionProps {
  datasource: string
  doc: Document
  /** Accumulated enrichment payload from stream */
  payload: Record<string, any> | null
  streamStatus: 'idle' | 'streaming' | 'complete' | 'error'
  streamError: string | null
  onRestream: () => void
}

const IOC_LABELS: Record<string, { label: string; color: string }> = {
  ips:        { label: 'IP',       color: 'volcano' },
  domains:    { label: 'Domain',   color: 'orange'  },
  urls:       { label: 'URL',      color: 'blue'    },
  emails:     { label: 'Email',    color: 'purple'  },
  hashes:     { label: 'Hash',     color: 'default' },
  cves:       { label: 'CVE',      color: 'red'     },
  file_paths: { label: 'Path',     color: 'cyan'    },
  hashtags:   { label: 'Hashtag',  color: 'geekblue'},
}

function EnrichmentSection({ datasource, doc, payload, streamStatus, streamError, onRestream }: EnrichmentSectionProps) {
  const { token } = theme.useToken()
  const reloadField = useReloadEnrichmentField(datasource, doc.id)
  const [showTranslation, setShowTranslation] = useState(false)
  // Expand all panels as soon as any payload arrives
  const [openPanels, setOpenPanels] = useState<string[]>(['core'])

  useEffect(() => {
    if (payload) setOpenPanels(ALL_PANEL_KEYS)
  }, [!!payload])

  const isStreaming = streamStatus === 'streaming'
  const isIdle      = streamStatus === 'idle'

  const reloadBtn = (field: EnrichmentField, label?: string) => (
    <Tooltip title={`Reload ${label ?? field}`}>
      <Button
        size="small"
        type="text"
        icon={<ReloadOutlined />}
        loading={reloadField.isPending && (reloadField.variables as any)?.field === field}
        onClick={(e) => { e.stopPropagation(); reloadField.mutate({ text: doc.text || '', field }) }}
      />
    </Tooltip>
  )

  const iocs: Record<string, string[]> = payload?.iocs ?? {}
  const hasIocs = Object.values(iocs).some((arr) => arr.length > 0)

  const locations: { name: string; lat: number | null; lon: number | null; display_name?: string }[] =
    payload?.locations ?? []

  const timeline: { date: string; description: string; normalized?: string }[] =
    payload?.timeline ?? []

  const graph = payload?.graph
  const hasGraph = graph && graph.nodes?.length > 0

  // translation may be stored as string (current) or legacy {language, text} object
  const rawTranslation = payload?.translation
  const translation: string = typeof rawTranslation === 'string'
    ? rawTranslation
    : (typeof rawTranslation === 'object' && rawTranslation !== null ? rawTranslation.text ?? '' : '')

  return (
    <div
      style={{
        background: token.colorFillAlter,
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: token.borderRadius,
        padding: 12,
        marginTop: 8,
      }}
    >
      {/* Header */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 8 }}>
        <Space>
          <RobotOutlined style={{ color: token.colorPrimary }} />
          <Text strong style={{ fontSize: 13 }}>AI Enrichment</Text>
          <Tag color="purple" style={{ fontSize: 10, margin: 0 }}>ENRICHMENT</Tag>
        </Space>
        <Space>
          {isStreaming && <Spin size="small" />}
          <Tooltip title="Re-run all enrichment">
            <Button size="small" icon={<ReloadOutlined />} onClick={onRestream}>
              Reload all
            </Button>
          </Tooltip>
        </Space>
      </Row>

      {(isIdle || isStreaming) && !payload && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <Spin size="small" />
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            AI is enriching document…
          </Text>
        </div>
      )}

      {streamStatus === 'error' && (
        <Alert
          type="error"
          message="Enrichment failed"
          description={streamError ?? 'Unknown error'}
          style={{ marginBottom: 8 }}
          action={<Button size="small" onClick={onRestream}>Retry</Button>}
        />
      )}

      {payload && (
        <Collapse
          ghost
          activeKey={openPanels}
          onChange={(keys) => setOpenPanels(Array.isArray(keys) ? keys : [keys])}
          style={{ marginTop: 0 }}
          items={[
            {
              key: 'core',
              label: <Text strong style={{ fontSize: 12 }}>Core Intelligence</Text>,
              children: (
                <Space orientation="vertical" style={{ width: '100%' }} size={0}>
                  {/* Summary */}
                  <div style={{ borderBottom: `1px solid ${token.colorBorderSecondary}`, paddingBottom: 10, marginBottom: 10 }}>
                    <Row justify="space-between" align="middle" style={{ marginBottom: 4 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>SUMMARY</Text>
                      {reloadBtn('summary')}
                    </Row>
                    <Paragraph style={{ margin: 0, fontSize: 13 }}>
                      {payload.summary || (isStreaming ? <Spin size="small" /> : '—')}
                    </Paragraph>
                  </div>

                  {/* Sentiment */}
                  <div style={{ borderBottom: `1px solid ${token.colorBorderSecondary}`, paddingBottom: 10, marginBottom: 10 }}>
                    <Row justify="space-between" align="middle" style={{ marginBottom: 4 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>SENTIMENT</Text>
                      {reloadBtn('sentiment')}
                    </Row>
                    {payload.sentiment ? (
                      <Tag color={['hostile','negative'].includes(payload.sentiment) ? 'red' : payload.sentiment === 'positive' ? 'green' : 'default'}>
                        {payload.sentiment.toUpperCase()}
                      </Tag>
                    ) : <Text type="secondary">—</Text>}
                  </div>

                  {/* Classification */}
                  <div style={{ borderBottom: `1px solid ${token.colorBorderSecondary}`, paddingBottom: 10, marginBottom: 10 }}>
                    <Row justify="space-between" align="middle" style={{ marginBottom: 4 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>CLASSIFICATION</Text>
                      {reloadBtn('classification')}
                    </Row>
                    {payload.classification ? <Tag>{payload.classification}</Tag> : <Text type="secondary">—</Text>}
                  </div>

                  {/* Entities */}
                  <div>
                    <Row justify="space-between" align="middle" style={{ marginBottom: 4 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>NAMED ENTITIES</Text>
                      {reloadBtn('entities')}
                    </Row>
                    <div>
                      {payload.entities?.length
                        ? payload.entities.map((e: any, i: number) => (
                          <Tag key={i} color="geekblue" style={{ marginBottom: 4 }}>
                            {e.name}
                            <Text type="secondary" style={{ fontSize: 10, marginLeft: 4 }}>{e.type}</Text>
                          </Tag>
                        ))
                        : <Text type="secondary">—</Text>}
                    </div>
                  </div>
                </Space>
              ),
            },

            /* ── Entity Relationship Graph — only when data exists ──────── */
            ...(hasGraph ? [{
              key: 'graph',
              label: (
                <Row justify="space-between" align="middle" style={{ width: '100%' }}>
                  <Space size={4}>
                    <ApartmentOutlined />
                    <Text strong style={{ fontSize: 12 }}>Entity Relationship Graph</Text>
                  </Space>
                  {reloadBtn('graph', 'graph')}
                </Row>
              ),
              children: (
                <RelationshipGraph
                  nodes={graph.nodes}
                  edges={graph.edges}
                  height={320}
                />
              ),
            }] : []),

            /* ── IOC Extraction — only when at least one IOC type has data  */
            ...(hasIocs ? [{
              key: 'iocs',
              label: (
                <Row justify="space-between" align="middle" style={{ width: '100%' }}>
                  <Space size={4}>
                    <BugOutlined />
                    <Text strong style={{ fontSize: 12 }}>IOC Extraction</Text>
                  </Space>
                  {reloadBtn('iocs', 'IOCs')}
                </Row>
              ),
              children: (
                <Space orientation="vertical" style={{ width: '100%' }} size={8}>
                  {Object.entries(IOC_LABELS).map(([key, { label, color }]) => {
                    const items: string[] = iocs[key] ?? []
                    if (!items.length) return null
                    return (
                      <div key={key}>
                        <Text type="secondary" style={{ fontSize: 11 }}>{label.toUpperCase()} ({items.length})</Text>
                        <div style={{ marginTop: 4 }}>
                          {items.slice(0, 20).map((v, i) => (
                            <Tag key={i} color={color} style={{ marginBottom: 4, fontSize: 11, fontFamily: 'monospace' }}>
                              {v.length > 60 ? v.slice(0, 57) + '…' : v}
                            </Tag>
                          ))}
                          {items.length > 20 && (
                            <Text type="secondary" style={{ fontSize: 11 }}>+{items.length - 20} more</Text>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </Space>
              ),
            }] : []),

            /* ── Geolocation — only when locations were extracted ──────── */
            ...(locations.length ? [{
              key: 'locations',
              label: (
                <Row justify="space-between" align="middle" style={{ width: '100%' }}>
                  <Space size={4}>
                    <EnvironmentOutlined />
                    <Text strong style={{ fontSize: 12 }}>Geolocation</Text>
                  </Space>
                  {reloadBtn('locations', 'locations')}
                </Row>
              ),
              children: (
                <Space orientation="vertical" style={{ width: '100%' }} size={4}>
                  {locations.map((loc: any, i: number) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <EnvironmentOutlined style={{ color: token.colorPrimary, fontSize: 12 }} />
                      <Text style={{ fontSize: 12 }}>{loc.display_name || loc.name}</Text>
                      {loc.lat != null && (
                        <Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>
                          {Number(loc.lat).toFixed(4)}, {Number(loc.lon).toFixed(4)}
                        </Text>
                      )}
                    </div>
                  ))}
                </Space>
              ),
            }] : []),

            /* ── Timeline — only when events were extracted ────────────── */
            ...(timeline.length ? [{
              key: 'timeline',
              label: (
                <Row justify="space-between" align="middle" style={{ width: '100%' }}>
                  <Space size={4}>
                    <FieldTimeOutlined />
                    <Text strong style={{ fontSize: 12 }}>Event Timeline</Text>
                  </Space>
                  {reloadBtn('timeline', 'timeline')}
                </Row>
              ),
              children: (
                <Space orientation="vertical" style={{ width: '100%' }} size={6}>
                  {timeline.map((ev: any, i: number) => (
                    <div key={i} style={{
                      display: 'flex', gap: 10,
                      paddingBottom: 6,
                      borderBottom: i < timeline.length - 1 ? `1px solid ${token.colorBorderSecondary}` : 'none',
                    }}>
                      <div style={{ minWidth: 90 }}>
                        <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                          {ev.normalized ?? ev.date}
                        </Tag>
                      </div>
                      <Text style={{ fontSize: 12 }}>{ev.description}</Text>
                    </div>
                  ))}
                </Space>
              ),
            }] : []),

            /* ── Translation ──────────────────────────────────────────── */
            {
              key: 'translation',
              label: (
                <Row justify="space-between" align="middle" style={{ width: '100%' }}>
                  <Space size={4}>
                    <TranslationOutlined />
                    <Text strong style={{ fontSize: 12 }}>Romanian Translation</Text>
                  </Space>
                  {reloadBtn('translation', 'translation')}
                </Row>
              ),
              children: translation ? (
                <div>
                  <Button
                    size="small"
                    type="link"
                    style={{ padding: 0, marginBottom: 6 }}
                    onClick={() => setShowTranslation((v) => !v)}
                  >
                    {showTranslation ? 'Hide translation' : 'Show translation'}
                  </Button>
                  {showTranslation && (
                    <Paragraph
                      style={{
                        fontSize: 12,
                        background: token.colorBgLayout,
                        border: `1px solid ${token.colorBorderSecondary}`,
                        borderRadius: token.borderRadius,
                        padding: 10,
                        margin: 0,
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {translation}
                    </Paragraph>
                  )}
                </div>
              ) : (
                <div style={{ textAlign: 'center', padding: '12px 0' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    No translation yet.{' '}
                    <Button type="link" size="small" style={{ padding: 0 }}
                      onClick={() => reloadField.mutate({ text: doc.text || '', field: 'translation' })}>
                      Translate now
                    </Button>
                  </Text>
                </div>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}

// ── Labels section ─────────────────────────────────────────────────────────

interface LabelsSectionProps {
  datasource: string
  docId: string
  currentLabels: string[]
  allKnownLabels: string[]
}

function LabelsSection({ datasource, docId, currentLabels, allKnownLabels }: LabelsSectionProps) {
  const { token } = theme.useToken()
  const setLabels = useSetDocumentLabels(datasource)
  const [inputVisible, setInputVisible] = useState(false)
  const [inputVal, setInputVal] = useState('')
  const inputRef = useRef<any>(null)

  useEffect(() => {
    if (inputVisible) inputRef.current?.focus()
  }, [inputVisible])

  const handleRemove = (label: string) => {
    const next = currentLabels.filter((l) => l !== label)
    setLabels.mutate({ docId, labels: next, datasource })
  }

  const handleAdd = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed || currentLabels.includes(trimmed)) {
      setInputVisible(false)
      setInputVal('')
      return
    }
    setLabels.mutate({ docId, labels: [...currentLabels, trimmed], datasource })
    setInputVisible(false)
    setInputVal('')
  }

  const handleSelectExisting = (value: string) => {
    if (!currentLabels.includes(value)) {
      setLabels.mutate({ docId, labels: [...currentLabels, value], datasource })
    }
  }

  const suggestions = allKnownLabels.filter((l) => !currentLabels.includes(l))

  return (
    <div style={{
      background: token.colorFillAlter,
      border: `1px solid ${token.colorBorderSecondary}`,
      borderRadius: token.borderRadius,
      padding: '10px 12px',
    }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 8 }}>
        <Space size={6}>
          <TagsOutlined style={{ color: token.colorPrimary }} />
          <Text strong style={{ fontSize: 13 }}>Labels</Text>
        </Space>
        {setLabels.isPending && <Spin size="small" />}
      </Row>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {currentLabels.map((label) => (
          <Tag
            key={label}
            closable
            onClose={() => handleRemove(label)}
            color="geekblue"
            style={{ margin: 0 }}
          >
            {label}
          </Tag>
        ))}
        {!currentLabels.length && (
          <Text type="secondary" style={{ fontSize: 12 }}>No labels yet</Text>
        )}
      </div>

      <Space size={6}>
        {suggestions.length > 0 && (
          <Select
            size="small"
            placeholder="Add existing label"
            style={{ width: 170 }}
            options={suggestions.map((l) => ({ value: l, label: l }))}
            onChange={handleSelectExisting}
            value={null}
            showSearch
          />
        )}
        {inputVisible ? (
          <Input
            ref={inputRef}
            size="small"
            placeholder="New label…"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onPressEnter={() => handleAdd(inputVal)}
            onBlur={() => handleAdd(inputVal)}
            style={{ width: 150 }}
          />
        ) : (
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => setInputVisible(true)}
          >
            New label
          </Button>
        )}
      </Space>
    </div>
  )
}

// ── Document Detail Panel (right side) ─────────────────────────────────────

interface DetailPanelProps {
  datasource: string
  doc: Document
  reviewStatus?: DocReviewStatus | null
  onStatusChange?: (status: DocReviewStatus | null) => void
  onClose: () => void
  onSendToRag?: (docs: Document[]) => void
  docLabels?: string[]
  allKnownLabels?: string[]
}

function DocumentDetailPanel({ datasource, doc, reviewStatus, onStatusChange, onClose, onSendToRag, docLabels = [], allKnownLabels = [] }: DetailPanelProps) {
  const { token } = theme.useToken()
  const qc = useQueryClient()

  // Enqueue enrichment via Kafka — polls until complete
  const { data: enrichData, isLoading: enrichLoading } =
    useEnrichDocument(datasource, doc.id, doc.text || '', !!(doc.text))
  const forceReenrich = useForceReenrich(datasource, doc.id)

  // When polling detects enrichment is complete, invalidate the enriched-doc-ids
  // cache so the ⭐ star appears immediately in the table without waiting for the
  // next 30-second refresh interval.
  useEffect(() => {
    if (enrichData?.status === 'complete' && datasource) {
      qc.invalidateQueries({ queryKey: ['enrichedDocIds', datasource] })
    }
  }, [enrichData?.status, datasource, qc])

  const enrichPayload = (enrichData?.payload as Record<string, any> | undefined) ?? null
  const enrichStatus: 'idle' | 'streaming' | 'complete' | 'error' =
    enrichLoading || enrichData?.status === 'pending' || enrichData?.status === 'processing'
      ? 'streaming'
      : enrichData?.status === 'complete'
      ? 'complete'
      : enrichData?.status === 'error'
      ? 'error'
      : 'idle'
  const enrichError = enrichData?.error ?? null
  const restream = () => forceReenrich.mutate(doc.text || '')
  const rawRows = useMemo(() => {
    const raw = (doc as any).raw
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return []
    return Object.entries(raw).map(([field, value]) => ({
      field,
      value: value == null
        ? ''
        : typeof value === 'string'
        ? value
        : JSON.stringify(value),
    }))
  }, [doc])

  const entities: EntityInfo[] = enrichPayload?.entities ?? []
  const enrichedSentiment = enrichPayload?.sentiment || doc.sentiment

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        borderLeft: `1px solid ${token.colorBorderSecondary}`,
        background: token.colorBgContainer,
        overflow: 'hidden',
      }}
    >
      {/* Panel header */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
        }}
      >
        <Space>
          <FileTextOutlined style={{ color: token.colorPrimary }} />
          <Text strong style={{ fontSize: 13 }}>Document Detail</Text>
          <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>{doc.id.slice(0, 8)}…</Tag>
        </Space>
        <Space>
          {onStatusChange !== undefined && (
            <Select
              size="small"
              value={reviewStatus ?? undefined}
              allowClear
              placeholder="Set status"
              style={{ width: 148 }}
              onChange={(val: DocReviewStatus | undefined) => onStatusChange(val ?? null)}
              onClear={() => onStatusChange(null)}
              options={[
                {
                  value: 'in_progress',
                  label: (
                    <Space size={4}>
                      <ClockCircleOutlined style={{ color: '#fa8c16' }} />
                      In Progress
                    </Space>
                  ),
                },
                {
                  value: 'done',
                  label: (
                    <Space size={4}>
                      <CheckCircleOutlined style={{ color: '#52c41a' }} />
                      Done
                    </Space>
                  ),
                },
              ]}
            />
          )}
          {onSendToRag && (
            <Button size="small" type="primary" icon={<SendOutlined />} onClick={() => onSendToRag([doc])}>
              Send to RAG
            </Button>
          )}
          <Tooltip title="Close panel">
            <Button size="small" type="text" icon={<CloseOutlined />} onClick={onClose} />
          </Tooltip>
        </Space>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {/* Metadata */}
        <Row gutter={16} style={{ marginBottom: 12 }}>
          {doc.created_at && (
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>DATE</Text>
              <div><LocalTimestamp value={doc.created_at} /></div>
            </Col>
          )}
          {doc.topic && (
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>TOPIC</Text>
              <div><Tag color="blue">{doc.topic}</Tag></div>
            </Col>
          )}
          {doc.sentiment && (
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>SENTIMENT</Text>
              <div>
                <Tag color={['hostile', 'negative'].includes(doc.sentiment) ? 'red' : 'default'}>
                  {doc.sentiment.toUpperCase()}
                </Tag>
              </div>
            </Col>
          )}
          {doc.source && (
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>SOURCE</Text>
              <div><Text>{doc.source}</Text></div>
            </Col>
          )}
        </Row>

        {doc.title && (
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>TITLE</Text>
            <Title level={5} style={{ margin: '4px 0 0' }}>{doc.title}</Title>
          </div>
        )}

        {/* Full content */}
        <div>
          <Row justify="space-between" align="middle">
            <Text type="secondary" style={{ fontSize: 11 }}>FULL DOCUMENT CONTENT</Text>
            {enrichedSentiment && (
              <Tag
                color={
                  ['hostile', 'negative'].includes(enrichedSentiment) ? 'red' :
                  ['positive', 'supportive'].includes(enrichedSentiment) ? 'green' : 'default'
                }
                style={{ fontSize: 10 }}
              >
                {enrichedSentiment.toUpperCase()}
              </Tag>
            )}
          </Row>
          <Divider style={{ margin: '6px 0 10px' }} />
          <HighlightedText
            text={doc.text || '(no content)'}
            entities={entities}
            sentiment={enrichedSentiment}
          />
          {entities.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 11, color: token.colorTextDescription }}>
              {entities.length} entities highlighted ·{' '}
              {Object.entries(ENTITY_TYPE_BORDER)
                .filter(([k]) => k !== 'default')
                .map(([type, color]) => (
                  <span key={type} style={{ marginRight: 8 }}>
                    <span style={{
                      display: 'inline-block', width: 8, height: 8,
                      borderRadius: 2, background: color, marginRight: 3,
                    }} />
                    {type}
                  </span>
                ))}
            </div>
          )}
        </div>

        <Divider style={{ margin: '12px 0' }} />

        {/* Uploaded source fields */}
        {rawRows.length > 0 && (
          <>
            <div>
              <Row justify="space-between" align="middle">
                <Text type="secondary" style={{ fontSize: 11 }}>SOURCE FIELDS</Text>
                <Tag style={{ fontSize: 10 }}>{rawRows.length} fields</Tag>
              </Row>
              <Divider style={{ margin: '6px 0 10px' }} />
              <Table
                rowKey="field"
                dataSource={rawRows}
                pagination={rawRows.length > 12 ? { pageSize: 12, size: 'small' } : false}
                size="small"
                tableLayout="fixed"
                columns={[
                  {
                    title: 'Field',
                    dataIndex: 'field',
                    key: 'field',
                    width: 180,
                    ellipsis: true,
                    render: (value: string) => <Text code style={{ fontSize: 12 }}>{value}</Text>,
                  },
                  {
                    title: 'Value',
                    dataIndex: 'value',
                    key: 'value',
                    render: (value: string) => (
                      <Paragraph
                        style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap' }}
                        ellipsis={{ rows: 3, expandable: true, symbol: 'more' }}
                      >
                        {value || '—'}
                      </Paragraph>
                    ),
                  },
                ]}
              />
            </div>

            <Divider style={{ margin: '12px 0' }} />
          </>
        )}

        {/* Labels / Tags */}
        <LabelsSection
          datasource={datasource}
          docId={doc.id}
          currentLabels={docLabels}
          allKnownLabels={allKnownLabels}
        />

        <Divider style={{ margin: '12px 0' }} />

        {/* Enrichment section — driven by SSE stream */}
        <EnrichmentSection
          datasource={datasource}
          doc={doc}
          payload={enrichPayload}
          streamStatus={enrichStatus}
          streamError={enrichError}
          onRestream={restream}
        />
      </div>
    </div>
  )
}

// ── Main DataTable ─────────────────────────────────────────────────────────

interface Props {
  datasource: string
  /** Doc ID from URL — auto-opens detail panel on mount/refresh. */
  initialDocId?: string
  /** Called whenever expanded doc changes so the parent can sync the URL. */
  onDocSelect?: (doc: Document | null) => void
  onSendToRag?: (docs: Document[]) => void
  /** External query override — when set the DataTable is in controlled mode for search */
  controlledQuery?: string
  /** External filter override — when set the DataTable is in controlled mode for filters */
  controlledFilters?: DocumentFilters
  /** Show the source index column (useful in global explore view) */
  showSourceIndex?: boolean
  /**
   * Sync selected document to URL query params (?doc=&idx=).
   * Enables deep-linking: refreshing or sharing the URL reopens the same document.
   * `idx` param is only written when datasource is empty (global explore mode).
   */
  enableUrlSync?: boolean
  /** Vertical offset for table scroll height calculation. Increase if pagination is hidden. */
  yOffset?: number
}

export function DataTable({
  datasource, initialDocId, onDocSelect, onSendToRag,
  controlledQuery, controlledFilters, showSourceIndex, enableUrlSync,
  yOffset = 360,
}: Props) {
  const { token } = theme.useToken()
  const [internalQuery, setInternalQuery] = useState('')
  const [searchVal, setSearchVal] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [expandedDoc, setExpandedDoc] = useState<Document | null>(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [selectedRows, setSelectedRows] = useState<Document[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [internalFilters, setInternalFilters] = useState<DocumentFilters>({})

  // URL sync — read ?doc= and ?idx= on first render
  const [searchParams, setSearchParams] = useSearchParams()
  const urlDocId  = enableUrlSync ? (searchParams.get('doc') ?? undefined) : undefined
  const urlDocIdx = enableUrlSync ? (searchParams.get('idx') ?? undefined) : undefined

  // Controlled mode: use externally provided state, fall back to internal
  const query   = controlledQuery   !== undefined ? controlledQuery   : internalQuery
  const filters = controlledFilters !== undefined ? controlledFilters : internalFilters

  const { data, isLoading, error } = useDocuments(datasource, page, pageSize, query, filters)

  useEffect(() => {
    setSearchVal(query)
    setPage(1)
  }, [query])

  // In global-explore mode (datasource="") documents span multiple indices.
  // Collect unique _source_index values from the loaded page so we can fetch
  // enriched IDs for each index separately (same cache keys as per-index mode).
  const sourceIndices = useMemo(() => {
    if (datasource) return [datasource]
    const seen = new Set<string>()
    for (const doc of data?.documents ?? []) {
      const src = (doc as any)._source_index
      if (src) seen.add(src)
    }
    return [...seen]
  }, [datasource, data?.documents])

  // Fetch enriched doc IDs — works for single datasource or multi-index global explore
  const enrichedSet = useMultiEnrichedDocIds(sourceIndices)

  // Analyst review statuses
  const { data: statusMap } = useDocumentStatuses(datasource)
  const setStatus = useSetDocumentStatus(datasource)

  // Labels
  const { data: labelsMap } = useDocumentLabels(datasource)
  // Collect all distinct labels across the datasource for autocomplete
  const allKnownLabels = useMemo(
    () => [...new Set(Object.values(labelsMap ?? {}).flat())].sort(),
    [labelsMap],
  )

  // Fetch pinned doc — supports both legacy initialDocId prop and URL ?doc= param.
  // In global explore mode (datasource=""), use ?idx= as the actual ES index.
  const pinnedDocId = urlDocId ?? initialDocId
  const pinnedDatasource = datasource || urlDocIdx || ''
  const { data: pinnedDoc } = useDocumentById(pinnedDatasource, pinnedDocId)

  // Open the pinned doc whenever the resolved ID changes
  useEffect(() => {
    if (pinnedDoc && pinnedDoc.id !== expandedDoc?.id) {
      setExpandedDoc(pinnedDoc)
    }
  }, [pinnedDoc?.id])

  // Helper: change expanded doc, notify parent, and sync URL params when enabled
  const selectDoc = (doc: Document | null) => {
    setExpandedDoc(doc)
    onDocSelect?.(doc)
    if (enableUrlSync) {
      if (doc) {
        const idx = (doc as any)._source_index || datasource
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev)
          next.set('doc', doc.id)
          if (idx) next.set('idx', idx)
          else next.delete('idx')
          return next
        }, { replace: true })
      } else {
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev)
          next.delete('doc')
          next.delete('idx')
          return next
        }, { replace: true })
      }
    }
  }

  const handleSearch = (value: string) => {
    setInternalQuery(value)
    setPage(1)
  }

  const updateFilter = (key: keyof DocumentFilters, value: any) => {
    setInternalFilters((prev) => ({ ...prev, [key]: value || undefined }))
    setPage(1)
  }

  const clearFilters = () => {
    setInternalFilters({})
    setPage(1)
  }

  const activeFilterCount = Object.values(filters).filter(
    (v) => v !== undefined && v !== '' && (Array.isArray(v) ? v.length > 0 : true),
  ).length

  const sourceIndexCol = showSourceIndex
    ? [{
        title: 'Index',
        dataIndex: '_source_index',
        key: '_source_index',
        width: 130,
        ellipsis: true,
        render: (val: string) => (
          <Tag style={{ fontSize: 11, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {val || '—'}
          </Tag>
        ),
      }]
    : []

  const columns = [
    ...sourceIndexCol,
    {
      title: 'Date',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 130,
      render: (val: string) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          <LocalTimestamp value={val} />
        </Text>
      ),
    },
    {
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      width: expandedDoc ? 180 : 260,
      ellipsis: true,
      render: (val: string, record: Document) => (
        <Space size={4}>
          {enrichedSet.has(record.id) && (
            <Tooltip title="AI enrichment complete">
              <span style={{ fontSize: 13 }}>⭐</span>
            </Tooltip>
          )}
          <Text strong style={{ fontSize: 13 }}>{val || '—'}</Text>
        </Space>
      ),
    },
    {
      title: 'Content',
      dataIndex: 'text',
      key: 'text',
      ellipsis: true,
      render: (val: string) => (
        <Tooltip title={val?.slice(0, 300)}>
          <Text style={{ fontSize: 12 }}>{val?.slice(0, 120)}</Text>
        </Tooltip>
      ),
    },
    {
      title: 'Topic',
      dataIndex: 'topic',
      key: 'topic',
      width: 120,
      render: (val: string) => val ? <Tag color="blue">{val}</Tag> : '—',
    },
    {
      title: 'Sentiment',
      dataIndex: 'sentiment',
      key: 'sentiment',
      width: 90,
      render: (val: string) => {
        const color = val === 'hostile' ? 'red' : val === 'supportive' ? 'green' : 'default'
        return val ? <Tag color={color}>{val.toUpperCase()}</Tag> : '—'
      },
    },
    {
      title: 'Status',
      key: 'review_status',
      width: 148,
      render: (_: any, record: Document) => {
        const current = statusMap?.[record.id] ?? null
        return (
          // Stop all clicks inside this cell from bubbling to the row handler
          <div onClick={(e) => e.stopPropagation()}>
          <Select
            size="small"
            value={current}
            allowClear
            placeholder="—"
            style={{ width: 136 }}
            loading={setStatus.isPending && (setStatus.variables as any)?.docId === record.id}
            onChange={(val: DocReviewStatus | undefined) => {
              setStatus.mutate({ 
                docId: record.id, 
                status: val ?? null, 
                datasource: (record as any)._source_index 
              })
            }}
            onClear={() => setStatus.mutate({ 
              docId: record.id, 
              status: null, 
              datasource: (record as any)._source_index 
            })}
            options={[
              {
                value: 'in_progress',
                label: (
                  <Space size={4}>
                    <ClockCircleOutlined style={{ color: '#fa8c16' }} />
                    In Progress
                  </Space>
                ),
              },
              {
                value: 'done',
                label: (
                  <Space size={4}>
                    <CheckCircleOutlined style={{ color: '#52c41a' }} />
                    Done
                  </Space>
                ),
              },
            ]}
          />
          </div>
        )
      },
    },
    {
      title: 'Labels',
      key: 'labels',
      width: expandedDoc ? 0 : 140,
      ellipsis: true,
      render: (_: any, record: Document) => {
        const docLbls = labelsMap?.[record.id] ?? []
        if (!docLbls.length) return null
        return (
          <Space size={2} style={{ flexWrap: 'wrap' }}>
            {docLbls.slice(0, 2).map((l) => (
              <Tag key={l} color="geekblue" style={{ margin: 0, fontSize: 10 }}>{l}</Tag>
            ))}
            {docLbls.length > 2 && (
              <Tag style={{ margin: 0, fontSize: 10 }}>+{docLbls.length - 2}</Tag>
            )}
          </Space>
        )
      },
    },
    {
      title: '',
      key: 'action',
      width: 60,
      render: (_: any, record: Document) => (
        <Button
          size="small"
          type={expandedDoc?.id === record.id ? 'primary' : 'default'}
          onClick={(e) => {
            e.stopPropagation()
            selectDoc(expandedDoc?.id === record.id ? null : record)
          }}
        >
          {expandedDoc?.id === record.id ? 'Close' : 'View'}
        </Button>
      ),
    },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Toolbar */}
      <Card
        variant="borderless"
        styles={{ body: { padding: '8px 12px' } }}
        style={{ marginBottom: 0, flexShrink: 0 }}
      >
        <Row justify="space-between" align="middle">
          <Space>
            <SearchOutlined />
            <Text strong>Data Exploration</Text>
            {data?.total !== undefined && (
              <Badge count={data.total} color="blue" overflowCount={999_999} />
            )}
          </Space>
          <Space>
            {selectedRowKeys.length > 0 && (
              <Button
                type="primary"
                icon={<SendOutlined />}
                size="small"
                onClick={() => onSendToRag && onSendToRag(selectedRows)}
              >
                Send {selectedRowKeys.length} to RAG
              </Button>
            )}
            <Tooltip
              title={
                <div>
                  <b>Search Syntax</b><br />
                  Exact: <i>"troll farm"</i><br />
                  Field: <i>title:malware</i><br />
                  Boolean: <i>(title:leak OR text:creds) AND sentiment:hostile</i><br />
                  Wildcard: <i>topic:cyber*</i>
                </div>
              }
            >
              <InfoCircleOutlined style={{ color: '#1890ff' }} />
            </Tooltip>
            <Input.Search
              placeholder='Search documents…'
              allowClear
              onSearch={handleSearch}
              onChange={(e) => setSearchVal(e.target.value)}
              value={searchVal}
              style={{ width: 280 }}
              size="small"
            />
            <Tooltip title="Advanced filters">
              <Badge count={activeFilterCount} size="small">
                <Button
                  size="small"
                  icon={<FilterOutlined />}
                  type={showFilters ? 'primary' : 'default'}
                  onClick={() => setShowFilters((v) => !v)}
                >
                  Filters
                </Button>
              </Badge>
            </Tooltip>
          </Space>
        </Row>

        {/* Filter bar */}
        {showFilters && (
          <Row style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${token.colorBorderSecondary}` }} gutter={8} align="middle">
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>Sentiment</Text>
              <Select
                size="small"
                allowClear
                placeholder="Any"
                style={{ width: 120, display: 'block', marginTop: 2 }}
                value={filters.sentiment}
                onChange={(v) => updateFilter('sentiment', v)}
                options={[
                  { value: 'positive',   label: 'Positive' },
                  { value: 'negative',   label: 'Negative' },
                  { value: 'neutral',    label: 'Neutral' },
                  { value: 'hostile',    label: 'Hostile' },
                  { value: 'mixed',      label: 'Mixed' },
                  { value: 'supportive', label: 'Supportive' },
                ]}
              />
            </Col>
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>Status</Text>
              <Select
                size="small"
                allowClear
                placeholder="Any"
                style={{ width: 130, display: 'block', marginTop: 2 }}
                value={filters.status}
                onChange={(v) => updateFilter('status', v)}
                options={[
                  { value: 'in_progress', label: 'In Progress' },
                  { value: 'done',        label: 'Done' },
                ]}
              />
            </Col>
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>Labels</Text>
              <Select
                size="small"
                mode="multiple"
                allowClear
                placeholder="Any"
                style={{ minWidth: 160, display: 'block', marginTop: 2 }}
                value={filters.labels ?? []}
                onChange={(v) => updateFilter('labels', v.length ? v : undefined)}
                options={allKnownLabels.map((l) => ({ value: l, label: l }))}
                showSearch
              />
            </Col>
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>Classification</Text>
              <Input
                size="small"
                allowClear
                placeholder="e.g. Cyber Threat"
                style={{ width: 160, display: 'block', marginTop: 2 }}
                value={filters.classification ?? ''}
                onChange={(e) => updateFilter('classification', e.target.value)}
              />
            </Col>
            <Col>
              <Text type="secondary" style={{ fontSize: 11 }}>Enriched</Text>
              <div style={{ marginTop: 6 }}>
                <Tooltip title="Show only AI-enriched documents">
                  <Button
                    size="small"
                    type={filters.enriched ? 'primary' : 'default'}
                    icon={<StarOutlined />}
                    onClick={() => updateFilter('enriched', filters.enriched ? undefined : true)}
                  >
                    {filters.enriched ? 'Enriched only' : 'All docs'}
                  </Button>
                </Tooltip>
              </div>
            </Col>
            {activeFilterCount > 0 && (
              <Col style={{ marginTop: 16 }}>
                <Button size="small" icon={<ClearOutlined />} onClick={clearFilters}>
                  Clear all
                </Button>
              </Col>
            )}
          </Row>
        )}
      </Card>

      {/* Main split area */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', gap: 0, marginTop: 8 }}>
        {/* Table column */}
        <div style={{ flex: expandedDoc ? '0 0 55%' : '1 1 100%', overflow: 'hidden', transition: 'flex 0.2s' }}>
          {error ? (
            <Alert type="error" message="Failed to load documents" description={(error as Error).message} />
          ) : (
            <Table<Document>
              rowKey="id"
              dataSource={data?.documents || []}
              columns={columns}
              loading={isLoading}
              size="small"
              rowSelection={{
                selectedRowKeys,
                onChange: (keys, rows) => {
                  setSelectedRowKeys(keys)
                  setSelectedRows(rows)
                },
              }}
              onRow={(record) => {
                const rs = statusMap?.[record.id]
                const bg = expandedDoc?.id === record.id
                  ? '#e6f7ff'
                  : rs === 'done'
                    ? 'rgba(82,196,26,0.06)'
                    : rs === 'in_progress'
                      ? 'rgba(250,140,22,0.06)'
                      : undefined
                return {
                  onClick: () => selectDoc(expandedDoc?.id === record.id ? null : record),
                  style: { cursor: 'pointer', background: bg },
                }
              }}
              pagination={{
                current: page,
                pageSize,
                total: data?.total || 0,
                onChange: (p, s) => {
                  setPage(p)
                  if (s && s !== pageSize) setPageSize(s)
                },
                showSizeChanger: true,
                pageSizeOptions: ['10', '25', '50', '100', '500'],
                showTotal: (total) => `${total} documents`,
                size: 'small',
              }}
              scroll={{ y: `calc(100vh - ${yOffset}px)`, x: 'max-content' }}
            />
          )}
        </div>

        {/* Document detail panel */}
        {expandedDoc && (
          <div style={{ flex: '0 0 45%', height: '100%', overflow: 'hidden' }}>
            <DocumentDetailPanel
              datasource={datasource || (expandedDoc as any)._source_index || ''}
              doc={expandedDoc}
              reviewStatus={statusMap?.[expandedDoc.id] ?? null}
              onStatusChange={(status) => setStatus.mutate({ 
                docId: expandedDoc.id, 
                status, 
                datasource: (expandedDoc as any)._source_index || datasource 
              })}
              onClose={() => selectDoc(null)}
              onSendToRag={onSendToRag}
              docLabels={labelsMap?.[expandedDoc.id] ?? []}
              allKnownLabels={allKnownLabels}
            />
          </div>
        )}
      </div>
    </div>
  )
}
