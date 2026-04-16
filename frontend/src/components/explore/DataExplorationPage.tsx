import { useState, useCallback, useEffect } from 'react'
import {
  Button, Space, Typography, Tag, Tooltip, message, theme,
} from 'antd'
import {
  FilterOutlined, BookOutlined, ClearOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { DataTable } from './DataTable'
import { AdvancedSearchPanel, type AdvancedSearchState } from './AdvancedSearchPanel'
import { SavedSearchesDrawer } from './SavedSearchesDrawer'
import { useIndices } from '@/hooks/useExplore'
import { useCreateSearch } from '@/hooks/useSavedSearches'
import type { SavedSearch, SavedSearchFilters } from '@/types'
import type { DocumentFilters } from '@/api/explore'

const { Text } = Typography

const EMPTY_SEARCH: AdvancedSearchState = { query: '' }

/** Read AdvancedSearchState from URL search params */
function stateFromParams(p: URLSearchParams): AdvancedSearchState {
  return {
    query:          p.get('q')           || '',
    sentiment:      p.get('sentiment')   || undefined,
    status:         p.get('status')      || undefined,
    classification: p.get('class')       || undefined,
    labels:         p.get('labels')      ? p.get('labels')!.split(',')       : undefined,
    date_from:      p.get('from')        || undefined,
    date_to:        p.get('to')          || undefined,
    index_patterns: p.get('idx_patterns') ? p.get('idx_patterns')!.split(',') : undefined,
  }
}

export function DataExplorationPage() {
  const { token } = theme.useToken()
  const { data: indices = [] } = useIndices()
  const createSearch = useCreateSearch()
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialise from URL so refresh / shared links restore the same filters
  const [appliedState, setAppliedState] = useState<AdvancedSearchState>(() => stateFromParams(searchParams))
  const [searchState, setSearchState]   = useState<AdvancedSearchState>(() => stateFromParams(searchParams))
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showSaved, setShowSaved] = useState(false)

  // Sync applied filters to URL whenever they change
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      const set = (k: string, v: string | undefined) =>
        v ? next.set(k, v) : next.delete(k)

      // Remove all search-related params first then re-add non-empty ones
      ;['q', 'sentiment', 'status', 'class', 'labels', 'from', 'to', 'idx_patterns']
        .forEach((k) => next.delete(k))

      set('q',            appliedState.query || undefined)
      set('sentiment',    appliedState.sentiment)
      set('status',       appliedState.status)
      set('class',        appliedState.classification)
      set('labels',       appliedState.labels?.length ? appliedState.labels.join(',') : undefined)
      set('from',         appliedState.date_from)
      set('to',           appliedState.date_to)
      set('idx_patterns', appliedState.index_patterns?.length ? appliedState.index_patterns.join(',') : undefined)
      return next
    }, { replace: true })
  }, [appliedState])

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

      <div style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <DataTable
          datasource=""
          controlledQuery={appliedState.query}
          controlledFilters={dtFilters}
          showSourceIndex
          enableUrlSync
          yOffset={280}
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
