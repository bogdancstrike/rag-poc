import { Card, Typography, Tag, Space, Button, Popconfirm, Tooltip } from 'antd'
import {
  FolderOpenOutlined, DeleteOutlined, LoadingOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined, FileTextOutlined,
} from '@ant-design/icons'
import type { Investigation } from '@/types'

const { Text, Paragraph } = Typography

const STATUS_CONFIG: Record<
  string,
  { color: string; icon: React.ReactNode; label: string }
> = {
  creating: { color: 'processing', icon: <LoadingOutlined />,         label: 'Building…' },
  ready:    { color: 'success',    icon: <CheckCircleOutlined />,     label: 'Ready' },
  ready_with_vectors: { color: 'success', icon: <CheckCircleOutlined />, label: 'Ready' },
  error:    { color: 'error',      icon: <ExclamationCircleOutlined />, label: 'Error' },
}

interface Props {
  investigation: Investigation
  onOpen: (inv: Investigation) => void
  onDelete: (id: string) => void
}

export function InvestigationCard({ investigation: inv, onOpen, onDelete }: Props) {
  const cfg = STATUS_CONFIG[inv.status] || { 
    color: 'default', 
    icon: <ExclamationCircleOutlined />, 
    label: inv.status || 'Unknown' 
  }

  const isReady = inv.status === 'ready' || inv.status === 'ready_with_vectors'

  return (
    <Card
      size="small"
      hoverable={isReady}
      onClick={() => isReady && onOpen(inv)}
      style={{ height: '100%', cursor: isReady ? 'pointer' : 'default' }}
      actions={[
        <Tooltip title="Open investigation" key="open">
          <Button
            type="link"
            size="small"
            icon={<FolderOpenOutlined />}
            disabled={!isReady}
            onClick={(e) => { e.stopPropagation(); onOpen(inv) }}
          >
            Open
          </Button>
        </Tooltip>,
        <Popconfirm
          key="delete"
          title="Delete this investigation?"
          description="This will also delete the associated Elasticsearch index."
          onConfirm={(e) => { e?.stopPropagation(); onDelete(inv.id) }}
          okText="Delete"
          okButtonProps={{ danger: true }}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={(e) => e.stopPropagation()}
          />
        </Popconfirm>,
      ]}
    >
      <div style={{ marginBottom: 8 }}>
        <Tag icon={cfg.icon} color={cfg.color} style={{ marginBottom: 4 }}>
          {cfg.label}
        </Tag>
        <Text strong style={{ display: 'block', fontSize: 14 }}>{inv.name}</Text>
      </div>

      {inv.description && (
        <Paragraph
          type="secondary"
          style={{ fontSize: 12, marginBottom: 8 }}
          ellipsis={{ rows: 2 }}
        >
          {inv.description}
        </Paragraph>
      )}

      <Space orientation="vertical" size={2} style={{ width: '100%' }}>
        {isReady && inv.doc_count !== null && (
          <Space size={4}>
            <FileTextOutlined style={{ fontSize: 11, color: '#8c8c8c' }} />
            <Text type="secondary" style={{ fontSize: 11 }}>
              {inv.doc_count.toLocaleString()} documents
            </Text>
          </Space>
        )}
        {inv.status === 'error' && inv.error_msg && (
          <Text type="danger" style={{ fontSize: 11 }}>{inv.error_msg}</Text>
        )}
        <Text type="secondary" style={{ fontSize: 11 }}>
          {inv.search_ids.length} saved search{inv.search_ids.length !== 1 ? 'es' : ''}
          {' · '}
          {new Date(inv.created_at).toLocaleDateString()}
        </Text>
        <Text
          type="secondary"
          style={{ fontSize: 10, fontFamily: 'monospace', opacity: 0.6 }}
          ellipsis
        >
          {inv.index_name}
        </Text>
      </Space>
    </Card>
  )
}
