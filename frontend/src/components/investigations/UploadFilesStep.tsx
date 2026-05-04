import { Upload, Typography, Space, Alert, Tag, theme, Tooltip, Button } from 'antd'
import { InboxOutlined, FileTextOutlined, DeleteOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload/interface'
import { useAcceptedFormats } from '@/hooks/useUploads'

const { Text, Paragraph } = Typography
const { Dragger } = Upload

interface Props {
  /** Files staged in the wizard. Held in browser state until createInvestigation
   *  resolves; then uploaded one-by-one to the new investigation. */
  files: File[]
  onChange: (files: File[]) => void
}

/**
 * Wizard step: drag-and-drop multi-file picker.
 *
 * No actual upload happens here — files are kept in component state and
 * shipped to the server immediately after the investigation is created. We
 * surface the accepted-formats list so the user knows what'll be picked up.
 */
export function UploadFilesStep({ files, onChange }: Props) {
  const { token } = theme.useToken()
  const { data: formats } = useAcceptedFormats()

  // Mirror our File[] state into antd's UploadFile[] for the visual list.
  const uploadList: UploadFile[] = files.map((f, idx) => ({
    uid: `${idx}-${f.name}-${f.size}`,
    name: f.name,
    size: f.size,
    status: 'done',
    type: f.type,
    originFileObj: f as any,
  }))

  const fmtSize = (b: number): string => {
    if (b < 1024) return `${b} B`
    if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`
    if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
    return `${(b / 1024 ** 3).toFixed(2)} GB`
  }

  const removeFile = (uid: string) => {
    const idx = uploadList.findIndex((f) => f.uid === uid)
    if (idx >= 0) onChange(files.filter((_, i) => i !== idx))
  }

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="Upload files into this investigation (optional)"
        description={
          <Text type="secondary" style={{ fontSize: 12 }}>
            Drag-drop or browse to add CSV, JSON, XLSX, TXT, MD or LOG files.
            They'll be parsed into the investigation index after it's created.
            Tabular files with auto-detected columns will pause for your
            confirmation on the Uploads tab.
          </Text>
        }
      />

      <Dragger
        multiple
        accept={formats?.accept_string}
        beforeUpload={(file, fileList) => {
          // Append the whole drop, deduped by name+size+lastModified.
          const key = (f: File) => `${f.name}|${f.size}|${(f as any).lastModified ?? 0}`
          const seen = new Set(files.map(key))
          const next = [...files]
          for (const f of fileList) {
            if (!seen.has(key(f))) {
              next.push(f)
              seen.add(key(f))
            }
          }
          onChange(next)
          return Upload.LIST_IGNORE   // prevent antd's default upload behavior
        }}
        showUploadList={false}
        style={{ padding: '8px 0' }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text" style={{ fontSize: 14 }}>
          Click or drag files to this area
        </p>
        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
          Multiple files supported. Multi-GB files are streamed (no in-memory load).
        </p>
      </Dragger>

      {/* Accepted formats hint */}
      {formats && (
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>ACCEPTED FORMATS</Text>
          <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {formats.handlers.map((h) => (
              <Tooltip key={h.name} title={h.extensions.join(', ')}>
                <Tag style={{ fontSize: 11, marginRight: 0 }}>
                  <span style={{ textTransform: 'uppercase' }}>{h.name}</span>
                  {' · '}
                  <span style={{ fontFamily: 'monospace' }}>{h.extensions.join(' ')}</span>
                </Tag>
              </Tooltip>
            ))}
          </div>
        </div>
      )}

      {/* Staged file list */}
      {uploadList.length > 0 && (
        <div
          style={{
            marginTop: 16,
            border: `1px solid ${token.colorBorderSecondary}`,
            borderRadius: token.borderRadius,
          }}
        >
          <div
            style={{
              padding: '8px 12px',
              borderBottom: `1px solid ${token.colorBorderSecondary}`,
              background: token.colorFillAlter,
            }}
          >
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Text strong style={{ fontSize: 12 }}>
                {uploadList.length} file{uploadList.length !== 1 ? 's' : ''} staged
              </Text>
              <Button size="small" type="link" onClick={() => onChange([])}>
                Clear all
              </Button>
            </Space>
          </div>
          {uploadList.map((f) => (
            <div
              key={f.uid}
              style={{
                padding: '6px 12px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                fontSize: 12,
                borderTop: f.uid === uploadList[0].uid ? 'none' : `1px solid ${token.colorBorderSecondary}`,
              }}
            >
              <FileTextOutlined style={{ color: token.colorTextTertiary }} />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {f.name}
              </span>
              <Tag style={{ fontSize: 10, marginRight: 0 }}>{fmtSize(f.size ?? 0)}</Tag>
              <Button
                size="small"
                type="text"
                icon={<DeleteOutlined />}
                onClick={() => removeFile(f.uid)}
              />
            </div>
          ))}
        </div>
      )}

      <Paragraph type="secondary" style={{ fontSize: 11, marginTop: 12, marginBottom: 0 }}>
        You can add more files later from the investigation's <b>Uploads</b> tab.
      </Paragraph>
    </div>
  )
}
