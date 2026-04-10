import { apiClient } from './client'

// ── Types ──────────────────────────────────────────────────────────────────

export type TaskStatus   = 'pending' | 'processing' | 'complete' | 'error'
export type TaskCategory = 'insight' | 'enrichment'

export interface Task {
  id:           string        // "insight__{ds}__{type}" or "enrichment__{ds}__{doc_id}"
  category:     TaskCategory
  task_type:    string        // insight_type ("summary"|"ner"|"graph"|"stats") or "enrichment"
  datasource:   string
  doc_id:       string | null // only for enrichment tasks
  status:       TaskStatus
  retry_count:  number
  error:        string | null
  has_output:   boolean
  generated_at: string | null
  started_at:   string | null
  updated_at:   string
  sample_hash?: string | null
  payload?:     any           // only populated in GET /v1/tasks/:id
}

export interface TaskStats {
  total:       number
  pending:     number
  processing:  number
  complete:    number
  error:       number
  insights:    number
  enrichments: number
}

export interface TaskListResponse {
  tasks: Task[]
  total: number
  page:  number
  size:  number
  stats: TaskStats
}

export interface TaskFilters {
  status?:        TaskStatus | ''
  category?:      TaskCategory | ''
  datasource?:    string
  task_type?:     string
  sort?:          string          // e.g. "updated_at:desc"
  page?:          number
  size?:          number
  created_after?: string
  created_before?: string
}

// ── API functions ───────────────────────────────────────────────────────────

export const fetchTasks = async (filters: TaskFilters = {}): Promise<TaskListResponse> => {
  const params: Record<string, any> = {}
  if (filters.status)         params.status         = filters.status
  if (filters.category)       params.category       = filters.category
  if (filters.datasource)     params.datasource     = filters.datasource
  if (filters.task_type)      params.task_type      = filters.task_type
  if (filters.sort)           params.sort           = filters.sort
  if (filters.page)           params.page           = filters.page
  if (filters.size)           params.size           = filters.size
  if (filters.created_after)  params.created_after  = filters.created_after
  if (filters.created_before) params.created_before = filters.created_before

  const { data } = await apiClient.get<TaskListResponse>('/v1/tasks', { params })
  return data
}

export const fetchTask = async (taskId: string): Promise<Task> => {
  const { data } = await apiClient.get<Task>(`/v1/tasks/${encodeURIComponent(taskId)}`)
  return data
}

export const restartTask = async (
  task_category: TaskCategory,
  datasource: string,
  task: string,
): Promise<void> => {
  await apiClient.post('/v1/dashboard/tasks/restart', { task_category, datasource, task })
}

export const deleteTask = async (
  task_category: TaskCategory,
  datasource: string,
  task: string,
): Promise<void> => {
  await apiClient.delete('/v1/dashboard/tasks', {
    params: { task_category, datasource, task },
  })
}

// Keep legacy dashboard overview for the summary stats card row
export const fetchDashboardTasks = async () => {
  const { data } = await apiClient.get('/v1/dashboard/tasks')
  return data
}

// ── Analytics ───────────────────────────────────────────────────────────────

export interface TimingRow {
  category:     string
  task_type:    string
  avg_queue_ms: number | null
  avg_exec_ms:  number | null
  avg_total_ms: number | null
  sample_count: number
}

export interface TaskAnalytics {
  timing:      TimingRow[]
  throughput:  Record<string, number>   // "5m" | "1h" | "12h" | "1d" | "7d" → count
  status_dist: Record<string, number>
  type_dist:   Record<string, number>
  time_series: { ts: number; count: number }[]
  total_tasks: number
}

export const fetchTaskAnalytics = async (
  datasource?: string,
  category?: string,
): Promise<TaskAnalytics> => {
  const params: Record<string, string> = {}
  if (datasource) params.datasource = datasource
  if (category)   params.category   = category
  const { data } = await apiClient.get<TaskAnalytics>('/v1/tasks/analytics', { params })
  return data
}
