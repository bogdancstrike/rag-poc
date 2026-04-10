import { useState } from 'react'
import { ConfigProvider, Layout, theme as antTheme, Tabs, Typography, Space, Button, Tooltip } from 'antd'
import {
  BulbOutlined, MessageOutlined, BgColorsOutlined,
} from '@ant-design/icons'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useThemeStore } from '@/stores/themeStore'
import { useSessionStore } from '@/stores/sessionStore'
import { InsightsPanel } from '@/components/insights/InsightsPanel'
import { ChatPanel } from '@/components/chat/ChatPanel'

const { Header, Content } = Layout
const { Text } = Typography

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

interface RagModuleProps {
  /** Base URL of the QSINT RAG backend (e.g. "http://localhost:5100"). */
  baseUrl?: string
  /** Which ES index / datasource key to use. Defaults to "default". */
  datasource?: string
  /** Override initial theme. */
  theme?: 'dark' | 'light'
  /** Height of the module container. Defaults to "100vh". */
  height?: string | number
}

/**
 * RagModule — the public-facing component exported by @qsint/rag-ui.
 *
 * Mount anywhere with:
 *   <RagModule baseUrl="http://localhost:5100" datasource="qsint_docs" />
 *
 * Internally wraps InsightsPanel and ChatPanel in a two-tab layout.
 * The "Ask about this" CTA in insights pre-fills the chat input and
 * switches the active tab to Chat automatically.
 */
function RagModuleInner({ datasource = 'default', height = '100vh' }: RagModuleProps) {
  const { token } = antTheme.useToken()
  const { mode, toggle } = useThemeStore()

  const [activeTab, setActiveTab]       = useState<'insights' | 'chat'>('insights')
  const [pendingQuery, setPendingQuery] = useState<string | null>(null)
  const setStorePendingQuery            = useSessionStore((s) => s.setPendingQuery)

  /** Called when user clicks "Ask about this" on a narrative/topic/anomaly. */
  const handleAskAbout = (question: string) => {
    setPendingQuery(question)
    setStorePendingQuery(question)
    setActiveTab('chat')
  }

  const tabItems = [
    {
      key:   'insights',
      label: <Space><BulbOutlined />Intelligence</Space>,
      children: (
        <div style={{ overflowY: 'auto', height: `calc(${typeof height === 'number' ? height + 'px' : height} - 108px)`, padding: '16px' }}>
          <InsightsPanel datasource={datasource} onAskAbout={handleAskAbout} />
        </div>
      ),
    },
    {
      key:   'chat',
      label: <Space><MessageOutlined />Chat</Space>,
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
            {datasource !== 'default' ? datasource : ''}
          </Text>
        </Space>
        <Tooltip title={`Switch to ${mode === 'dark' ? 'light' : 'dark'} mode`}>
          <Button
            type="text"
            size="small"
            icon={<BgColorsOutlined />}
            onClick={toggle}
          />
        </Tooltip>
      </Header>

      {/* Tabs */}
      <Content>
        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as 'insights' | 'chat')}
          items={tabItems}
          style={{ height: '100%' }}
          tabBarStyle={{
            margin:  0,
            padding: '0 16px',
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
          tabBarExtraContent={null}
        />
      </Content>
    </Layout>
  )
}

/**
 * Public export — wraps inner component with providers (theme, react-query).
 */
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
