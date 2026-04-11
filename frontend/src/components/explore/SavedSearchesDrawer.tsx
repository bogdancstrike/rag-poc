import { useState } from 'react'
import {
  Drawer, List, Button, Popconfirm, Typography, Tag, Space, Empty, Spin,
  Input, Form, Tooltip, Badge,
} from 'antd'
import {
  DeleteOutlined, EditOutlined, PlayCircleOutlined, CheckOutlined, CloseOutlined,
} from '@ant-design/icons'
import type { SavedSearch } from '@/types'
import { useSavedSearches, useDeleteSearch, useUpdateSearch } from '@/hooks/useSavedSearches'

const { Text, Paragraph } = Typography

interface Props {
  open: boolean
  onClose: () => void
  onApply: (search: SavedSearch) => void
}

export function SavedSearchesDrawer({ open, onClose, onApply }: Props) {
  const { data: searches, isLoading } = useSavedSearches()
  const deleteSearch  = useDeleteSearch()
  const updateSearch  = useUpdateSearch()
  const [editingId,   setEditingId]   = useState<string | null>(null)
  const [editName,    setEditName]    = useState('')
  const [editDesc,    setEditDesc]    = useState('')

  const startEdit = (s: SavedSearch) => {
    setEditingId(s.id)
    setEditName(s.name)
    setEditDesc(s.description || '')
  }

  const cancelEdit = () => setEditingId(null)

  const saveEdit = (s: SavedSearch) => {
    if (!editName.trim()) return
    updateSearch.mutate({ id: s.id, name: editName.trim(), description: editDesc.trim() })
    setEditingId(null)
  }

  const filterSummary = (s: SavedSearch): string[] => {
    const parts: string[] = []
    if (s.filters.sentiment)      parts.push(`sentiment: ${s.filters.sentiment}`)
    if (s.filters.status)         parts.push(`status: ${s.filters.status}`)
    if (s.filters.classification) parts.push(`class: ${s.filters.classification}`)
    if (s.filters.date_from)      parts.push(`from: ${s.filters.date_from.slice(0, 10)}`)
    if (s.filters.date_to)        parts.push(`to: ${s.filters.date_to.slice(0, 10)}`)
    if (s.filters.index_patterns?.length) {
      parts.push(`indices: ${s.filters.index_patterns.slice(0, 2).join(', ')}`)
    }
    return parts
  }

  return (
    <Drawer
      title={
        <Space>
          <Text strong>Saved Searches</Text>
          <Badge count={searches?.length ?? 0} showZero style={{ backgroundColor: '#1890ff' }} />
        </Space>
      }
      placement="right"
      width={440}
      open={open}
      onClose={onClose}
    >
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
      ) : !searches?.length ? (
        <Empty
          description="No saved searches yet"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          <Text type="secondary" style={{ fontSize: 12 }}>
            Use Advanced Search and click "Save this search"
          </Text>
        </Empty>
      ) : (
        <List
          dataSource={searches}
          itemLayout="vertical"
          renderItem={(s) => (
            <List.Item
              key={s.id}
              style={{ padding: '12px 0', borderBottom: '1px solid var(--border-color)' }}
              actions={[
                <Tooltip title="Apply this search" key="apply">
                  <Button
                    type="link"
                    size="small"
                    icon={<PlayCircleOutlined />}
                    onClick={() => { onApply(s); onClose() }}
                  >
                    Apply
                  </Button>
                </Tooltip>,
                <Tooltip title="Edit name / description" key="edit">
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => startEdit(s)}
                  />
                </Tooltip>,
                <Popconfirm
                  key="delete"
                  title="Delete this saved search?"
                  onConfirm={() => deleteSearch.mutate(s.id)}
                  okText="Delete"
                  okButtonProps={{ danger: true }}
                >
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>,
              ]}
            >
              {editingId === s.id ? (
                <div>
                  <Form layout="vertical" size="small">
                    <Form.Item label="Name" style={{ marginBottom: 8 }}>
                      <Input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onPressEnter={() => saveEdit(s)}
                        autoFocus
                      />
                    </Form.Item>
                    <Form.Item label="Description" style={{ marginBottom: 8 }}>
                      <Input
                        value={editDesc}
                        onChange={(e) => setEditDesc(e.target.value)}
                      />
                    </Form.Item>
                  </Form>
                  <Space>
                    <Button
                      size="small"
                      type="primary"
                      icon={<CheckOutlined />}
                      onClick={() => saveEdit(s)}
                    >
                      Save
                    </Button>
                    <Button size="small" icon={<CloseOutlined />} onClick={cancelEdit}>
                      Cancel
                    </Button>
                  </Space>
                </div>
              ) : (
                <div>
                  <Text strong>{s.name}</Text>
                  {s.description && (
                    <Paragraph
                      type="secondary"
                      style={{ fontSize: 12, marginBottom: 4 }}
                      ellipsis={{ rows: 1 }}
                    >
                      {s.description}
                    </Paragraph>
                  )}
                  {s.query && (
                    <Tag
                      style={{
                        maxWidth: '100%',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        fontSize: 11,
                        marginBottom: 4,
                      }}
                    >
                      {s.query}
                    </Tag>
                  )}
                  <div>
                    {filterSummary(s).map((f, i) => (
                      <Tag key={i} style={{ fontSize: 10 }}>{f}</Tag>
                    ))}
                  </div>
                </div>
              )}
            </List.Item>
          )}
        />
      )}
    </Drawer>
  )
}
