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

export interface LLMLiveStats {
  available:                   boolean
  backend?:                    string
  reason?:                     string
  requests_running?:           number | null
  requests_waiting?:           number | null
  kv_cache_usage_perc?:        number | null    // 0..1
  kv_cache_tokens_used?:       number | null
  kv_cache_capacity_tokens?:   number | null
  kv_cache_dtype?:             string | null
  kv_cache_block_size?:        number | null
  kv_cache_gpu_blocks?:        number | null
  kv_total_bytes?:             number | null
  kv_used_bytes?:              number | null
  kv_bytes_per_token?:         number | null
  vram_per_request_bytes?:     number | null
  vram_per_request_basis?:     'actual' | 'theoretical' | null
  gpu_memory_utilization?:     number | null    // 0..1
  prompt_tokens_total?:        number | null
  generation_tokens_total?:    number | null
  prefix_cache_hit_rate?:      number | null    // 0..1
  preemptions_total?:          number | null
}

export const fetchLLMLive = async (): Promise<LLMLiveStats> => {
  const { data } = await apiClient.get<LLMLiveStats>('/v1/llm/live')
  return data
}

export interface EmbeddingsGpuProcess {
  pid: number
  name: string
  used_mib: number
  role: 'embeddings' | 'llm' | 'other'
}

export interface EmbeddingsGpuStats {
  available: boolean
  reason?: string
  total_mib?: number
  used_mib?: number
  embeddings_mib?: number
  llm_mib?: number
  other_mib?: number
  processes?: EmbeddingsGpuProcess[]
}

export interface EmbeddingsLiveStats {
  available: boolean
  backend?: string
  reason?: string
  base_url?: string
  model?: string
  model_dtype?: string
  pooling?: string
  max_input_length?: number | null
  max_batch_tokens?: number | null
  max_client_batch_size?: number | null
  max_concurrent_requests?: number | null
  tokenization_workers?: number | null
  version?: string | null
  request_count?: number | null
  success_count?: number | null
  embed_count?: number | null
  embedded_records_total?: number | null
  queue_size?: number | null
  avg_request_ms?: number | null
  avg_inference_ms?: number | null
  avg_queue_ms?: number | null
  avg_tokenization_ms?: number | null
  avg_input_tokens?: number | null
  avg_batch_tokens?: number | null
  avg_batch_size?: number | null
  gpu?: EmbeddingsGpuStats
}

export const fetchEmbeddingsLive = async (): Promise<EmbeddingsLiveStats> => {
  const { data } = await apiClient.get<EmbeddingsLiveStats>('/v1/embeddings/live')
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
