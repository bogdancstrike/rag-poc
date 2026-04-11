import { useState, useCallback } from 'react'
import {
  Button, Space, Typography, Tag, Tooltip, message, theme,
} from 'antd'
import {
  FilterOutlined, BookOutlined, ClearOutlined,
} from '@ant-design/icons'
import { DataTable } from './DataTable'
import { AdvancedSearchPanel, type AdvancedSearchState } from './AdvancedSearchPanel'
import { SavedSearchesDrawer } from './SavedSearchesDrawer'
import { useIndices } from '@/hooks/useExplore'
import { useCreateSearch } from '@/hooks/useSavedSearches'
import type { SavedSearch, SavedSearchFilters } from '@/types'
import type { DocumentFilters } from '@/api/explore'

const { Text } = Typography

const EMPTY_SEARCH: AdvancedSearchState = { query: '' }

export function DataExplorationPage() {
  const { token } = theme.useToken()
  const { data: indices = [] } = useIndices()
  const createSearch = useCreateSearch()

  const [searchState, setSearchState] = useState<AdvancedSearchState>(EMPTY_SEARCH)
  const [appliedState, setAppliedState] = useState<AdvancedSearchState>(EMPTY_SEARCH)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showSaved, setShowSaved] = useState(false)

  const handleApply = useCallback(() => {
    setAppliedState(searchState)
  }, [searchState])

  const handleSaveSearch = useCallback(
    (name: string, description: string) => {
      createSearch.mutate(
        {
          name,
          description,
          query: searchState.query,
          filters: {
            sentiment:      searchState.sentiment,
            status:         searchState.status,
            labels:         searchState.labels,
            classification: searchState.classification,
            index_patterns: searchState.index_patterns,
            date_from:      searchState.date_from,
            date_to:        searchState.date_to,
          } satisfies SavedSearchFilters,
        },
        {
          onSuccess: () => message.success('Search saved successfully'),
          onError:   () => message.error('Failed to save search'),
        },
      )
    },
    [searchState, createSearch],
  )

  const handleApplySearch = (s: SavedSearch) => {
    const next: AdvancedSearchState = {
      query:          s.query,
      sentiment:      s.filters.sentiment,
      status:         s.filters.status,
      labels:         s.filters.labels,
      classification: s.filters.classification,
      index_patterns: s.filters.index_patterns,
      date_from:      s.filters.date_from,
      date_to:        s.filters.date_to,
    }
    setSearchState(next)
    setAppliedState(next)
  }

  const handleClearAll = () => {
    setSearchState(EMPTY_SEARCH)
    setAppliedState(EMPTY_SEARCH)
  }

  // Build active filter tags for the action bar
  const activeTags: { label: string; onRemove: () => void }[] = []
  if (appliedState.query) {
    activeTags.push({
      label: `"${appliedState.query.slice(0, 30)}${appliedState.query.length > 30 ? '…' : ''}"`,
      onRemove: () => setAppliedState((p) => ({ ...p, query: '' })),
    })
  }
  if (appliedState.sentiment) {
    activeTags.push({
      label: `sentiment: ${appliedState.sentiment}`,
      onRemove: () => setAppliedState((p) => ({ ...p, sentiment: undefined })),
    })
  }
  if (appliedState.status) {
    activeTags.push({
      label: `status: ${appliedState.status}`,
      onRemove: () => setAppliedState((p) => ({ ...p, status: undefined })),
    })
  }
  if (appliedState.classification) {
    activeTags.push({
      label: `class: ${appliedState.classification}`,
      onRemove: () => setAppliedState((p) => ({ ...p, classification: undefined })),
    })
  }
  if (appliedState.date_from || appliedState.date_to) {
    activeTags.push({
      label: `date: ${appliedState.date_from?.slice(0, 10) ?? '…'} – ${appliedState.date_to?.slice(0, 10) ?? '…'}`,
      onRemove: () => setAppliedState((p) => ({ ...p, date_from: undefined, date_to: undefined })),
    })
  }

  // Build DocumentFilters for DataTable
  const dtFilters: DocumentFilters = {
    sentiment:      appliedState.sentiment,
    status:         appliedState.status,
    labels:         appliedState.labels,
    classification: appliedState.classification,
    date_from:      appliedState.date_from,
    date_to:        appliedState.date_to,
    index_patterns: appliedState.index_patterns,
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Action bar */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: `1px solid ${token.colorBorderSecondary}`,
          background: token.colorBgContainer,
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 8,
          flexShrink: 0,
        }}
      >
        <Text strong style={{ fontSize: 14 }}>Data Exploration</Text>
        <Text type="secondary" style={{ fontSize: 12 }}>— all indices</Text>

        <div style={{ flex: 1 }} />

        {/* Active filter tags */}
        <Space wrap size={4}>
          {activeTags.map(({ label, onRemove }, i) => (
            <Tag
              key={i}
              closable
              onClose={onRemove}
              style={{ fontSize: 11 }}
            >
              {label}
            </Tag>
          ))}
          {activeTags.length > 0 && (
            <Tooltip title="Clear all filters">
              <Button
                size="small"
                type="text"
                icon={<ClearOutlined />}
                onClick={handleClearAll}
              />
            </Tooltip>
          )}
        </Space>

        <Button
          icon={<BookOutlined />}
          size="small"
          onClick={() => setShowSaved(true)}
        >
          Saved Searches
        </Button>
        <Button
          icon={<FilterOutlined />}
          size="small"
          type={activeTags.length > 0 ? 'primary' : 'default'}
          onClick={() => setShowAdvanced(true)}
        >
          Advanced Search
          {activeTags.length > 0 && ` (${activeTags.length})`}
        </Button>
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        <DataTable
          datasource=""
          controlledQuery={appliedState.query}
          controlledFilters={dtFilters}
          showSourceIndex
        />
      </div>

      {/* Drawers */}
      <AdvancedSearchPanel
        open={showAdvanced}
        onClose={() => setShowAdvanced(false)}
        indices={indices}
        value={searchState}
        onChange={setSearchState}
        onApply={handleApply}
        onSave={handleSaveSearch}
      />

      <SavedSearchesDrawer
        open={showSaved}
        onClose={() => setShowSaved(false)}
        onApply={handleApplySearch}
      />
    </div>
  )
}
