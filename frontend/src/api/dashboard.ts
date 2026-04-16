import { apiClient } from './client'

export interface InsightTask {
  datasource: string
  insight_type: string
  status: 'pending' | 'processing' | 'complete' | 'error'
  payload?: any
  error?: string
  generated_at?: string
  sample_hash?: string
}

export interface EnrichmentTask {
  doc_id: string
  datasource: string
  status: 'pending' | 'processing' | 'complete' | 'error'
  payload?: any
  error?: string
  generated_at?: string
}

export interface TaskOverview {
  summary: {
    total_insights: number
    total_enrichments: number
    insights_pending: number
    enrichments_pending: number
    insights_error: number
    enrichments_error: number
  }
  insights: InsightTask[]
  enrichments: EnrichmentTask[]
}

export interface LLMStats {
  model: string
  model_path?: string
  model_type?: string
  architectures?: string[]
  context_length?: number
  max_model_len?: number
  dtype?: string
  quantization?: string
  kv_cache_dtype?: string
  mem_fraction_static?: number
  max_running_requests?: number
  tp_size?: number
  is_generation?: boolean
  error?: string
}

export const fetchDashboardTasks = async (): Promise<TaskOverview> => {
  const { data } = await apiClient.get<TaskOverview>('/v1/dashboard/tasks')
  return data
}

export const fetchLLMStats = async (): Promise<LLMStats> => {
  const { data } = await apiClient.get<LLMStats>('/v1/llm/stats')
  return data
}

/** Restart an insight or enrichment task. */
export const restartTask = async (
  task_category: 'insight' | 'enrichment',
  datasource: string,
  task: string,
): Promise<void> => {
  await apiClient.post('/v1/dashboard/tasks/restart', { task_category, datasource, task })
}

/** Clear (delete) a task record from the database. */
export const clearTask = async (
  task_category: 'insight' | 'enrichment',
  datasource: string,
  task: string,
): Promise<void> => {
  await apiClient.delete('/v1/dashboard/tasks', {
    params: { task_category, datasource, task },
  })
}
