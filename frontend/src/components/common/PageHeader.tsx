import React from 'react'
import { Typography, Space, theme, Divider } from 'antd'
import { InfoPoint } from './InfoPoint'

const { Title, Text } = Typography

interface PageHeaderProps {
  title: string
  subtitle?: string
  extra?: React.ReactNode
  info?: string
  icon?: React.ReactNode
}

/**
 * Standardized Header for all pages.
 * Ensures consistent title, icon, and extra actions layout.
 */
export function PageHeader({ title, subtitle, extra, info, icon }: PageHeaderProps) {
  const { token } = theme.useToken()

  return (
    <div style={{ 
      marginBottom: 20, 
      display: 'flex', 
      flexDirection: 'column', 
      gap: 4 
    }}>
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between',
        width: '100%' 
      }}>
        <Space size={12} align="center">
          {icon && (
            <div style={{ 
              fontSize: 24, 
              color: token.colorPrimary, 
              display: 'flex', 
              alignItems: 'center' 
            }}>
              {icon}
            </div>
          )}
          <div>
            <Space size={8} align="center">
              <Title level={4} style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
                {title}
              </Title>
              {info && <InfoPoint content={info} />}
            </Space>
            {subtitle && (
              <Text type="secondary" style={{ fontSize: 13, display: 'block' }}>
                {subtitle}
              </Text>
            )}
          </div>
        </Space>
        
        {extra && <div className="page-header-extra">{extra}</div>}
      </div>
      <Divider style={{ margin: '12px 0 0' }} />
    </div>
  )
}
