import { useState } from 'react'
import {
  Drawer, Form, Input, Select, DatePicker, Button, Space, Divider, Typography,
} from 'antd'
import { SaveOutlined, SearchOutlined, ClearOutlined } from '@ant-design/icons'
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
  /** Hide index_patterns selector (e.g. when inside an investigation with a fixed index) */
  hideIndexFilter?: boolean
}

const SENTIMENT_OPTIONS = [
  { value: 'positive',  label: 'Positive' },
  { value: 'negative',  label: 'Negative' },
  { value: 'neutral',   label: 'Neutral' },
  { value: 'hostile',   label: 'Hostile' },
  { value: 'mixed',     label: 'Mixed' },
]

const STATUS_OPTIONS = [
  { value: 'in_progress', label: 'In Progress' },
  { value: 'done',        label: 'Done' },
]

export function AdvancedSearchPanel({
  open, onClose, indices, value, onChange, onApply, onSave, hideIndexFilter,
}: Props) {
  const [saveName, setSaveName]   = useState('')
  const [saveDesc, setSaveDesc]   = useState('')
  const [showSave, setShowSave]   = useState(false)

  const set = (partial: Partial<AdvancedSearchState>) =>
    onChange({ ...value, ...partial })

  const handleClear = () => {
    onChange({ query: '' })
  }

  const handleApply = () => {
    onApply()
    onClose()
  }

  const handleSave = () => {
    if (!saveName.trim()) return
    onSave(saveName.trim(), saveDesc.trim())
    setSaveName('')
    setSaveDesc('')
    setShowSave(false)
  }

  const dateRange: [dayjs.Dayjs, dayjs.Dayjs] | null =
    value.date_from && value.date_to
      ? [dayjs(value.date_from), dayjs(value.date_to)]
      : null

  return (
    <Drawer
      title="Advanced Search"
      placement="right"
      styles={{ wrapper: { width: '420px' } }}
      open={open}
      onClose={onClose}
      extra={
        <Space>
          <Button icon={<ClearOutlined />} size="small" onClick={handleClear}>Clear</Button>
          <Button type="primary" icon={<SearchOutlined />} size="small" onClick={handleApply}>
            Apply
          </Button>
        </Space>
      }
    >
      <Form layout="vertical" size="small">
        <Form.Item label="Full-text Search">
          <Input
            placeholder="Keywords, phrases, operators…"
            value={value.query}
            onChange={(e) => set({ query: e.target.value })}
            onPressEnter={handleApply}
            allowClear
          />
        </Form.Item>

        <Form.Item label="Sentiment">
          <Select
            placeholder="Any sentiment"
            allowClear
            value={value.sentiment || undefined}
            onChange={(v) => set({ sentiment: v })}
            options={SENTIMENT_OPTIONS}
          />
        </Form.Item>

        <Form.Item label="Review Status">
          <Select
            placeholder="Any status"
            allowClear
            value={value.status || undefined}
            onChange={(v) => set({ status: v })}
            options={STATUS_OPTIONS}
          />
        </Form.Item>

        <Form.Item label="Classification">
          <Input
            placeholder="e.g. disinformation, threat…"
            value={value.classification || ''}
            onChange={(e) => set({ classification: e.target.value || undefined })}
            allowClear
          />
        </Form.Item>

        <Form.Item label="Labels">
          <Select
            mode="tags"
            placeholder="Add labels…"
            value={value.labels || []}
            onChange={(v) => set({ labels: v })}
            tokenSeparators={[',']}
          />
        </Form.Item>

        <Form.Item label="Date Range">
          <RangePicker
            style={{ width: '100%' }}
            value={dateRange}
            onChange={(range) => {
              if (range && range[0] && range[1]) {
                set({
                  date_from: range[0].startOf('day').toISOString(),
                  date_to:   range[1].endOf('day').toISOString(),
                })
              } else {
                set({ date_from: undefined, date_to: undefined })
              }
            }}
          />
        </Form.Item>

        {!hideIndexFilter && (
          <Form.Item label="Source Indices">
            <Select
              mode="multiple"
              placeholder="All indices"
              value={value.index_patterns || []}
              onChange={(v) => set({ index_patterns: v })}
              options={indices.map((idx) => ({ value: idx, label: idx }))}
              allowClear
            />
          </Form.Item>
        )}

        <Divider dashed style={{ margin: '16px 0 12px' }} />

        {!showSave ? (
          <Button
            block
            icon={<SaveOutlined />}
            onClick={() => setShowSave(true)}
          >
            Save this search
          </Button>
        ) : (
          <div>
            <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
              Save current search configuration
            </Text>
            <Input
              placeholder="Search name *"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              style={{ marginBottom: 8 }}
            />
            <Input
              placeholder="Description (optional)"
              value={saveDesc}
              onChange={(e) => setSaveDesc(e.target.value)}
              style={{ marginBottom: 8 }}
            />
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button size="small" onClick={() => setShowSave(false)}>Cancel</Button>
              <Button
                size="small"
                type="primary"
                icon={<SaveOutlined />}
                disabled={!saveName.trim()}
                onClick={handleSave}
              >
                Save
              </Button>
            </Space>
          </div>
        )}
      </Form>
    </Drawer>
  )
}
