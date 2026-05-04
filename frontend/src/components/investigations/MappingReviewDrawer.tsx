import { useEffect, useState } from 'react'
import {
  Drawer, Form, Select, Input, Button, Space, Typography, Alert, Tag,
  Switch, Table, theme, Divider,
} from 'antd'
import { CheckOutlined } from '@ant-design/icons'
import { useConfirmMapping } from '@/hooks/useUploads'
import type { ProposedMapping, UploadedFile, UploadMapping } from '@/types'

const { Text, Paragraph } = Typography

interface Props {
  upload: UploadedFile | null
  open: boolean
  onClose: () => void
  investigationId: string
}

/**
 * Drawer that shows the LLM/heuristic-proposed mapping and lets the user
 * accept or edit it before indexing begins. Also offers to save the result
 * as a parser profile so structurally identical re-uploads skip this step.
 *
 * Two distinct UIs depending on the handler family:
 *   - Tabular  (csv/jsonl/xlsx)  → column→field selects + sample preview
 *   - Text-like (txt/pdf/docx/html) → mode dropdown + optional regex
 */
export function MappingReviewDrawer({ upload, open, onClose, investigationId }: Props) {
  const { token } = theme.useToken()
  const confirmMutation = useConfirmMapping(investigationId)

  const proposed = (upload?.proposed_mapping ?? null) as ProposedMapping | null

  const [mapping, setMapping] = useState<UploadMapping>({})
  const [saveProfile, setSaveProfile] = useState(false)
  const [profileName, setProfileName] = useState('')

  // Reset form whenever a new upload is opened.
  useEffect(() => {
    if (proposed) {
      setMapping({ ...proposed.mapping })
      setSaveProfile(false)
      setProfileName('')
    }
  }, [upload?.id])

  if (!upload || !proposed) return null

  const isTextLike = ['text', 'pdf', 'docx', 'html'].includes(upload.handler_name)
  const modeKey: keyof UploadMapping = upload.handler_name === 'text' ? 'mode' : 'chunking'
  const currentMode = (mapping[modeKey] as string | undefined) || (
    upload.handler_name === 'pdf' ? 'page'
      : upload.handler_name === 'html' ? 'article'
        : upload.handler_name === 'docx' ? 'paragraph'
          : 'paragraph'
  )
  const modeOptions = upload.handler_name === 'pdf'
    ? [
        { label: 'Full-text (one record for the entire file)', value: 'full_text' },
        { label: 'Page (one record per page)', value: 'page' },
        { label: 'Paragraph (split pages on blank lines)', value: 'paragraph' },
      ]
    : upload.handler_name === 'docx'
      ? [
          { label: 'Full-text (one record for the entire file)', value: 'full_text' },
          { label: 'Paragraph (one record per paragraph)', value: 'paragraph' },
          { label: 'Section (group paragraphs under headings)', value: 'section' },
        ]
      : upload.handler_name === 'html'
        ? [
            { label: 'Full-text (one record for the whole page body)', value: 'full_text' },
            { label: 'Article (prefer article/main content)', value: 'article' },
            { label: 'Paragraph (one record per paragraph/list/header)', value: 'paragraph' },
          ]
        : [
            { label: 'Full-text (one record for the entire file)', value: 'full_text' },
            { label: 'Regex (one record per matching line)', value: 'regex' },
            { label: 'Paragraph (split on blank lines)', value: 'paragraph' },
            { label: 'Line (one record per non-empty line)', value: 'line' },
          ]

  const handleConfirm = async () => {
    await confirmMutation.mutateAsync({
      fileId: upload.id,
      mapping,
      save_as_profile: saveProfile,
      name: saveProfile ? (profileName || null as any) : undefined,
    })
    onClose()
  }

  // Table preview of first samples
  const sampleColumns = proposed.columns.map((c) => ({
    title: <span style={{ fontSize: 11 }}>{c}</span>,
    dataIndex: c,
    key: c,
    ellipsis: true,
    render: (v: unknown) => (
      <span style={{ fontSize: 11 }}>
        {v === null || v === undefined
          ? <Text type="secondary">null</Text>
          : String(v).slice(0, 80)}
      </span>
    ),
  }))

  // Field selectors common to all tabular handlers.
  const fieldSelector = (
    label: string,
    fieldKey: keyof UploadMapping,
    required = false,
  ) => (
    <Form.Item label={label} required={required} style={{ marginBottom: 12 }}>
      <Select
        size="small"
        allowClear={!required}
        placeholder="(none)"
        value={mapping[fieldKey] ?? null}
        onChange={(v) => setMapping((m) => ({ ...m, [fieldKey]: v ?? null }))}
        options={proposed.columns.map((c) => ({ label: c, value: c }))}
      />
    </Form.Item>
  )

  // Cancel must always work; Confirm requires a text-column for tabular
  // handlers (CSV/JSONL/XLSX) or a parse mode for the text handler.
  const canConfirm = isTextLike
    ? !!(mapping[modeKey])
    : !!(mapping.text)

  return (
    <Drawer
      title={
        <Space>
          <Text strong>Review mapping for </Text>
          <Tag>{upload.filename}</Tag>
        </Space>
      }
      open={open}
      onClose={onClose}
      width={620}
      // Force a higher zIndex than the parent tab content's stacking context
      // so the footer buttons aren't visually clipped/blocked.
      zIndex={1100}
      // Render the Drawer's portal at document.body explicitly. Default
      // behaviour, but stating it makes future-proofing against parent
      // overflow/transform changes safer.
      getContainer={() => document.body}
      // Plain div (not Space) for the footer — Space can collapse the
      // height to 0 in some antd versions, hiding/blocking the buttons.
      footer={
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          gap: 8,
          padding: '0 4px',
        }}>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="primary"
            icon={<CheckOutlined />}
            loading={confirmMutation.isPending}
            disabled={!canConfirm}
            onClick={handleConfirm}
          >
            Confirm and index
          </Button>
        </div>
      }
    >
      {/* Source banner */}
      <Alert
        type={proposed.source === 'llm' ? 'info' : 'warning'}
        showIcon
        style={{ marginBottom: 16 }}
        title={proposed.source === 'llm'
          ? `LLM-proposed mapping (confidence ${(proposed.confidence * 100).toFixed(0)}%)`
          : 'Heuristic mapping (LLM unavailable — please verify)'}
        description={proposed.rationale}
      />

      {!isTextLike && (
        <>
          <Text type="secondary" style={{ fontSize: 11 }}>COLUMN MAPPING</Text>
          <div style={{ marginTop: 8, marginBottom: 16 }}>
            <Form layout="vertical" size="small">
              {fieldSelector('Primary text (required)', 'text', true)}
              {fieldSelector('Title', 'title')}
              {fieldSelector('Created at', 'created_at')}
              {fieldSelector('Author', 'author')}
              {fieldSelector('URL', 'url')}
            </Form>
          </div>
        </>
      )}

      {isTextLike && (
        <>
          <Text type="secondary" style={{ fontSize: 11 }}>PARSE MODE</Text>
          <Form layout="vertical" size="small" style={{ marginTop: 8, marginBottom: 16 }}>
            <Form.Item label="Mode">
              <Select
                size="small"
                value={currentMode}
                onChange={(v) => setMapping((m) => ({ ...m, [modeKey]: v as any }))}
                options={modeOptions}
              />
            </Form.Item>
            {upload.handler_name === 'text' && currentMode === 'regex' && (
              <Form.Item label="Regex pattern (named groups: text, created_at, author)">
                <Input.TextArea
                  rows={3}
                  size="small"
                  value={mapping.regex || ''}
                  onChange={(e) => setMapping((m) => ({ ...m, regex: e.target.value }))}
                  style={{ fontFamily: 'monospace', fontSize: 11 }}
                />
              </Form.Item>
            )}
            <Form.Item label="Minimum characters per record">
              <Input
                size="small"
                type="number"
                value={mapping.min_chars ?? 0}
                onChange={(e) => setMapping((m) => ({
                  ...m, min_chars: parseInt(e.target.value, 10) || 0,
                }))}
              />
            </Form.Item>
          </Form>
        </>
      )}

      {/* Sample preview */}
      {!isTextLike && proposed.samples.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <Text type="secondary" style={{ fontSize: 11 }}>
            SAMPLE ROWS ({proposed.samples.length})
          </Text>
          <div style={{ marginTop: 8, overflowX: 'auto' }}>
            <Table
              size="small"
              dataSource={proposed.samples.map((s, i) => ({ key: i, ...s }))}
              columns={sampleColumns}
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
          </div>

          {/* Data Exploration preview — show how the sample rows above
              will render in the existing DataTable after the mapping is
              applied. Mirrors the backend normalizer's synthetic-title
              logic so what the user sees here is what they'll get. */}
          <div style={{ marginTop: 14 }}>
            <Text type="secondary" style={{ fontSize: 11 }}>
              PREVIEW IN DATA EXPLORATION
            </Text>
            <Table
              size="small"
              style={{ marginTop: 6 }}
              pagination={false}
              dataSource={proposed.samples.slice(0, 3).map((s, i) => {
                const get = (k?: string | null) =>
                  k ? (s as Record<string, unknown>)[k] : undefined
                const text = String(get(mapping.text) ?? '').trim()
                const realTitle = get(mapping.title)
                  ? String(get(mapping.title)).trim()
                  : ''
                const synthesised = !realTitle && text
                  ? text.split('\n')[0].slice(0, 80) + (text.length > 80 ? '…' : '')
                  : ''
                const title = realTitle || synthesised || '(synthetic)'
                return {
                  key: i,
                  date: String(get(mapping.created_at) ?? '—'),
                  title,
                  title_synthetic: !realTitle,
                  content: text || '—',
                }
              })}
              columns={[
                {
                  title: <span style={{ fontSize: 11 }}>Date</span>,
                  dataIndex: 'date',
                  key: 'date',
                  width: 120,
                  render: (v: string) => (
                    <span style={{ fontSize: 11, fontFamily: 'monospace' }}>
                      {v.length > 19 ? v.slice(0, 19) : v}
                    </span>
                  ),
                },
                {
                  title: <span style={{ fontSize: 11 }}>Title</span>,
                  dataIndex: 'title',
                  key: 'title',
                  render: (v: string, row: { title_synthetic: boolean }) => (
                    <span style={{
                      fontSize: 11,
                      fontStyle: row.title_synthetic ? 'italic' : 'normal',
                      color: row.title_synthetic ? token.colorTextSecondary : undefined,
                    }}>
                      {v}
                    </span>
                  ),
                },
                {
                  title: <span style={{ fontSize: 11 }}>Content</span>,
                  dataIndex: 'content',
                  key: 'content',
                  ellipsis: true,
                  render: (v: string) => (
                    <span style={{ fontSize: 11 }}>
                      {v.length > 120 ? v.slice(0, 120) + '…' : v}
                    </span>
                  ),
                },
              ]}
            />
            <Text type="secondary" style={{ fontSize: 10, display: 'block', marginTop: 4 }}>
              Italic titles are auto-generated from the first line of content
              when no title column was selected.
            </Text>
          </div>
        </>
      )}

      {/* Save-as-profile */}
      <Divider style={{ margin: '16px 0' }} />
      <div
        style={{
          border: `1px solid ${saveProfile ? token.colorPrimary : token.colorBorderSecondary}`,
          borderRadius: token.borderRadius,
          padding: '10px 14px',
        }}
      >
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space direction="vertical" size={2}>
            <Text strong style={{ fontSize: 13 }}>Save as parser profile</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              The next file with the same structure will reuse this mapping
              automatically — no LLM call, no review step.
            </Text>
          </Space>
          <Switch checked={saveProfile} onChange={setSaveProfile} />
        </Space>
        {saveProfile && (
          <Input
            size="small"
            placeholder="Profile name (optional, e.g. 'leak-export-format')"
            style={{ marginTop: 10 }}
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
          />
        )}
      </div>

      {confirmMutation.isError && (
        <Paragraph type="danger" style={{ marginTop: 12, fontSize: 12 }}>
          {(confirmMutation.error as Error)?.message || 'Confirmation failed.'}
        </Paragraph>
      )}
    </Drawer>
  )
}
