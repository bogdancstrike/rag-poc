import { useState } from 'react'
import {
  Upload, Table, Tag, Typography, Space, Button, Tooltip, theme, Progress,
  Modal, Alert, Popconfirm, notification,
} from 'antd'
import {
  InboxOutlined, FileTextOutlined, DeleteOutlined, EyeOutlined,
  DownloadOutlined, ReloadOutlined,
} from '@ant-design/icons'
import {
  useUploads, useUploadFile, useDeleteUpload, useAcceptedFormats,
  useConfirmMapping,
} from '@/hooks/useUploads'
import { downloadUploadUrl } from '@/api/uploads'
import { MappingReviewDrawer } from './MappingReviewDrawer'
import type { UploadedFile, UploadStatus } from '@/types'

const { Text, Paragraph } = Typography
const { Dragger } = Upload

const STATUS_COLORS: Record<UploadStatus, string> = {
  pending:        'default',
  parsing:        'processing',
  mapping_review: 'warning',
  indexing:       'processing',
  complete:       'success',
  error:          'error',
}

const STATUS_LABELS: Record<UploadStatus, string> = {
  pending:        'Pending',
  parsing:        'Parsing',
  mapping_review: 'Awaiting review',
  indexing:       'Indexing',
  complete:       'Complete',
  error:          'Error',
}

interface Props {
  investigationId: string
}

/**
 * Investigation detail page tab — drag-drop new files plus a table of all
 * past uploads. The table polls every 2.5s while any upload is non-terminal,
 * driven by ``useUploads``.
 */
export function UploadsTab({ investigationId }: Props) {
  const { token } = theme.useToken()
  const [api, contextHolder] = notification.useNotification()
  const { data: uploads = [], isLoading, refetch } = useUploads(investigationId)
  const { data: formats } = useAcceptedFormats()
  const uploadMut = useUploadFile(investigationId)
  const deleteMut = useDeleteUpload(investigationId)
  const [reviewing, setReviewing] = useState<UploadedFile | null>(null)

  const fmtSize = (b: number): string => {
    if (b < 1024) return `${b} B`
    if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`
    if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
    return `${(b / 1024 ** 3).toFixed(2)} GB`
  }

  const handleUpload = async (file: File) => {
    try {
      await uploadMut.mutateAsync(file)
      api.success({ message: `Uploaded ${file.name}`, duration: 3 })
    } catch (e: any) {
      const msg = e?.message || 'Upload failed'
      if (msg.includes('duplicate')) {
        api.warning({ message: `${file.name} already uploaded`, description: msg, duration: 4 })
      } else {
        api.error({ message: `Upload failed: ${file.name}`, description: msg, duration: 6 })
      }
    }
  }

  const handleDelete = async (u: UploadedFile, purgeEs: boolean) => {
    try {
      await deleteMut.mutateAsync({ fileId: u.id, purgeEs })
      api.success({ message: `Removed ${u.filename}`, duration: 3 })
    } catch (e: any) {
      api.error({ message: 'Delete failed', description: e?.message })
    }
  }

  const columns = [
    {
      title: 'File',
      dataIndex: 'filename',
      key: 'filename',
      render: (name: string, u: UploadedFile) => (
        <Space size={8}>
          <FileTextOutlined style={{ color: token.colorTextTertiary }} />
          <Text style={{ fontSize: 12 }}>{name}</Text>
          {u.handler_name && (
            <Tag style={{ fontSize: 10 }}>{u.handler_name}</Tag>
          )}
          {u.profile_id && (
            <Tooltip title="Mapping reused from a saved parser profile">
              <Tag color="cyan" style={{ fontSize: 10 }}>profile</Tag>
            </Tooltip>
          )}
        </Space>
      ),
    },
    {
      title: 'Size',
      dataIndex: 'size_bytes',
      key: 'size',
      width: 90,
      render: (s: number) => <Text style={{ fontSize: 11 }}>{fmtSize(s)}</Text>,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 200,
      render: (status: UploadStatus, u: UploadedFile) => {
        const total = u.record_count ?? 0
        const done = u.indexed_count ?? 0
        const percent = total > 0 ? Math.round((done / total) * 100) : 0
        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <Tag color={STATUS_COLORS[status]} style={{ fontSize: 11 }}>
              {STATUS_LABELS[status]}
            </Tag>
            {status === 'indexing' && total > 0 && (
              <Progress percent={percent} size="small" status="active" />
            )}
            {status === 'complete' && total > 0 && (
              <Text type="secondary" style={{ fontSize: 11 }}>
                {done.toLocaleString()} / {total.toLocaleString()} indexed
              </Text>
            )}
            {status === 'error' && u.error && (
              <Tooltip title={u.error}>
                <Text type="danger" ellipsis style={{ fontSize: 11, maxWidth: 180 }}>
                  {u.error}
                </Text>
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 180,
      render: (_: unknown, u: UploadedFile) => (
        <Space size={4}>
          {u.status === 'mapping_review' && (
            <Tooltip title="Review proposed mapping">
              <Button
                type="primary"
                size="small"
                icon={<EyeOutlined />}
                onClick={() => setReviewing(u)}
              >
                Review
              </Button>
            </Tooltip>
          )}
          <Tooltip title="Download original file">
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={downloadUploadUrl(u.id)}
              target="_blank"
              rel="noreferrer"
            />
          </Tooltip>
          <Popconfirm
            title="Delete this upload?"
            description="The original file will be removed. ES documents stay unless you use 'purge'."
            okText="Delete"
            onConfirm={() => handleDelete(u, false)}
          >
            <Tooltip title="Delete (keep ES docs)">
              <Button size="small" icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
          <Popconfirm
            title="Delete + purge from ES?"
            description="This also removes all indexed documents that came from this file."
            okText="Purge"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(u, true)}
          >
            <Tooltip title="Delete + purge ES docs">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      {contextHolder}

      <Dragger
        multiple
        accept={formats?.accept_string}
        beforeUpload={(file) => {
          handleUpload(file)
          return Upload.LIST_IGNORE
        }}
        showUploadList={false}
        style={{ padding: '8px 0', marginBottom: 16 }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text" style={{ fontSize: 14 }}>
          Click or drag files to add to this investigation
        </p>
        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
          Multiple files supported · streaming upload · max 5 GB per file by default
        </p>
      </Dragger>

      {/* Accepted formats */}
      {formats && (
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>ACCEPTED FORMATS:</Text>{' '}
          {formats.handlers.map((h) => (
            <Tooltip key={h.name} title={h.extensions.join(', ')}>
              <Tag style={{ fontSize: 11, marginRight: 4 }}>
                <span style={{ textTransform: 'uppercase' }}>{h.name}</span>
              </Tag>
            </Tooltip>
          ))}
        </div>
      )}

      {uploadMut.isPending && (
        <Alert
          type="info"
          showIcon
          message="Uploading…"
          style={{ marginBottom: 12 }}
        />
      )}

      <Space style={{ marginBottom: 8, width: '100%', justifyContent: 'space-between' }}>
        <Text strong style={{ fontSize: 13 }}>
          {uploads.length} upload{uploads.length !== 1 ? 's' : ''}
        </Text>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => refetch()}
        >
          Refresh
        </Button>
      </Space>

      <Table
        rowKey="id"
        size="small"
        loading={isLoading}
        dataSource={uploads}
        columns={columns as any}
        pagination={uploads.length > 25 ? { pageSize: 25, size: 'small' } : false}
      />

      <MappingReviewDrawer
        upload={reviewing}
        open={!!reviewing}
        onClose={() => setReviewing(null)}
        investigationId={investigationId}
      />
    </div>
  )
}
