import { useState } from 'react'
import {
  Typography, Button, Row, Col, Empty, Spin, Alert, Space, theme, message,
} from 'antd'
import { PlusOutlined, ApartmentOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { InvestigationCard } from './InvestigationCard'
import { CreateInvestigationWizard } from './CreateInvestigationWizard'
import { useInvestigations, useDeleteInvestigation } from '@/hooks/useInvestigations'
import type { Investigation } from '@/types'

const { Title, Text } = Typography

export function InvestigationsPage() {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const { data: investigations, isLoading, error } = useInvestigations()
  const deleteInv = useDeleteInvestigation()
  const [showCreate, setShowCreate] = useState(false)

  const handleDelete = (id: string) => {
    deleteInv.mutate(id, {
      onSuccess: () => message.success('Investigation deleted'),
      onError:   () => message.error('Failed to delete investigation'),
    })
  }

  const handleCreated = (id: string) => {
    navigate(`/investigations/${id}`)
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div
        style={{
          padding: '12px 20px',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          background: token.colorBgContainer,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Space>
          <ApartmentOutlined style={{ fontSize: 16, color: token.colorPrimary }} />
          <Title level={5} style={{ margin: 0 }}>Investigations</Title>
          {investigations && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              ({investigations.length})
            </Text>
          )}
        </Space>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setShowCreate(true)}
        >
          Create Investigation
        </Button>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
        ) : error ? (
          <Alert type="error" message="Failed to load investigations" showIcon />
        ) : !investigations?.length ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div>
                <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                  No investigations yet
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  Create an investigation to aggregate documents from multiple saved searches
                  into a dedicated workspace with Intelligence Reports and RAG Chat.
                </Text>
              </div>
            }
          >
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setShowCreate(true)}
            >
              Create your first investigation
            </Button>
          </Empty>
        ) : (
          <Row gutter={[16, 16]}>
            {investigations.map((inv: Investigation) => (
              <Col key={inv.id} xs={24} sm={12} lg={8} xl={6}>
                <InvestigationCard
                  investigation={inv}
                  onOpen={(i) => navigate(`/investigations/${i.id}`)}
                  onDelete={handleDelete}
                />
              </Col>
            ))}
          </Row>
        )}
      </div>

      <CreateInvestigationWizard
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={handleCreated}
      />
    </div>
  )
}
