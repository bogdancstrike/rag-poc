import { useState } from 'react'
import {
  Layout, Menu, Button, Typography, Space, Tooltip, Popconfirm,
  Input, theme, Spin,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, EditOutlined, MessageOutlined, CheckOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useSessions, useCreateSession, useDeleteSession, useRenameSession } from '@/hooks/useSessions'
import { useSessionStore } from '@/stores/sessionStore'
import { useMessages } from '@/hooks/useSessions'

dayjs.extend(relativeTime)

const { Sider } = Layout
const { Text } = Typography

interface Props {
  datasource?: string
  collapsed?: boolean
}

/**
 * Left sidebar listing past sessions.
 * Supports: select, create, rename (inline), delete.
 */
export function SessionSidebar({ datasource, collapsed = false }: Props) {
  const { token } = theme.useToken()
  const { data: sessions, isLoading } = useSessions(datasource)
  const { activeSessionId, setActiveSession, setMessages } = useSessionStore()
  const createMut  = useCreateSession()
  const deleteMut  = useDeleteSession()
  const renameMut  = useRenameSession()

  const { refetch: fetchMessages } = useMessages(activeSessionId)

  const [editingId, setEditingId]     = useState<string | null>(null)
  const [editTitle, setEditTitle]     = useState('')

  const handleSelect = async (id: string) => {
    setActiveSession(id)
    const { data } = await fetchMessages()
    if (data) setMessages(data)
  }

  const handleCreate = () => {
    createMut.mutate({ datasource })
  }

  const startRename = (id: string, current: string) => {
    setEditingId(id)
    setEditTitle(current || '')
  }

  const commitRename = (id: string) => {
    if (editTitle.trim()) renameMut.mutate({ id, title: editTitle.trim() })
    setEditingId(null)
  }

  const menuItems = (sessions ?? []).map((s) => ({
    key:   s.id,
    label: (
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 4 }}
        onDoubleClick={() => startRename(s.id, s.title ?? '')}
      >
        {editingId === s.id ? (
          <Input
            size="small"
            value={editTitle}
            autoFocus
            onChange={(e) => setEditTitle(e.target.value)}
            onPressEnter={() => commitRename(s.id)}
            onBlur={() => commitRename(s.id)}
            onClick={(e) => e.stopPropagation()}
            style={{ flex: 1, fontSize: 12 }}
          />
        ) : (
          <Text
            ellipsis
            style={{ fontSize: 12, flex: 1, color: token.colorText }}
          >
            {s.title || `Session ${s.id.slice(0, 6)}`}
          </Text>
        )}

        {!collapsed && (
          <Space size={2} onClick={(e) => e.stopPropagation()}>
            <Tooltip title="Rename">
              <Button
                size="small" type="text"
                icon={<EditOutlined style={{ fontSize: 10 }} />}
                onClick={() => startRename(s.id, s.title ?? '')}
                style={{ width: 20, height: 20, minWidth: 20 }}
              />
            </Tooltip>
            <Popconfirm
              title="Delete session?"
              onConfirm={() => deleteMut.mutate(s.id)}
              okText="Yes" cancelText="No"
            >
              <Tooltip title="Delete">
                <Button
                  size="small" type="text" danger
                  icon={<DeleteOutlined style={{ fontSize: 10 }} />}
                  style={{ width: 20, height: 20, minWidth: 20 }}
                />
              </Tooltip>
            </Popconfirm>
          </Space>
        )}
      </div>
    ),
    icon: <MessageOutlined style={{ fontSize: 13 }} />,
  }))

  return (
    <Sider
      width={220}
      collapsedWidth={52}
      collapsed={collapsed}
      style={{
        background:  token.colorBgContainer,
        borderRight: `1px solid ${token.colorBorderSecondary}`,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* New session button */}
      <div style={{ padding: '12px 8px 8px' }}>
        <Tooltip title={collapsed ? 'New chat' : undefined} placement="right">
          <Button
            block
            type="dashed"
            icon={<PlusOutlined />}
            loading={createMut.isPending}
            onClick={handleCreate}
            style={{ fontSize: 12, height: 32 }}
          >
            {!collapsed && 'New Chat'}
          </Button>
        </Tooltip>
      </div>

      {isLoading ? (
        <div style={{ padding: 16, textAlign: 'center' }}><Spin size="small" /></div>
      ) : (
        <Menu
          mode="inline"
          selectedKeys={activeSessionId ? [activeSessionId] : []}
          onSelect={({ key }) => handleSelect(key)}
          items={menuItems}
          style={{
            flex: 1,
            overflowY: 'auto',
            border: 'none',
            background: 'transparent',
          }}
        />
      )}
    </Sider>
  )
}
