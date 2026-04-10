import { useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchInsights,
  refreshInsights,
  deleteInsights,
  refreshTask,
  openInsightsStream,
} from '@/api/insights'

/**
 * useInsights — fetches the initial insights snapshot then subscribes to SSE
 * for real-time task updates.  Falls back to polling (5 s) if SSE fails.
 */
export function useInsights(datasource = 'default') {
  const qc = useQueryClient()

  const query = useQuery({
    queryKey: ['insights', datasource],
    queryFn: () => fetchInsights(datasource),
    staleTime: 30_000,
    // Fallback polling while SSE is not available or tasks are pending
    refetchInterval: (q) => {
      const data = q.state.data as any
      if (!data?.tasks) return 5_000 // poll until we have data
      const isProcessing = Object.values(data.tasks).some(
        (t: any) => t.status === 'processing' || t.status === 'pending',
      )
      return isProcessing ? 5_000 : false
    },
    retry: 2,
  })

  // SSE subscription — updates React Query cache in real time
  const streamRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!datasource) return

    // Open SSE stream
    const controller = openInsightsStream(datasource, {
      onState: (tasks) => {
        qc.setQueryData(['insights', datasource], (old: any) => ({
          ...(old || {}),
          tasks,
          _meta: { ...(old?._meta || {}), datasource },
        }))
      },
      onTaskUpdate: (insightType, task) => {
        qc.setQueryData(['insights', datasource], (old: any) => {
          if (!old) return old
          return {
            ...old,
            tasks: { ...(old.tasks || {}), [insightType]: task },
          }
        })
      },
      onError: () => {
        // SSE failed — polling fallback already active via refetchInterval
      },
    })

    streamRef.current = controller

    return () => {
      controller.abort()
      streamRef.current = null
    }
  }, [datasource, qc])

  return query
}

export function useRefreshInsights(datasource = 'default') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => refreshInsights(datasource),
    onSuccess: (data) => qc.setQueryData(['insights', datasource], data),
  })
}

export function useDeleteInsights(datasource = 'default') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => deleteInsights(datasource),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['insights', datasource] }),
  })
}

export function useRefreshTask(datasource: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (task: string) => refreshTask(datasource, task),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['insights', datasource] }),
  })
}
