import { Layout, theme } from 'antd'
import type { ReactNode } from 'react'

const { Content } = Layout

interface RagShellProps {
  sidebar: ReactNode
  children: ReactNode
}

/** Main layout shell: fixed left sidebar + scrollable content area */
export function RagShell({ sidebar, children }: RagShellProps) {
  const { token } = theme.useToken()
  return (
    <Layout style={{ height: '100%', minHeight: 0 }}>
      {sidebar}
      <Layout style={{ background: token.colorBgLayout }}>
        <Content
          style={{
            padding: '16px',
            overflowY: 'auto',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
          }}
        >
          {children}
        </Content>
      </Layout>
    </Layout>
  )
}
