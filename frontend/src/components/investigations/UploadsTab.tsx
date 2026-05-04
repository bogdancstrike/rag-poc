import { useEffect, useRef, useState } from 'react'
import {
  Upload, Table, Tag, Typography, Space, Button, Tooltip, theme, Progress,
  Modal, Alert, Popconfirm, notification,
} from 'antd'
import {
  InboxOutlined, FileTextOutlined, DeleteOutlined, EyeOutlined,
  DownloadOutlined, ReloadOutlined, CheckCircleOutlined,
  ThunderboltOutlined, SearchOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  useUploads, useUploadFile, useDeleteUpload, useAcceptedFormats,
  useConfirmMapping,
} from '@/hooks/useUploads'
import { useInvestigation } from '@/hooks/useInvestigations'
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
  const navigate = useNavigate()
  const [api, contextHolder] = notification.useNotification()
  const { data: investigation } = useInvestigation(investigationId)
  const { data: uploads = [], isLoading, refetch } = useUploads(investigationId)
  const { data: formats } = useAcceptedFormats()
  const uploadMut = useUploadFile(investigationId)
  const deleteMut = useDeleteUpload(investigationId)
  const confirmMut = useConfirmMapping(investigationId)
  const [reviewing, setReviewing] = useState<UploadedFile | null>(null)
  const [bulkAccepting, setBulkAccepting] = useState(false)
  // Last-seen status per upload, so we can detect transitions and fire
  // a one-shot toast when a file finishes indexing or vectors come
  // online. Ref (not state) because we don't need to re-render on diff.
  const seenStatus = useRef<Record<string, { status: UploadStatus; vectors_ready: boolean }>>({})

  useEffect(() => {
    for (const u of uploads) {
      const prev = seenStatus.current[u.id]
      if (prev && prev.status !== 'complete' && u.status === 'complete') {
        api.success({
          message: `${u.filename} indexed`,
          description: `${u.indexed_count ?? 0} docs ready · BM25 active`,
          duration: 4,
        })
      }
      if (prev && !prev.vectors_ready && u.vectors_ready) {
        api.info({
          message: `${u.filename} hybrid-ready`,
          description: 'Vector embeddings online — full hybrid search enabled.',
          icon: <ThunderboltOutlined style={{ color: '#52c41a' }} />,
          duration: 4,
        })
      }
      seenStatus.current[u.id] = {
        status: u.status,
        vectors_ready: !!u.vectors_ready,
      }
    }
  }, [uploads, api])

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

  /**
   * Bulk-confirm every upload currently in ``mapping_review``, applying its
   * own LLM-proposed mapping unchanged. Errors on individual files are
   * surfaced as a warning toast at the end, but don't stop the rest of the
   * batch — the user can still retry the failed ones manually.
   */
  const handleAcceptAll = async () => {
    const pending = uploads.filter((u) => u.status === 'mapping_review')
    if (pending.length === 0) return
    setBulkAccepting(true)
    let ok = 0
    const failed: string[] = []
    for (const u of pending) {
      const mapping = u.proposed_mapping?.mapping
      if (!mapping) {
        failed.push(u.filename)
        continue
      }
      try {
        await confirmMut.mutateAsync({
          fileId: u.id,
          mapping,
          options: u.proposed_mapping?.options,
          save_as_profile: false,
        })
        ok++
      } catch {
        failed.push(u.filename)
      }
    }
    setBulkAccepting(false)
    if (ok > 0) {
      api.success({
        message: `Accepted ${ok} review${ok === 1 ? '' : 's'}`,
        description: failed.length
          ? `${failed.length} failed: ${failed.slice(0, 3).join(', ')}${failed.length > 3 ? '…' : ''}`
          : 'Indexing started for all confirmed files.',
        duration: 5,
      })
    } else if (failed.length) {
      api.error({
        message: 'Bulk accept failed',
        description: failed.slice(0, 3).join(', ') + (failed.length > 3 ? '…' : ''),
      })
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
      width: 220,
      render: (status: UploadStatus, u: UploadedFile) => {
        const total      = u.record_count ?? 0
        const indexed    = u.indexed_count ?? 0
        const embedded   = u.embedded_count ?? 0
        const idxPercent = total > 0 ? Math.round((indexed / total) * 100) : 0
        const embedPct   = indexed > 0 ? Math.round((embedded / indexed) * 100) : 0

        // Quartile-style "step" the user can read at a glance regardless
        // of total magnitude. Falls out of the percent so it stays
        // consistent with the Progress bar; capped at 4/4 so it doesn't
        // jitter when total is unknown.
        const indexStep = total > 0
          ? `${Math.min(4, Math.ceil(indexed / Math.max(1, total) * 4))}/4`
          : null

        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <Space size={4}>
              <Tag color={STATUS_COLORS[status]} style={{ fontSize: 11 }}>
                {STATUS_LABELS[status]}
              </Tag>
              {/* Search-mode badge: BM25 (text-only) until vectors are
                  ready, then Hybrid (BM25 + dense). Only shown for
                  successfully-indexed files. */}
              {status === 'complete' && (
                u.vectors_ready ? (
                  <Tooltip title="Both BM25 and vector search active for this file">
                    <Tag color="success" style={{ fontSize: 10, marginRight: 0 }}>
                      <ThunderboltOutlined /> Hybrid
                    </Tag>
                  </Tooltip>
                ) : indexed > 0 ? (
                  <Tooltip title="Keyword search ready; vector embeddings still computing">
                    <Tag style={{ fontSize: 10, marginRight: 0 }}>BM25</Tag>
                  </Tooltip>
                ) : null
              )}
            </Space>

            {status === 'indexing' && (
              <>
                <Progress
                  percent={idxPercent}
                  size="small"
                  status="active"
                  strokeColor={token.colorPrimary}
                  // ``"3/4"`` reads at a glance without forcing the user
                  // to parse the bar. Fades to ``%`` when total is known
                  // exactly, since that's more informative.
                  format={() =>
                    total > 0
                      ? <span style={{ fontSize: 10 }}>{indexStep} · {idxPercent}%</span>
                      : <span style={{ fontSize: 10 }}>indexing</span>
                  }
                />
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {indexed.toLocaleString()}
                  {total > 0 ? ` / ${total.toLocaleString()}` : ''} docs
                </Text>
              </>
            )}

            {status === 'complete' && total > 0 && (
              <>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {indexed.toLocaleString()} / {total.toLocaleString()} indexed
                </Text>
                {!u.vectors_ready && indexed > 0 && (
                  <Tooltip title={`${embedded.toLocaleString()} of ${indexed.toLocaleString()} embedded`}>
                    <Progress
                      percent={embedPct}
                      size="small"
                      strokeColor={token.colorPrimary}
                      format={() => (
                        <span style={{ fontSize: 10 }}>
                          embedding {embedded.toLocaleString()}/{indexed.toLocaleString()}
                        </span>
                      )}
                    />
                  </Tooltip>
                )}
              </>
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
          {u.status === 'complete' && (u.indexed_count ?? 0) > 0 && (
            <Tooltip title={`View this file's ${u.indexed_count} indexed docs in Data Exploration`}>
              <Button
                size="small"
                icon={<SearchOutlined />}
                onClick={() => {
                  // Route to the investigation's Data tab with a query
                  // string that filters to this upload's docs. The Data
                  // Exploration table uses Lucene query_string so
                  // ``source_file:<id>`` exact-matches the keyword field.
                  // ``source_file`` is a UUID — use the .keyword subfield
                  // so the query_string parser does an exact term match
                  // rather than tokenising the UUID into chunks.
                  const params = new URLSearchParams({
                    tab: 'data',
                    q: `source_file.keyword:${u.id}`,
                  })
                  navigate(`/investigations/${investigationId}?${params.toString()}`)
                }}
              >
                {u.indexed_count}
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
        <Space size={8}>
          <Text strong style={{ fontSize: 13 }}>
            {uploads.length} upload{uploads.length !== 1 ? 's' : ''}
          </Text>
          {(() => {
            const pendingReviews = uploads.filter((u) => u.status === 'mapping_review').length
            return pendingReviews > 0 ? (
              <Tag color="warning" style={{ fontSize: 11 }}>
                {pendingReviews} awaiting review
              </Tag>
            ) : null
          })()}
        </Space>
        <Space>
          {uploads.some((u) => u.status === 'mapping_review') && (
            <Tooltip title="Confirm every pending review with its proposed mapping">
              <Button
                size="small"
                type="primary"
                icon={<CheckCircleOutlined />}
                loading={bulkAccepting}
                onClick={handleAcceptAll}
              >
                Accept all (
                {uploads.filter((u) => u.status === 'mapping_review').length}
                )
              </Button>
            </Tooltip>
          )}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => refetch()}
          >
            Refresh
          </Button>
        </Space>
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
