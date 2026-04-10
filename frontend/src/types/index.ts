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
  id: string
  score: number
  text: string
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
