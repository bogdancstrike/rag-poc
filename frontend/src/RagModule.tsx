import { useState, useEffect } from 'react'
import { ConfigProvider, Layout, theme as antTheme, Tabs, Typography, Space, Button, Tooltip, Menu, Spin, Alert, Switch } from 'antd'
import {
  BulbOutlined, MessageOutlined, BgColorsOutlined, DatabaseOutlined, RobotOutlined,
  TableOutlined, DashboardOutlined
} from '@ant-design/icons'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useThemeStore } from '@/stores/themeStore'
import { useSessionStore } from '@/stores/sessionStore'
import { InsightsPanel } from '@/components/insights/InsightsPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { DataTable } from '@/components/explore/DataTable'
import { OverviewDashboard } from '@/components/dashboard/OverviewDashboard'
import { useIndices } from '@/hooks/useExplore'
import { Document } from '@/api/explore'

const { Header, Content, Sider } = Layout
const { Text } = Typography

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

interface RagModuleProps {
  baseUrl?: string
  theme?: 'dark' | 'light'
  height?: string | number
}

function RagModuleInner({ height = '100vh' }: RagModuleProps) {
  const { token } = antTheme.useToken()
  const { mode, toggle } = useThemeStore()

  const { data: indices, isLoading: isLoadingIndices, error: indicesError } = useIndices()
  const [datasource, setDatasource] = useState<string>('__dashboard__')
  const [aiModes, setAiModes] = useState<Record<string, boolean>>(() => {
    try {
      const saved = localStorage.getItem('qsint_ai_modes')
      return saved ? JSON.parse(saved) : {}
    } catch {
      return {}
    }
  })
  const aiMode = aiModes[datasource] || false
  const setAiMode = (checked: boolean) => {
    setAiModes(prev => {
      const next = { ...prev, [datasource]: checked }
      try { localStorage.setItem('qsint_ai_modes', JSON.stringify(next)) } catch {}
      return next
    })
  }

  const [activeTab, setActiveTab]       = useState<'insights' | 'chat'>('insights')
  const [pendingQuery, setPendingQuery] = useState<string | null>(null)
  const setStorePendingQuery            = useSessionStore((s) => s.setPendingQuery)

  const handleAskAbout = (question: string) => {
    setPendingQuery(question)
    setStorePendingQuery(question)
    setActiveTab('chat')
    setAiMode(true)
  }

  const handleSendToRag = (docs: any[]) => {
    const context = docs.map(d => `Title: ${d.title}\nContent: ${d.text}`).join('\n\n')
    const query = `Please analyze the following ${docs.length} selected documents:\n\n${context}`
    setPendingQuery(query)
    setStorePendingQuery(query)
    setActiveTab('chat')
    setAiMode(true)
  }

  const aiTabItems = [
    {
      key:   'insights',
      label: <Space><BulbOutlined />Intelligence Report</Space>,
      children: (
        <div style={{ overflowY: 'auto', height: `calc(${typeof height === 'number' ? height + 'px' : height} - 108px)`, padding: '16px' }}>
          <InsightsPanel datasource={datasource} onAskAbout={handleAskAbout} />
        </div>
      ),
    },
    {
      key:   'chat',
      label: <Space><MessageOutlined />RAG Chat</Space>,
      children: (
        <div style={{ height: `calc(${typeof height === 'number' ? height + 'px' : height} - 108px)` }}>
          <ChatPanel
            datasource={datasource}
            prefillQuery={activeTab === 'chat' ? pendingQuery : null}
            onPrefillConsumed={() => setPendingQuery(null)}
          />
        </div>
      ),
    },
  ]

  const menuItems = [
    {
      key: '__dashboard__',
      icon: <DashboardOutlined />,
      label: 'Platform Overview'
    },
    { type: 'divider' },
    ...(indices || []).map(idx => ({
      key: idx,
      icon: <DatabaseOutlined />,
      label: idx
    }))
  ]

  return (
    <Layout style={{ height, background: token.colorBgLayout }}>
      {/* Top bar */}
      <Header
        style={{
          padding:     '0 16px',
          height:      48,
          lineHeight:  '48px',
          background:  token.colorBgContainer,
          borderBottom:`1px solid ${token.colorBorderSecondary}`,
          display:     'flex',
          alignItems:  'center',
          justifyContent: 'space-between',
          flexShrink:  0,
        }}
      >
        <Space>
          <BulbOutlined style={{ color: token.colorPrimary }} />
          <Text strong style={{ fontSize: 14 }}>QSINT RAG</Text>
          <Text style={{ fontSize: 11, color: token.colorTextDescription, marginLeft: 4 }}>
            Multi-Index Explorer
          </Text>
        </Space>
        <Space size={16}>
          {datasource && datasource !== '__dashboard__' && (
            <Space>
              <Text strong style={{ fontSize: 12 }}>AI Mode</Text>
              <Switch 
                checkedChildren={<RobotOutlined />} 
                unCheckedChildren={<TableOutlined />}
                checked={aiMode} 
                onChange={setAiMode} 
              />
            </Space>
          )}
          <Tooltip title={`Switch to ${mode === 'dark' ? 'light' : 'dark'} mode`}>
            <Button
              type="text"
              size="small"
              icon={<BgColorsOutlined />}
              onClick={toggle}
            />
          </Tooltip>
        </Space>
      </Header>

      <Layout>
        <Sider width={250} style={{ background: token.colorBgContainer, borderRight: `1px solid ${token.colorBorderSecondary}` }}>
          <div style={{ padding: '12px 16px' }}>
            <Text type="secondary" strong style={{ fontSize: 11 }}>AVAILABLE INDICES</Text>
          </div>
          {isLoadingIndices ? (
            <div style={{ padding: 16, textAlign: 'center' }}><Spin /></div>
          ) : indicesError ? (
            <Alert type="error" message="Failed to load indices" style={{ margin: 8 }} />
          ) : (
            <Menu
              mode="inline"
              selectedKeys={[datasource]}
              onClick={(e) => setDatasource(e.key)}
              items={menuItems as any}
              style={{ borderRight: 0 }}
            />
          )}
        </Sider>
        
        <Content style={{ position: 'relative' }}>
          {!datasource ? (
            <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
              <Text type="secondary">Select an index from the sidebar to explore data.</Text>
            </div>
          ) : datasource === '__dashboard__' ? (
            <div style={{ height: '100%', overflowY: 'auto' }}>
              <OverviewDashboard />
            </div>
          ) : aiMode ? (
            <Tabs
              activeKey={activeTab}
              onChange={(k) => setActiveTab(k as 'insights' | 'chat')}
              items={aiTabItems}
              style={{ height: '100%' }}
              tabBarStyle={{
                margin:  0,
                padding: '0 16px',
                background: token.colorBgContainer,
                borderBottom: `1px solid ${token.colorBorderSecondary}`,
              }}
              tabBarExtraContent={null}
            />
          ) : (
            <div style={{ height: '100%', padding: '16px' }}>
               <DataTable datasource={datasource} onSendToRag={handleSendToRag} />
            </div>
          )}
        </Content>
      </Layout>
    </Layout>
  )
}

export function RagModule(props: RagModuleProps) {
  const { mode } = useThemeStore()
  const isDark   = (props.theme ?? mode) === 'dark'

  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
        token: {
          colorPrimary:      '#1890ff',
          borderRadius:      4,
          fontFamily:        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
          colorBgLayout:     isDark ? '#141414' : '#f0f2f5',
          fontSize:          14,
          colorTextHeading:  isDark ? '#d9d9d9' : '#1f1f1f',
          colorTextSecondary:isDark ? '#8c8c8c' : '#595959',
        },
        components: {
          Layout: {
            headerBg: isDark ? '#1f1f1f' : '#ffffff',
            siderBg:  isDark ? '#1f1f1f' : '#ffffff',
          },
          Menu: {
            itemSelectedBg:    isDark ? '#111b26' : '#e6f7ff',
            itemSelectedColor: '#1890ff',
            itemHeight:        36,
          },
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <RagModuleInner {...props} />
      </QueryClientProvider>
    </ConfigProvider>
  )
}
