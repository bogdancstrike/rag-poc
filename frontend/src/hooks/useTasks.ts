import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchTasks, fetchTask, restartTask, deleteTask, fetchTaskAnalytics, type TaskFilters, type TaskCategory } from '@/api/tasks'

const TASKS_KEY = 'tasks'

/** Unified filterable task list with 10 s auto-refresh. */
export function useTasks(filters: TaskFilters = {}) {
  return useQuery({
    queryKey: [TASKS_KEY, filters],
    queryFn: () => fetchTasks(filters),
    staleTime: 1_000,
    refetchInterval: 2_000,
  })
}

/** Single task detail — polls every 3 s while pending/processing. */
export function useTask(taskId: string | undefined) {
  return useQuery({
    queryKey: [TASKS_KEY, 'detail', taskId],
    queryFn: () => fetchTask(taskId!),
    enabled: !!taskId,
    staleTime: 2_000,
    refetchInterval: (query) => {
      const s = (query.state.data as any)?.status
      return s === 'pending' || s === 'processing' ? 3_000 : false
    },
  })
}

export function useRestartTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      category,
      datasource,
      task,
    }: {
      category: TaskCategory
      datasource: string
      task: string
    }) => restartTask(category, datasource, task),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [TASKS_KEY] })
    },
  })
}

export function useTaskAnalytics(datasource?: string, category?: string) {
  return useQuery({
    queryKey: ['tasks', 'analytics', datasource, category],
    queryFn: () => fetchTaskAnalytics(datasource, category),
    staleTime: 10_000,
    refetchInterval: 10_000,
  })
}

export function useDeleteTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      category,
      datasource,
      task,
    }: {
      category: TaskCategory
      datasource: string
      task: string
    }) => deleteTask(category, datasource, task),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [TASKS_KEY] })
    },
  })
}
