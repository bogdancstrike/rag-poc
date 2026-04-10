/**
 * RagModule — root component with react-router-dom based URL routing.
 *
 * Routes:
 *   /             → redirect to /dashboard
 *   /dashboard    → Platform Overview
 *   /explore/:idx → DataTable for a specific index (data mode)
 *   /ai/:idx      → InsightsPanel + Chat for a specific index (AI mode)
 *   /tasks        → Platform Overview (task list focused)
 *   /tasks/:id    → Task Detail page
 */

import { useState, useEffect } from 'react'
import {
  BrowserRouter, Routes, Route, Navigate, useParams, useNavigate, useLocation,
} from 'react-router-dom'
import {
  ConfigProvider, Layout, theme as antTheme, Typography, Space,
  Button, Tooltip, Menu, Spin, Alert, Switch, Tabs,
} from 'antd'
import {
  BulbOutlined, MessageOutlined, BgColorsOutlined, DatabaseOutlined,
  RobotOutlined, TableOutlined, DashboardOutlined,
} from '@ant-design/icons'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useThemeStore } from '@/stores/themeStore'
import { useSessionStore } from '@/stores/sessionStore'
import { InsightsPanel } from '@/components/insights/InsightsPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { DataTable } from '@/components/explore/DataTable'
import { OverviewDashboard } from '@/components/dashboard/OverviewDashboard'
import { TaskDetailPanel } from '@/components/dashboard/TaskDetailPanel'
import { useIndices } from '@/hooks/useExplore'

const { Header, Content, Sider } = Layout
const { Text } = Typography

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

// ── Sidebar navigation ─────────────────────────────────────────────────────

function AppSidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { data: indices, isLoading, error } = useIndices()
  const { token } = antTheme.useToken()

  /** Derive the currently selected sidebar key from the URL. */
  const selectedKey = (() => {
    const path = location.pathname
    if (path === '/' || path.startsWith('/dashboard') || path.startsWith('/tasks')) return '__dashboard__'
    const m = path.match(/^\/(explore|ai)\/(.+)/)
    if (m) return m[2]
    return ''
  })()

  const menuItems = [
    { key: '__dashboard__', icon: <DashboardOutlined />, label: 'Platform Overview' },
    { type: 'divider' },
    ...(indices || []).map((idx) => ({
      key: idx,
      icon: <DatabaseOutlined />,
      label: idx,
    })),
  ]

  const handleSelect = ({ key }: { key: string }) => {
    if (key === '__dashboard__') {
      navigate('/dashboard')
    } else {
      navigate(`/explore/${encodeURIComponent(key)}`)
    }
  }

  return (
    <Sider
      width={240}
      style={{
        background: token.colorBgContainer,
        borderRight: `1px solid ${token.colorBorderSecondary}`,
        height: '100%',
        overflow: 'auto',
      }}
    >
      <div style={{ padding: '12px 16px 4px' }}>
        <Text type="secondary" strong style={{ fontSize: 11 }}>AVAILABLE INDICES</Text>
      </div>
      {isLoading ? (
        <div style={{ padding: 16, textAlign: 'center' }}><Spin /></div>
      ) : error ? (
        <Alert type="error" message="Failed to load indices" style={{ margin: 8 }} />
      ) : (
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          onClick={handleSelect}
          items={menuItems as any}
          style={{ borderRight: 0 }}
        />
      )}
    </Sider>
  )
}

// ── Top bar ────────────────────────────────────────────────────────────────

function AppHeader() {
  const { token } = antTheme.useToken()
  const { mode, toggle } = useThemeStore()
  const location = useLocation()

  /** Show the AI Mode toggle only on /explore and /ai routes. */
  const navigate = useNavigate()
  const isExplore = location.pathname.startsWith('/explore/')
  const isAi = location.pathname.startsWith('/ai/')
  const indexSlug = location.pathname.match(/^\/(explore|ai)\/(.+)/)?.[2] || ''
  const decodedIndex = indexSlug ? decodeURIComponent(indexSlug) : ''

  return (
    <Header
      style={{
        padding: '0 16px',
        height: 48,
        lineHeight: '48px',
        background: token.colorBgContainer,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}
    >
      <Space>
        <BulbOutlined style={{ color: token.colorPrimary, fontSize: 16 }} />
        <Text strong style={{ fontSize: 14 }}>QSINT RAG</Text>
        <Text style={{ fontSize: 11, color: token.colorTextDescription }}>
          Intelligence Platform
        </Text>
      </Space>
      <Space size={16}>
        {(isExplore || isAi) && decodedIndex && (
          <Space>
            <Text style={{ fontSize: 12, color: token.colorTextSecondary }}>
              {decodedIndex}
            </Text>
            <Text strong style={{ fontSize: 12 }}>AI Mode</Text>
            <Switch
              checkedChildren={<RobotOutlined />}
              unCheckedChildren={<TableOutlined />}
              checked={isAi}
              onChange={(v) => {
                if (v) navigate(`/ai/${indexSlug}`)
                else navigate(`/explore/${indexSlug}`)
              }}
            />
          </Space>
        )}
        <Tooltip title={`Switch to ${mode === 'dark' ? 'light' : 'dark'} mode`}>
          <Button type="text" size="small" icon={<BgColorsOutlined />} onClick={toggle} />
        </Tooltip>
      </Space>
    </Header>
  )
}

// ── Page views ─────────────────────────────────────────────────────────────

/** Platform Overview + Task list at /dashboard */
function DashboardPage() {
  const navigate = useNavigate()
  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <OverviewDashboard
        onSelectTask={(task, category) => {
          const id = category === 'insight'
            ? `insight__${task.datasource}__${task.insight_type}`
            : `enrichment__${task.datasource}__${task.doc_id}`
          navigate(`/tasks/${encodeURIComponent(id)}`, { state: { task, category } })
        }}
      />
    </div>
  )
}

/** Task detail page at /tasks/:id */
function TaskDetailPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()

  const state = location.state as { task: any; category: 'insight' | 'enrichment' } | null

  if (!state?.task) {
    return (
      <div style={{ padding: 32 }}>
        <Alert
          type="warning"
          message="Task not found"
          description="This task detail is not available. Please navigate from the Platform Overview."
          action={<Button onClick={() => navigate('/dashboard')}>Go to Dashboard</Button>}
        />
      </div>
    )
  }

  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <TaskDetailPanel
        task={state.task}
        category={state.category}
        onBack={() => navigate('/dashboard')}
      />
    </div>
  )
}

/** Raw data exploration at /explore/:index */
function ExplorePage() {
  const { index } = useParams<{ index: string }>()
  const navigate = useNavigate()
  const { setPendingQuery } = useSessionStore()

  const datasource = index ? decodeURIComponent(index) : ''

  const handleSendToRag = (docs: any[]) => {
    const context = docs
      .map((d) => `Title: ${d.title || '(untitled)'}\nContent: ${d.text || ''}`)
      .join('\n\n')
    const query = `Please analyze the following ${docs.length} document(s):\n\n${context}`
    setPendingQuery(query)
    navigate(`/ai/${encodeURIComponent(datasource)}`)
  }

  return (
    <div style={{ height: '100%', padding: 16 }}>
      <DataTable datasource={datasource} onSendToRag={handleSendToRag} />
    </div>
  )
}

/** AI mode (Insights + Chat) at /ai/:index */
function AiPage() {
  const { index } = useParams<{ index: string }>()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<'insights' | 'chat'>('insights')
  const [pendingQuery, setPendingQuery] = useState<string | null>(null)
  const { pendingQuery: storePending, setPendingQuery: setStorePending } = useSessionStore()
  const { token } = antTheme.useToken()

  const datasource = index ? decodeURIComponent(index) : ''

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

  const handleSendToRag = (docs: any[]) => {
    const context = docs
      .map((d) => `Title: ${d.title || '(untitled)'}\nContent: ${d.text || ''}`)
      .join('\n\n')
    setPendingQuery(`Analyze the following:\n\n${context}`)
    setActiveTab('chat')
  }

  const tabItems = [
    {
      key: 'insights',
      label: (
        <Space>
          <BulbOutlined />
          Intelligence Report
        </Space>
      ),
      children: (
        <div style={{ overflowY: 'auto', height: 'calc(100vh - 108px)', padding: 16 }}>
          <InsightsPanel
            datasource={datasource}
            onAskAbout={handleAskAbout}
            onSendToRag={handleSendToRag}
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
        <div style={{ height: 'calc(100vh - 108px)' }}>
          <ChatPanel
            datasource={datasource}
            prefillQuery={activeTab === 'chat' ? pendingQuery : null}
            onPrefillConsumed={() => setPendingQuery(null)}
          />
        </div>
      ),
    },
  ]

  return (
    <Tabs
      activeKey={activeTab}
      onChange={(k) => setActiveTab(k as 'insights' | 'chat')}
      items={tabItems}
      style={{ height: '100%' }}
      tabBarStyle={{
        margin: 0,
        padding: '0 16px',
        background: token.colorBgContainer,
        borderBottom: `1px solid ${token.colorBorderSecondary}`,
      }}
    />
  )
}

// ── Main shell ─────────────────────────────────────────────────────────────

function AppShell() {
  const { token } = antTheme.useToken()

  return (
    <Layout style={{ height: '100vh', background: token.colorBgLayout }}>
      <AppHeader />
      <Layout>
        <AppSidebar />
        <Content style={{ position: 'relative', overflow: 'hidden' }}>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/tasks" element={<DashboardPage />} />
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
            <Route path="/explore/:index" element={<ExplorePage />} />
            <Route path="/ai/:index" element={<AiPage />} />
            {/* Fallback */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}

// ── Public export ──────────────────────────────────────────────────────────

interface RagModuleProps {
  baseUrl?: string
  theme?: 'dark' | 'light'
  height?: string | number
}

export function RagModule(props: RagModuleProps) {
  const { mode } = useThemeStore()
  const isDark = (props.theme ?? mode) === 'dark'

  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
        token: {
          colorPrimary: '#1890ff',
          borderRadius: 6,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
          colorBgLayout: isDark ? '#141414' : '#f0f2f5',
          fontSize: 14,
          colorTextHeading: isDark ? '#d9d9d9' : '#1f1f1f',
          colorTextSecondary: isDark ? '#8c8c8c' : '#595959',
        },
        components: {
          Layout: {
            headerBg: isDark ? '#1f1f1f' : '#ffffff',
            siderBg:  isDark ? '#1f1f1f' : '#ffffff',
          },
          Menu: {
            itemSelectedBg:    isDark ? '#111b26' : '#e6f7ff',
            itemSelectedColor: '#1890ff',
            itemHeight: 36,
          },
          Card: {
            boxShadowTertiary: isDark
              ? '0 1px 4px rgba(0,0,0,0.3)'
              : '0 1px 4px rgba(0,0,0,0.06)',
          },
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppShell />
        </BrowserRouter>
      </QueryClientProvider>
    </ConfigProvider>
  )
}
