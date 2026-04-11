import { useState } from 'react'
import {
  Drawer, Input, Select, DatePicker, Button, Space, Typography,
  Segmented, Tag, Divider, theme, Modal,
} from 'antd'
import {
  SearchOutlined, ClearOutlined, SaveOutlined,
  CalendarOutlined, TagsOutlined, FilterOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import type { SavedSearchFilters } from '@/types'

const { RangePicker } = DatePicker
const { Text } = Typography

export interface AdvancedSearchState extends SavedSearchFilters {
  query: string
}

interface Props {
  open: boolean
  onClose: () => void
  indices: string[]
  value: AdvancedSearchState
  onChange: (v: AdvancedSearchState) => void
  onApply: () => void
  onSave: (name: string, description: string) => void
  hideIndexFilter?: boolean
}

const SENTIMENT_OPTS = [
  { label: 'Any',       value: '' },
  { label: 'Positive',  value: 'positive' },
  { label: 'Neutral',   value: 'neutral' },
  { label: 'Negative',  value: 'negative' },
  { label: 'Hostile',   value: 'hostile' },
  { label: 'Mixed',     value: 'mixed' },
]

const STATUS_OPTS = [
  { label: 'Any',         value: '' },
  { label: 'In Progress', value: 'in_progress' },
  { label: 'Done',        value: 'done' },
]

function SectionHeader({ icon, label }: { icon: React.ReactNode; label: string }) {
  const { token } = theme.useToken()
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
      <span style={{ color: token.colorTextTertiary, fontSize: 13 }}>{icon}</span>
      <Text style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: token.colorTextTertiary }}>
        {label}
      </Text>
    </div>
  )
}

export function AdvancedSearchPanel({
  open, onClose, indices, value, onChange, onApply, onSave, hideIndexFilter,
}: Props) {
  const { token } = theme.useToken()
  const [saveModal, setSaveModal]   = useState(false)
  const [saveName,  setSaveName]    = useState('')
  const [saveDesc,  setSaveDesc]    = useState('')

  const set = (partial: Partial<AdvancedSearchState>) =>
    onChange({ ...value, ...partial })

  const activeFilterCount = [
    value.sentiment, value.status, value.classification,
    value.labels?.length, value.date_from, value.index_patterns?.length,
  ].filter(Boolean).length

  const handleApply = () => { onApply(); onClose() }

  const handleClear = () => onChange({ query: '' })

  const handleSave = () => {
    if (!saveName.trim()) return
    onSave(saveName.trim(), saveDesc.trim())
    setSaveName(''); setSaveDesc(''); setSaveModal(false)
  }

  const dateRange: [dayjs.Dayjs, dayjs.Dayjs] | null =
    value.date_from && value.date_to
      ? [dayjs(value.date_from), dayjs(value.date_to)]
      : null

  return (
    <>
      <Drawer
        title={
          <Space>
            <FilterOutlined style={{ color: token.colorPrimary }} />
            <span>Advanced Search</span>
            {activeFilterCount > 0 && (
              <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>
                {activeFilterCount} active
              </Tag>
            )}
          </Space>
        }
        placement="right"
        styles={{
          wrapper: { width: '460px' },
          body: { padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 0 },
          footer: { padding: '12px 20px' },
        }}
        footer={
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space>
              <Button
                size="small"
                icon={<ClearOutlined />}
                onClick={handleClear}
                disabled={!activeFilterCount && !value.query}
              >
                Clear all
              </Button>
              <Button
                size="small"
                icon={<SaveOutlined />}
                onClick={() => setSaveModal(true)}
              >
                Save search
              </Button>
            </Space>
            <Button
              type="primary"
              icon={<SearchOutlined />}
              onClick={handleApply}
            >
              Apply
            </Button>
          </Space>
        }
        open={open}
        onClose={onClose}
      >
        {/* ── Full-text query ───────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <SectionHeader icon={<SearchOutlined />} label="Search Query" />
          <Input.Search
            placeholder="Keywords, phrases, boolean operators…"
            value={value.query}
            onChange={(e) => set({ query: e.target.value })}
            onSearch={handleApply}
            onPressEnter={handleApply}
            enterButton={false}
            allowClear
            size="middle"
          />
        </div>

        <Divider style={{ margin: '0 0 20px' }} />

        {/* ── Sentiment ─────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <SectionHeader icon={<FilterOutlined />} label="Content Filters" />

          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>Sentiment</Text>
          <Segmented
            options={SENTIMENT_OPTS}
            value={value.sentiment || ''}
            onChange={(v) => set({ sentiment: (v as string) || undefined })}
            style={{ width: '100%', marginBottom: 14 }}
            size="small"
          />

          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>Review Status</Text>
          <Segmented
            options={STATUS_OPTS}
            value={value.status || ''}
            onChange={(v) => set({ status: (v as string) || undefined })}
            style={{ width: '100%', marginBottom: 14 }}
            size="small"
          />

          <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>Classification</Text>
          <Input
            placeholder="e.g. disinformation, threat, propaganda…"
            value={value.classification || ''}
            onChange={(e) => set({ classification: e.target.value || undefined })}
            allowClear
            size="small"
          />
        </div>

        <Divider style={{ margin: '0 0 20px' }} />

        {/* ── Labels ────────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <SectionHeader icon={<TagsOutlined />} label="Labels" />
          <Select
            mode="tags"
            placeholder="Type a label and press Enter…"
            value={value.labels || []}
            onChange={(v) => set({ labels: v.length ? v : undefined })}
            tokenSeparators={[',']}
            style={{ width: '100%' }}
            size="small"
          />
        </div>

        <Divider style={{ margin: '0 0 20px' }} />

        {/* ── Date range ────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <SectionHeader icon={<CalendarOutlined />} label="Date Range" />
          <RangePicker
            style={{ width: '100%' }}
            value={dateRange}
            size="small"
            onChange={(range) => {
              if (range?.[0] && range?.[1]) {
                set({
                  date_from: range[0].startOf('day').toISOString(),
                  date_to:   range[1].endOf('day').toISOString(),
                })
              } else {
                set({ date_from: undefined, date_to: undefined })
              }
            }}
          />
        </div>

        {/* ── Source indices ────────────────────────────── */}
        {!hideIndexFilter && (
          <>
            <Divider style={{ margin: '0 0 20px' }} />
            <div>
              <SectionHeader icon={<DatabaseOutlined />} label="Source Indices" />
              <Select
                mode="multiple"
                placeholder="All indices"
                value={value.index_patterns || []}
                onChange={(v) => set({ index_patterns: v.length ? v : undefined })}
                options={indices.map((idx) => ({ value: idx, label: idx }))}
                style={{ width: '100%' }}
                size="small"
                allowClear
                maxTagCount="responsive"
              />
            </div>
          </>
        )}
      </Drawer>

      {/* Save search modal */}
      <Modal
        title={
          <Space>
            <SaveOutlined style={{ color: token.colorPrimary }} />
            Save Search
          </Space>
        }
        open={saveModal}
        onCancel={() => { setSaveModal(false); setSaveName(''); setSaveDesc('') }}
        onOk={handleSave}
        okText="Save"
        okButtonProps={{ disabled: !saveName.trim() }}
        width={380}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingTop: 8 }}>
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>Name *</Text>
            <Input
              placeholder="e.g. Hostile Russia narratives"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              onPressEnter={handleSave}
              autoFocus
            />
          </div>
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>Description</Text>
            <Input.TextArea
              placeholder="Optional notes about this search…"
              value={saveDesc}
              onChange={(e) => setSaveDesc(e.target.value)}
              autoSize={{ minRows: 2, maxRows: 4 }}
            />
          </div>
          {/* Preview of what will be saved */}
          <div
            style={{
              background: token.colorFillAlter,
              border: `1px solid ${token.colorBorderSecondary}`,
              borderRadius: token.borderRadius,
              padding: '8px 12px',
            }}
          >
            <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 4 }}>
              This will save:
            </Text>
            {value.query && (
              <div><Text style={{ fontSize: 12 }}>Query: </Text><Text code style={{ fontSize: 11 }}>{value.query}</Text></div>
            )}
            {value.sentiment && (
              <div><Text style={{ fontSize: 12 }}>Sentiment: </Text><Tag style={{ fontSize: 10 }}>{value.sentiment}</Tag></div>
            )}
            {value.status && (
              <div><Text style={{ fontSize: 12 }}>Status: </Text><Tag style={{ fontSize: 10 }}>{value.status}</Tag></div>
            )}
            {value.classification && (
              <div><Text style={{ fontSize: 12 }}>Classification: </Text><Tag style={{ fontSize: 10 }}>{value.classification}</Tag></div>
            )}
            {value.labels?.length ? (
              <div><Text style={{ fontSize: 12 }}>Labels: </Text>{value.labels.map((l) => <Tag key={l} style={{ fontSize: 10 }}>{l}</Tag>)}</div>
            ) : null}
            {value.date_from && (
              <div>
                <Text style={{ fontSize: 12 }}>Date: </Text>
                <Text style={{ fontSize: 11 }}>{value.date_from.slice(0, 10)} → {value.date_to?.slice(0, 10)}</Text>
              </div>
            )}
            {!value.query && activeFilterCount === 0 && (
              <Text type="secondary" style={{ fontSize: 11 }}>No filters set — this will match all documents.</Text>
            )}
          </div>
        </div>
      </Modal>
    </>
  )
}
