import { useState, useMemo } from 'react'
import {
  Drawer, Button, Popconfirm, Typography, Tag, Space, Empty, Spin,
  Input, Tooltip, theme, Badge,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, PlayCircleOutlined,
  CheckOutlined, CloseOutlined, SearchOutlined,
  BookOutlined, CalendarOutlined, FilterOutlined,
} from '@ant-design/icons'
import type { SavedSearch } from '@/types'
import { useSavedSearches, useDeleteSearch, useUpdateSearch } from '@/hooks/useSavedSearches'

const { Text, Paragraph } = Typography

interface Props {
  open: boolean
  onClose: () => void
  onApply: (search: SavedSearch) => void
}

function FilterChips({ s }: { s: SavedSearch }) {
  const chips: { label: string; color?: string }[] = []
  if (s.query)                       chips.push({ label: `"${s.query.slice(0, 28)}${s.query.length > 28 ? '…' : ''}"`, color: 'blue' })
  if (s.filters.sentiment)           chips.push({ label: s.filters.sentiment })
  if (s.filters.status)              chips.push({ label: s.filters.status })
  if (s.filters.classification)      chips.push({ label: s.filters.classification! })
  if (s.filters.labels?.length)      chips.push({ label: `${s.filters.labels.length} label${s.filters.labels.length > 1 ? 's' : ''}`, color: 'purple' })
  if (s.filters.date_from)           chips.push({ label: `${s.filters.date_from.slice(0, 10)} → ${s.filters.date_to?.slice(0, 10) ?? '…'}`, color: 'cyan' })
  if (s.filters.index_patterns?.length) chips.push({ label: `${s.filters.index_patterns.length} index${s.filters.index_patterns.length > 1 ? 'es' : ''}`, color: 'geekblue' })

  if (!chips.length) return <Text type="secondary" style={{ fontSize: 11 }}>No filters — matches all</Text>

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {chips.map((c, i) => (
        <Tag key={i} color={c.color} style={{ fontSize: 10, margin: 0, lineHeight: '18px' }}>
          {c.label}
        </Tag>
      ))}
    </div>
  )
}

interface CardProps {
  s: SavedSearch
  onApply: (s: SavedSearch) => void
  onDelete: (id: string) => void
  onUpdate: (id: string, name: string, desc: string) => void
}

function SearchCard({ s, onApply, onDelete, onUpdate }: CardProps) {
  const { token } = theme.useToken()
  const [editing,   setEditing]   = useState(false)
  const [editName,  setEditName]  = useState(s.name)
  const [editDesc,  setEditDesc]  = useState(s.description || '')
  const [hovered,   setHovered]   = useState(false)

  const saveEdit = () => {
    if (!editName.trim()) return
    onUpdate(s.id, editName.trim(), editDesc.trim())
    setEditing(false)
  }

  const cancelEdit = () => {
    setEditName(s.name)
    setEditDesc(s.description || '')
    setEditing(false)
  }

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        border: `1px solid ${hovered ? token.colorPrimaryBorder : token.colorBorderSecondary}`,
        borderRadius: token.borderRadiusLG,
        background: hovered ? token.colorFillAlter : token.colorBgContainer,
        padding: '12px 14px',
        transition: 'border-color 0.15s, background 0.15s',
        cursor: 'default',
      }}
    >
      {editing ? (
        /* ── Edit mode ──────────────────────────────── */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Input
            size="small"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onPressEnter={saveEdit}
            placeholder="Search name *"
            autoFocus
          />
          <Input
            size="small"
            value={editDesc}
            onChange={(e) => setEditDesc(e.target.value)}
            placeholder="Description (optional)"
          />
          <Space size={6} style={{ justifyContent: 'flex-end' }}>
            <Button size="small" icon={<CloseOutlined />} onClick={cancelEdit}>Cancel</Button>
            <Button
              size="small"
              type="primary"
              icon={<CheckOutlined />}
              disabled={!editName.trim()}
              onClick={saveEdit}
            >
              Save
            </Button>
          </Space>
        </div>
      ) : (
        /* ── Display mode ───────────────────────────── */
        <div>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 4 }}>
            <Text strong style={{ fontSize: 13, lineHeight: '20px', flex: 1, marginRight: 8 }}>
              {s.name}
            </Text>
            <Space size={2} style={{ flexShrink: 0, opacity: hovered ? 1 : 0.4, transition: 'opacity 0.15s' }}>
              <Tooltip title="Rename">
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => setEditing(true)}
                />
              </Tooltip>
              <Popconfirm
                title="Delete this saved search?"
                onConfirm={() => onDelete(s.id)}
                okText="Delete"
                okButtonProps={{ danger: true }}
                placement="left"
              >
                <Tooltip title="Delete">
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                </Tooltip>
              </Popconfirm>
            </Space>
          </div>

          {s.description && (
            <Paragraph
              type="secondary"
              style={{ fontSize: 11, marginBottom: 8 }}
              ellipsis={{ rows: 2, tooltip: s.description }}
            >
              {s.description}
            </Paragraph>
          )}

          <div style={{ marginBottom: 10 }}>
            <FilterChips s={s} />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Text type="secondary" style={{ fontSize: 10 }}>
              <CalendarOutlined style={{ marginRight: 3 }} />
              {new Date(s.created_at).toLocaleDateString()}
            </Text>
            <Button
              type="primary"
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => onApply(s)}
            >
              Run search
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export function SavedSearchesDrawer({ open, onClose, onApply }: Props) {
  const { token } = theme.useToken()
  const { data: searches, isLoading } = useSavedSearches()
  const deleteSearch = useDeleteSearch()
  const updateSearch = useUpdateSearch()
  const [filterText, setFilterText] = useState('')

  const filtered = useMemo(() => {
    if (!searches || !filterText.trim()) return searches ?? []
    const q = filterText.toLowerCase()
    return searches.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.description?.toLowerCase().includes(q) ||
        s.query?.toLowerCase().includes(q),
    )
  }, [searches, filterText])

  const handleApply = (s: SavedSearch) => {
    onApply(s)
    onClose()
  }

  return (
    <Drawer
      title={
        <Space>
          <BookOutlined style={{ color: token.colorPrimary }} />
          <span>Saved Searches</span>
          {searches?.length ? (
            <Badge
              count={searches.length}
              style={{ backgroundColor: token.colorPrimary }}
            />
          ) : null}
        </Space>
      }
      placement="right"
      styles={{
        wrapper: { width: '440px' },
        body:    { padding: 0, display: 'flex', flexDirection: 'column' },
      }}
      open={open}
      onClose={onClose}
    >
      {/* Search bar */}
      {(searches?.length ?? 0) > 3 && (
        <div
          style={{
            padding: '10px 16px',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            flexShrink: 0,
          }}
        >
          <Input
            prefix={<SearchOutlined style={{ color: token.colorTextTertiary }} />}
            placeholder="Filter saved searches…"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            allowClear
            size="small"
          />
        </div>
      )}

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : !searches?.length ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div style={{ textAlign: 'center' }}>
                <Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                  No saved searches yet
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Open Advanced Search and click <strong>Save search</strong>
                </Text>
              </div>
            }
          />
        ) : filtered.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={<Text type="secondary">No matches for "{filterText}"</Text>}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {filtered.map((s) => (
              <SearchCard
                key={s.id}
                s={s}
                onApply={handleApply}
                onDelete={(id) => deleteSearch.mutate(id)}
                onUpdate={(id, name, desc) => updateSearch.mutate({ id, name, description: desc })}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer hint */}
      {(searches?.length ?? 0) > 0 && (
        <div
          style={{
            padding: '8px 16px',
            borderTop: `1px solid ${token.colorBorderSecondary}`,
            background: token.colorFillAlter,
            flexShrink: 0,
          }}
        >
          <Text type="secondary" style={{ fontSize: 11 }}>
            <FilterOutlined style={{ marginRight: 4 }} />
            {searches!.length} saved search{searches!.length !== 1 ? 'es' : ''} total
            {filtered.length !== searches!.length && ` · ${filtered.length} shown`}
          </Text>
        </div>
      )}
    </Drawer>
  )
}
