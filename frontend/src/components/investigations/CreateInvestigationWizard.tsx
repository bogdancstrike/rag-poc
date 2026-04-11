import { useState } from 'react'
import {
  Modal, Steps, Form, Input, Select, Button, Space, Typography, Table, Tag,
  Alert, message,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import type { SavedSearch } from '@/types'
import { useSavedSearches } from '@/hooks/useSavedSearches'
import { useCreateInvestigation } from '@/hooks/useInvestigations'

const { Text, Paragraph } = Typography
const { TextArea } = Input

interface Props {
  open: boolean
  onClose: () => void
  onCreated: (id: string) => void
}

interface WizardState {
  name: string
  description: string
  selectedSearchIds: string[]
}

const INITIAL: WizardState = { name: '', description: '', selectedSearchIds: [] }

export function CreateInvestigationWizard({ open, onClose, onCreated }: Props) {
  const [step, setStep]               = useState(0)
  const [form]                        = Form.useForm()
  const [state, setState]             = useState<WizardState>(INITIAL)
  const { data: searches = [], isLoading } = useSavedSearches()
  const createInv                     = useCreateInvestigation()

  const reset = () => {
    setStep(0)
    setState(INITIAL)
    form.resetFields()
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleNext = async () => {
    if (step === 0) {
      try {
        const vals = await form.validateFields()
        setState((s) => ({ ...s, name: vals.name, description: vals.description || '' }))
        setStep(1)
      } catch {}
    } else if (step === 1) {
      setStep(2)
    }
  }

  const handleBack = () => setStep((s) => Math.max(0, s - 1))

  const handleCreate = () => {
    createInv.mutate(
      {
        name:        state.name,
        description: state.description || undefined,
        search_ids:  state.selectedSearchIds,
      },
      {
        onSuccess: (inv) => {
          message.success(`Investigation "${state.name}" is being created`)
          reset()
          onClose()
          onCreated(inv.id)
        },
        onError: (err: any) => {
          message.error(err?.message || 'Failed to create investigation')
        },
      },
    )
  }

  const searchColumns = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, s: SavedSearch) => (
        <div>
          <Text strong style={{ fontSize: 13 }}>{name}</Text>
          {s.description && (
            <Paragraph type="secondary" style={{ fontSize: 11, margin: 0 }} ellipsis={{ rows: 1 }}>
              {s.description}
            </Paragraph>
          )}
        </div>
      ),
    },
    {
      title: 'Query',
      dataIndex: 'query',
      key: 'query',
      ellipsis: true,
      render: (q: string) => q ? <Tag style={{ fontSize: 11 }}>{q.slice(0, 60)}</Tag> : <Text type="secondary">—</Text>,
    },
    {
      title: 'Filters',
      key: 'filters',
      width: 120,
      render: (_: any, s: SavedSearch) => {
        const count = Object.values(s.filters).filter(
          (v) => v !== undefined && v !== null && (Array.isArray(v) ? v.length > 0 : true),
        ).length
        return count > 0 ? <Tag>{count} filter{count !== 1 ? 's' : ''}</Tag> : '—'
      },
    },
  ]

  const selectedSearches = searches.filter((s) => state.selectedSearchIds.includes(s.id))

  const stepContent = [
    // Step 0 — Name
    <Form form={form} layout="vertical" size="small" key="step0">
      <Form.Item
        label="Investigation Name"
        name="name"
        rules={[{ required: true, message: 'Name is required' }]}
      >
        <Input placeholder="e.g. 2026 Election Disinfo Campaign" autoFocus />
      </Form.Item>
      <Form.Item label="Description (optional)" name="description">
        <TextArea
          placeholder="What is this investigation about?"
          rows={3}
          showCount
          maxLength={500}
        />
      </Form.Item>
    </Form>,

    // Step 1 — Select saved searches
    <div key="step1">
      <Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
        Select the saved searches that will populate this investigation's document index.
        You can select multiple searches — documents matching any of them will be included.
      </Text>
      {searches.length === 0 && !isLoading ? (
        <Alert
          type="info"
          showIcon
          message="No saved searches yet"
          description="Go to Data Exploration → Advanced Search and save some queries first."
        />
      ) : (
        <Table
          size="small"
          loading={isLoading}
          dataSource={searches}
          columns={searchColumns}
          rowKey="id"
          pagination={false}
          scroll={{ y: 300 }}
          rowSelection={{
            selectedRowKeys: state.selectedSearchIds,
            onChange: (keys) => setState((s) => ({ ...s, selectedSearchIds: keys as string[] })),
          }}
        />
      )}
    </div>,

    // Step 2 — Review
    <div key="step2">
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>Investigation Name</Text>
          <Text strong style={{ display: 'block', fontSize: 15 }}>{state.name}</Text>
          {state.description && (
            <Text type="secondary" style={{ fontSize: 12 }}>{state.description}</Text>
          )}
        </div>

        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            Selected Searches ({selectedSearches.length})
          </Text>
          {selectedSearches.length === 0 ? (
            <Text type="warning" style={{ display: 'block', fontSize: 12 }}>
              No searches selected — investigation will start with an empty index.
            </Text>
          ) : (
            selectedSearches.map((s) => (
              <div key={s.id} style={{ marginTop: 6 }}>
                <Tag>{s.name}</Tag>
                {s.query && (
                  <Text type="secondary" style={{ fontSize: 11 }}> — {s.query.slice(0, 50)}</Text>
                )}
              </div>
            ))
          )}
        </div>

        <Alert
          type="info"
          showIcon
          message="Index creation runs in the background"
          description="After clicking Create, a background task will build the investigation index. You can monitor progress in Task Monitor or on the investigation card."
        />
      </Space>
    </div>,
  ]

  return (
    <Modal
      title={
        <Space>
          <PlusOutlined />
          <Text strong>Create Investigation</Text>
        </Space>
      }
      open={open}
      onCancel={handleClose}
      width={640}
      footer={
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Button onClick={handleClose}>Cancel</Button>
          <Space>
            {step > 0 && <Button onClick={handleBack}>Back</Button>}
            {step < 2 ? (
              <Button type="primary" onClick={handleNext}>
                Next
              </Button>
            ) : (
              <Button
                type="primary"
                icon={<SearchOutlined />}
                loading={createInv.isPending}
                onClick={handleCreate}
              >
                Create Investigation
              </Button>
            )}
          </Space>
        </Space>
      }
    >
      <Steps
        current={step}
        size="small"
        style={{ marginBottom: 24 }}
        items={[
          { title: 'Name' },
          { title: 'Select Searches' },
          { title: 'Review' },
        ]}
      />
      {stepContent[step]}
    </Modal>
  )
}
