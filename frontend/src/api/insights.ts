import { apiClient, API_BASE } from './client'
import type { Insights } from '@/types'

export const fetchInsights = async (datasource = 'default'): Promise<Insights> => {
  const { data } = await apiClient.get<Insights>('/v1/insights', { params: { datasource } })
  return data
}

export const refreshInsights = async (datasource = 'default'): Promise<Insights> => {
  const { data } = await apiClient.post<Insights>('/v1/insights/refresh', { datasource })
  return data
}

export const deleteInsights = async (datasource = 'default'): Promise<void> => {
  await apiClient.delete('/v1/insights', { params: { datasource } })
}

export const refreshTask = async (datasource: string, task: string): Promise<void> => {
  await apiClient.post('/v1/insights/task/refresh', { datasource, task })
}

/**
 * openInsightsStream — opens an SSE connection to receive real-time task updates.
 *
 * Returns an AbortController; call `.abort()` to close the connection.
 * Callbacks:
 *   onState(tasks)     — initial snapshot of all tasks
 *   onTaskUpdate(type, task) — individual task status change
 *   onError(err)       — connection error
 */
export function openInsightsStream(
  datasource: string,
  callbacks: {
    onState: (tasks: Record<string, any>) => void
    onTaskUpdate: (insightType: string, task: any) => void
    onError?: (err: Error) => void
  },
): AbortController {
  const controller = new AbortController()
  const url = `${API_BASE}/v1/insights/stream?datasource=${encodeURIComponent(datasource)}`

  const connect = () => {
    const es = new EventSource(url)

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        if (event.type === 'state') {
          callbacks.onState(event.tasks || {})
        } else if (event.type === 'task_update') {
          callbacks.onTaskUpdate(event.insight_type, event.task)
        }
      } catch {
        // Ignore parse errors (e.g., heartbeat comments)
      }
    }

    es.onerror = () => {
      es.close()
      callbacks.onError?.(new Error('SSE connection lost'))
    }

    // Allow external abort to close the EventSource
    controller.signal.addEventListener('abort', () => es.close(), { once: true })
  }

  connect()
  return controller
}
