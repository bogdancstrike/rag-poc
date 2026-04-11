import { useState, useEffect } from 'react'
import {
  Tabs, Spin, Alert, Typography, Space, Button, Tag, theme,
} from 'antd'
import {
  TableOutlined, BulbOutlined, MessageOutlined,
  ArrowLeftOutlined, LoadingOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useInvestigation } from '@/hooks/useInvestigations'
import { DataTable } from '@/components/explore/DataTable'
import { InsightsPanel } from '@/components/insights/InsightsPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useSessionStore } from '@/stores/sessionStore'
import type { Investigation } from '@/types'

const { Text, Title } = Typography

interface Props {
  id: string
}

export function InvestigationDetail({ id }: Props) {
  const navigate = useNavigate()
  const { token } = theme.useToken()
  const { data: investigation, isLoading, error } = useInvestigation(id)

  const [activeTab, setActiveTab] = useState<'data' | 'insights' | 'chat'>('data')
  const [pendingQuery, setPendingQuery] = useState<string | null>(null)
  const { pendingQuery: storePending, setPendingQuery: setStorePending } = useSessionStore()

  // Handle "Ask about this" flow from InsightsPanel → ChatPanel
  useEffect(() => {
    if (storePending) {
      setPendingQuery(storePending)
      setStorePending(null)
      setActiveTab('chat')
    }
  }, [storePending])

  const handleAskAbout = (q: string) => {
    setPendingQuery(q)
    setActiveTab('chat')
  }

  if (isLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  if (error || !investigation) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          showIcon
          message="Investigation not found"
          description={
            <Button onClick={() => navigate('/investigations')} size="small" style={{ marginTop: 8 }}>
              Back to Investigations
            </Button>
          }
        />
      </div>
    )
  }

  const inv = investigation as Investigation

  // Header (always shown)
  const header = (
    <div
      style={{
        padding: '10px 16px',
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        background: token.colorBgContainer,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexShrink: 0,
      }}
    >
      <Button
        type="text"
        size="small"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate('/investigations')}
      />
      <div style={{ flex: 1 }}>
        <Space>
          <Title level={5} style={{ margin: 0 }}>{inv.name}</Title>
          {inv.status === 'creating' && (
            <Tag icon={<LoadingOutlined />} color="processing">Building index…</Tag>
          )}
          {inv.status === 'ready' && inv.doc_count !== null && (
            <Tag color="success">{inv.doc_count.toLocaleString()} docs</Tag>
          )}
          {inv.status === 'error' && (
            <Tag color="error">Error</Tag>
          )}
        </Space>
        {inv.description && (
          <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
            {inv.description}
          </Text>
        )}
      </div>
      <Text type="secondary" style={{ fontSize: 11, fontFamily: 'monospace' }}>
        {inv.index_name}
      </Text>
    </div>
  )

  // While creating — show spinner
  if (inv.status === 'creating') {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {header}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: 16 }}>
          <Spin size="large" />
          <Text type="secondary">Building investigation index…</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Documents are being copied from your saved searches. This may take a moment.
          </Text>
        </div>
      </div>
    )
  }

  // Error state
  if (inv.status === 'error') {
    return (
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {header}
        <div style={{ padding: 24 }}>
          <Alert
            type="error"
            showIcon
            message="Investigation creation failed"
            description={inv.error_msg || 'An unknown error occurred while building the index.'}
          />
        </div>
      </div>
    )
  }

  // Ready — show full tabbed view
  const tabItems = [
    {
      key: 'data',
      label: (
        <Space>
          <TableOutlined />
          Data Exploration
        </Space>
      ),
      children: (
        <div style={{ height: 'calc(100vh - 152px)', padding: 16, overflowY: 'auto' }}>
          <DataTable datasource={inv.index_name} />
        </div>
      ),
    },
    {
      key: 'insights',
      label: (
        <Space>
          <BulbOutlined />
          Intelligence Report
        </Space>
      ),
      children: (
        <div style={{ height: 'calc(100vh - 152px)', overflowY: 'auto', padding: 16 }}>
          <InsightsPanel
            datasource={inv.index_name}
            onAskAbout={handleAskAbout}
          />
        </div>
      ),
    },
    {
      key: 'chat',
      label: (
        <Space>
          <MessageOutlined />
          RAG Chat
        </Space>
      ),
      children: (
        <div style={{ height: 'calc(100vh - 152px)' }}>
          <ChatPanel
            datasource={inv.index_name}
            prefillQuery={activeTab === 'chat' ? pendingQuery : null}
            onPrefillConsumed={() => setPendingQuery(null)}
          />
        </div>
      ),
    },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {header}
      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as 'data' | 'insights' | 'chat')}
        items={tabItems}
        style={{ flex: 1 }}
        tabBarStyle={{
          margin: 0,
          padding: '0 16px',
          background: token.colorBgContainer,
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
        }}
      />
    </div>
  )
}
