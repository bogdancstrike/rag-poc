/**
 * RagModule — root component with react-router-dom based URL routing.
 *
 * Routes:
 *   /                         → redirect to /overview
 *   /overview                 → Platform Overview
 *   /tasks                    → Task Monitor
 *   /tasks/:id                → Task Detail
 *   /explore                  → Data Exploration (all indices)
 *   /investigations           → Investigations list
 *   /investigations/:id       → Investigation detail (Data / Insights / Chat tabs)
 *   /dashboard                → legacy redirect → /overview
 *   /index/:idx               → legacy index page (kept for backwards compat)
 *   /index/:idx/:docId        → legacy index page with pinned doc
 */

import { useState, useEffect } from 'react'
import {
  BrowserRouter, Routes, Route, Navigate, useParams, useNavigate, useLocation,
} from 'react-router-dom'
import {
  ConfigProvider, Layout, theme as antTheme, Typography, Space,
  Button, Tooltip, Menu, Tabs,
} from 'antd'
import {
  BulbOutlined, MessageOutlined, BgColorsOutlined,
  DashboardOutlined, UnorderedListOutlined, TableOutlined, ApartmentOutlined,
  MenuFoldOutlined, MenuUnfoldOutlined,
} from '@ant-design/icons'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useThemeStore } from '@/stores/themeStore'
import { useSessionStore } from '@/stores/sessionStore'
import { InsightsPanel } from '@/components/insights/InsightsPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { DataTable } from '@/components/explore/DataTable'
import { DataExplorationPage } from '@/components/explore/DataExplorationPage'
import { InvestigationsPage } from '@/components/investigations/InvestigationsPage'
import { InvestigationDetail } from '@/components/investigations/InvestigationDetail'
import { OverviewDashboard } from '@/components/dashboard/OverviewDashboard'
import { TaskDetailPanel } from '@/components/dashboard/TaskDetailPanel'
import { TasksPage } from '@/components/tasks/TasksPage'

const { Header, Sider, Content } = Layout
const { Text } = Typography

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

// ── Left sidebar navigation ────────────────────────────────────────────────

const NAV_ITEMS = [
  { key: '/overview',       label: 'Platform Overview', icon: <DashboardOutlined /> },
  { key: '/tasks',          label: 'Task Monitor',      icon: <UnorderedListOutlined /> },
  { key: '/explore',        label: 'Data Exploration',  icon: <TableOutlined /> },
  { key: '/investigations', label: 'Investigations',    icon: <ApartmentOutlined /> },
]

function AppSidebar() {
  const navigate   = useNavigate()
  const location   = useLocation()
  const { token }  = antTheme.useToken()
  const [collapsed, setCollapsed] = useState(false)

  const selectedKey = (() => {
    const p = location.pathname
    if (p === '/' || p.startsWith('/overview') || p.startsWith('/dashboard')) return '/overview'
    if (p.startsWith('/tasks'))          return '/tasks'
    if (p.startsWith('/explore'))        return '/explore'
    if (p.startsWith('/investigations')) return '/investigations'
    return ''
  })()

  return (
    <Sider
      collapsible
      collapsed={collapsed}
      onCollapse={setCollapsed}
      width={220}
      collapsedWidth={56}
      trigger={null}          // we render our own trigger below
      style={{
        background:   token.colorBgContainer,
        borderRight:  `1px solid ${token.colorBorderSecondary}`,
        display:      'flex',
        flexDirection:'column',
        height:       '100vh',
        position:     'sticky',
        top:          0,
        overflow:     'hidden',
      }}
    >
      {/* Brand row */}
      <div
        style={{
          height:         52,
          display:        'flex',
          alignItems:     'center',
          padding:        collapsed ? '0 16px' : '0 16px',
          gap:            10,
          borderBottom:   `1px solid ${token.colorBorderSecondary}`,
          flexShrink:     0,
          overflow:       'hidden',
          whiteSpace:     'nowrap',
        }}
      >
        <BulbOutlined style={{ color: token.colorPrimary, fontSize: 18, flexShrink: 0 }} />
        {!collapsed && (
          <div style={{ overflow: 'hidden' }}>
            <Text strong style={{ fontSize: 13, display: 'block', lineHeight: '16px' }}>
              QSINT
            </Text>
            <Text type="secondary" style={{ fontSize: 10, lineHeight: '13px' }}>
              Intelligence Platform
            </Text>
          </div>
        )}
      </div>

      {/* Nav menu — fills remaining space */}
      <div style={{ flex: 1, overflow: 'hidden auto' }}>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          inlineCollapsed={collapsed}
          onClick={({ key }) => navigate(key)}
          items={NAV_ITEMS}
          style={{ border: 0, marginTop: 4 }}
        />
      </div>

      {/* Footer: collapse toggle only */}
      <div
        style={{
          borderTop:      `1px solid ${token.colorBorderSecondary}`,
          padding:        '8px',
          display:        'flex',
          alignItems:     'center',
          justifyContent: 'center',
          flexShrink:     0,
        }}
      >
        <Tooltip title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} placement="right">
          <Button
            type="text"
            size="small"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed((c) => !c)}
          />
        </Tooltip>
      </div>
    </Sider>
  )
}

// ── Top navbar ─────────────────────────────────────────────────────────────

function AppNavbar() {
  const { token } = antTheme.useToken()
  const { mode, toggle } = useThemeStore()
  const location = useLocation()

  // Derive current page label for breadcrumb
  const pageLabel = (() => {
    const p = location.pathname
    if (p.startsWith('/overview') || p === '/') return 'Platform Overview'
    if (p.startsWith('/tasks'))                  return 'Task Monitor'
    if (p.startsWith('/explore'))                return 'Data Exploration'
    if (p.startsWith('/investigations'))         return 'Investigations'
    if (p.startsWith('/index'))                  return 'Index Explorer'
    return ''
  })()

  return (
    <Header
      style={{
        padding:        '0 20px',
        height:         48,
        lineHeight:     '48px',
        background:     token.colorBgContainer,
        borderBottom:   `1px solid ${token.colorBorderSecondary}`,
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
        flexShrink:     0,
      }}
    >
      <Text type="secondary" style={{ fontSize: 13 }}>{pageLabel}</Text>
      <Tooltip title={`Switch to ${mode === 'dark' ? 'light' : 'dark'} mode`}>
        <Button type="text" size="small" icon={<BgColorsOutlined />} onClick={toggle} />
      </Tooltip>
    </Header>
  )
}

// ── Page wrappers ──────────────────────────────────────────────────────────

function DashboardPage() {
  const navigate = useNavigate()
  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <OverviewDashboard onGoToTasks={() => navigate('/tasks')} />
    </div>
  )
}

function TasksPageWrapper() {
  const navigate = useNavigate()
  return (
    <div style={{ height: '100%' }}>
      <TasksPage onViewTask={(task) => navigate(`/tasks/${encodeURIComponent(task.id)}`)} />
    </div>
  )
}

function TaskDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <TaskDetailPanel
        taskId={id ? decodeURIComponent(id) : ''}
        onBack={() => navigate('/tasks')}
      />
    </div>
  )
}

function InvestigationDetailPage() {
  const { id } = useParams<{ id: string }>()
  return <InvestigationDetail id={id ?? ''} />
}

/** Legacy index page — kept so old bookmarks / links still work */
function IndexPage() {
  const { idx, docId } = useParams<{ idx: string; docId?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [activeTab, setActiveTab] = useState<'data' | 'insights' | 'chat'>('data')
  const [pendingQuery, setPendingQuery] = useState<string | null>(null)
  const { pendingQuery: storePending, setPendingQuery: setStorePending } = useSessionStore()
  const { token } = antTheme.useToken()

  const datasource = idx ? decodeURIComponent(idx) : ''
  const initialDocId = docId ? decodeURIComponent(docId) : undefined

  useEffect(() => {
    if (storePending) {
      setPendingQuery(storePending)
      setStorePending(null)
      setActiveTab('chat')
    }
  }, [storePending])

  useEffect(() => {
    const tabFromState = (location.state as any)?.tab
    if (tabFromState) setActiveTab(tabFromState)
  }, [location.state])

  useEffect(() => {
    if (docId) setActiveTab('data')
  }, [docId])

  const handleDocSelect = (doc: any | null) => {
    if (doc) {
      navigate(`/index/${encodeURIComponent(datasource)}/${encodeURIComponent(doc.id)}`, { replace: true })
    } else {
      navigate(`/index/${encodeURIComponent(datasource)}`, { replace: true })
    }
  }

  const handleSendToRag = (docs: any[]) => {
    const context = docs
      .map((d) => `Title: ${d.title || '(untitled)'}\nContent: ${d.text || ''}`)
      .join('\n\n')
    setPendingQuery(`Please analyze the following ${docs.length} document(s):\n\n${context}`)
    setActiveTab('chat')
  }

  const handleAskAbout = (q: string) => {
    setPendingQuery(q)
    setActiveTab('chat')
  }

  const tabItems = [
    {
      key: 'data',
      label: <Space><TableOutlined />Data Exploration</Space>,
      children: (
        <div style={{ height: 'calc(100vh - 108px)', padding: 16, overflowY: 'auto' }}>
          <DataTable
            datasource={datasource}
            initialDocId={initialDocId}
            onDocSelect={handleDocSelect}
            onSendToRag={handleSendToRag}
          />
        </div>
      ),
    },
    {
      key: 'insights',
      label: <Space><BulbOutlined />Intelligence Report</Space>,
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
      label: <Space><MessageOutlined />RAG Chat</Space>,
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
      onChange={(k) => setActiveTab(k as 'data' | 'insights' | 'chat')}
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
      <AppSidebar />
      <Layout style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <AppNavbar />
        <Content style={{ position: 'relative', overflow: 'hidden', flex: 1 }}>
          <Routes>
            <Route path="/" element={<Navigate to="/overview" replace />} />
            <Route path="/dashboard" element={<Navigate to="/overview" replace />} />
            <Route path="/overview" element={<DashboardPage />} />
            <Route path="/tasks" element={<TasksPageWrapper />} />
            <Route path="/tasks/:id" element={<TaskDetailPage />} />
            <Route path="/explore" element={<DataExplorationPage />} />
            <Route path="/investigations" element={<InvestigationsPage />} />
            <Route path="/investigations/:id" element={<InvestigationDetailPage />} />
            {/* Legacy index routes */}
            <Route path="/index/:idx" element={<IndexPage />} />
            <Route path="/index/:idx/:docId" element={<IndexPage />} />
            <Route path="*" element={<Navigate to="/overview" replace />} />
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
