import { useState, useEffect, useRef } from 'react'
import {
  Tabs, Spin, Alert, Typography, Space, Button, Tag, theme, notification,
} from 'antd'
import {
  TableOutlined, BulbOutlined, MessageOutlined,
  ArrowLeftOutlined, LoadingOutlined, ThunderboltOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { useInvestigation } from '@/hooks/useInvestigations'
import { DataTable } from '@/components/explore/DataTable'
import { InsightsPanel } from '@/components/insights/InsightsPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { UploadsTab } from './UploadsTab'
import { useSessionStore } from '@/stores/sessionStore'
import { apiClient } from '@/api/client'
import type { Investigation } from '@/types'

const { Text, Title } = Typography

type TabKey = 'data' | 'insights' | 'chat' | 'uploads'
const VALID_TABS: TabKey[] = ['data', 'insights', 'chat', 'uploads']

interface Props {
  id: string
}

export function InvestigationDetail({ id }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const { token } = theme.useToken()
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: investigation, isLoading, error } = useInvestigation(id)
  const [api, contextHolder] = notification.useNotification()

  /**
   * Fetch the first `count` documents from the investigation index and queue
   * enrichment for each one.
   */
  const triggerAutoEnrichment = async (indexName: string, count: number) => {
    api.info({
      title: 'Auto-enrichment starting',
      description: `Fetching up to ${count} documents to enrich…`,
      icon: <ThunderboltOutlined style={{ color: '#faad14' }} />,
      duration: 4,
    })

    try {
      const resp = await apiClient.get<{ documents: any[]; total: number }>(
        '/v1/documents',
        { params: { datasource: indexName, limit: count, offset: 0 } },
      )
      const docs  = resp.data.documents ?? []
      const total = resp.data.total ?? 0
      const batch = docs.slice(0, count)

      if (batch.length === 0) {
        api.warning({ title: 'Auto-enrichment', description: 'No documents found in index.' })
        return
      }

      api.success({
        title: 'Auto-enrichment queued',
        description: `Enriching ${batch.length} of ${total} documents. Monitor progress in the Data tab.`,
        icon: <ThunderboltOutlined style={{ color: '#52c41a' }} />,
        duration: 6,
      })

      // Fire enrichment requests in parallel (backend queues via Kafka anyway)
      await Promise.allSettled(
        batch.map((doc: any) =>
          apiClient.post('/v1/documents/enrich', {
            doc_id:     doc.id,
            datasource: indexName,
            text:       doc.text || doc.content || doc.body || '',
          }).catch(() => {}),
        ),
      )
    } catch (e: any) {
      api.error({
        title: 'Auto-enrichment failed',
        description: e?.message || 'Could not fetch documents from the investigation index.',
      })
    }
  }

  const [activeTab, setActiveTab] = useState<TabKey>(() => {
    const t = searchParams.get('tab') as TabKey | null
    return t && VALID_TABS.includes(t) ? t : 'data'
  })
  const [pendingQuery, setPendingQuery] = useState<string | null>(null)
  const { pendingQuery: storePending, setPendingQuery: setStorePending } = useSessionStore()

  // Auto-enrichment: read count from router state set by the wizard
  const autoEnrichCount: number = (location.state as any)?.autoEnrichCount ?? 0
  const enrichTriggeredRef = useRef(false)

  // Handle "Ask about this" flow from InsightsPanel → ChatPanel
  useEffect(() => {
    if (storePending) {
      setPendingQuery(storePending)
      setStorePending(null)
      switchTab('chat')
    }
  }, [storePending])

  // Trigger auto-enrichment once the investigation transitions to "ready"
  useEffect(() => {
    const isReady = investigation?.status === 'ready' || investigation?.status === 'ready_with_vectors'
    if (
      autoEnrichCount > 0 &&
      isReady &&
      investigation?.index_name &&
      !enrichTriggeredRef.current
    ) {
      enrichTriggeredRef.current = true
      triggerAutoEnrichment(investigation.index_name, autoEnrichCount)
    }
  }, [investigation?.status, investigation?.index_name, autoEnrichCount])


  const switchTab = (tab: TabKey) => {
    setActiveTab(tab)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (tab === 'data') next.delete('tab')   // 'data' is default — keep URL clean
      else next.set('tab', tab)
      return next
    }, { replace: true })
  }

  const handleAskAbout = (q: string) => {
    setPendingQuery(q)
    switchTab('chat')
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
        {contextHolder}
        <Alert
          type="error"
          showIcon
          title="Investigation not found"
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
          {(inv.status === 'ready' || inv.status === 'ready_with_vectors') && inv.doc_count !== null && (
            <Tag color="success">{inv.doc_count.toLocaleString()} docs</Tag>
          )}
          {(inv.status === 'ready' || inv.status === 'ready_with_vectors') && autoEnrichCount > 0 && (
            <Tag icon={<ThunderboltOutlined />} color="gold">
              Auto-enriching {Math.min(autoEnrichCount, inv.doc_count ?? autoEnrichCount)} of {inv.doc_count ?? '?'}
            </Tag>
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
        {contextHolder}
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
        {contextHolder}
        {header}
        <div style={{ padding: 24 }}>
          <Alert
            type="error"
            showIcon
            title="Investigation creation failed"
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
        <div style={{ height: 'calc(100vh - 152px)', padding: 16, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <DataTable
            datasource={inv.index_name}
            enableUrlSync
            yOffset={380}
            // ``q`` lets other tabs (e.g. Uploads → "View N docs")
            // pre-filter the table by source_file/keyword. Empty/null
            // hands DataTable back to its internal search-box state.
            controlledQuery={searchParams.get('q') ?? undefined}
          />
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
    {
      key: 'uploads',
      label: (
        <Space>
          <CloudUploadOutlined />
          Uploads
        </Space>
      ),
      children: (
        <div style={{ height: 'calc(100vh - 152px)', overflowY: 'auto' }}>
          <UploadsTab investigationId={inv.id} />
        </div>
      ),
    },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {contextHolder}
      {header}
      <Tabs
        activeKey={activeTab}
        onChange={(k) => switchTab(k as TabKey)}
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
