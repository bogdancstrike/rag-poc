// ── Domain types ────────────────────────────────────────────────────────────

export interface Session {
  id: string
  title: string | null
  datasource: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  sources: Source[] | null
  created_at: string
}

export interface Source {
  id:          string
  score:       number
  text:        string
  title?:      string   // doc title or source field
  datasource?: string   // index name — used for "Go To Document" link
}

// ── Insights types ────────────────────────────────────────────────────────────

export interface HotTopic {
  topic: string
  count_estimate: number
  summary: string
  sentiment: 'positive' | 'negative' | 'neutral' | 'mixed'
}

export interface Narrative {
  title: string
  description: string
  evidence_docs: string[]
}

export interface Trend {
  label: string
  direction: 'rising' | 'falling' | 'stable'
  change_pct: number
  time_period: string
}

export interface Entity {
  name: string
  type: 'person' | 'org' | 'location' | 'event' | 'other'
  frequency: number
  related: string[]
}

export interface Anomaly {
  description: string
  docs: string[]
}

export interface InsightsMeta {
  cached?: boolean
  generated_at?: string
  age_seconds?: number
  doc_count?: number
  datasource: string
  reason?: string
  is_processing?: boolean
  refresh_triggered?: boolean
  sample_hash?: string
}

export interface Insights {
  tasks?: Record<string, any>
  hot_topics?: HotTopic[]
  narratives?: Narrative[]
  trends?: Trend[]
  entities?: Entity[]
  anomalies?: Anomaly[]
  _meta: InsightsMeta
}

// ── SSE event types ───────────────────────────────────────────────────────────

export type SseEvent =
  | { type: 'sources';  sources: Source[]; session_id: string }
  | { type: 'delta';    content: string }
  | { type: 'done';     message_id: string; session_id: string }
  | { type: 'error';    content: string }

// ── Saved Search types ────────────────────────────────────────────────────────

export interface SavedSearchFilters {
  sentiment?:       string
  status?:          string
  labels?:          string[]
  classification?:  string
  index_patterns?:  string[]
  date_from?:       string
  date_to?:         string
}

export interface SavedSearch {
  id:          string
  name:        string
  description: string | null
  query:       string
  filters:     SavedSearchFilters
  created_at:  string
  updated_at:  string
}

// ── Investigation types ───────────────────────────────────────────────────────

export type InvestigationStatus = 'creating' | 'ready' | 'error'

export interface Investigation {
  id:          string
  name:        string
  description: string | null
  index_name:  string
  status:      InvestigationStatus
  error_msg:   string | null
  doc_count:   number | null
  search_ids:  string[]
  created_at:  string
  updated_at:  string
}
