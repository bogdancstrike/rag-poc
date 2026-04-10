import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchInsights, refreshInsights, deleteInsights } from '@/api/insights'

export function useInsights(datasource = 'default') {
  return useQuery({
    queryKey:  ['insights', datasource],
    queryFn:   () => fetchInsights(datasource),
    staleTime: 30_000, 
    refetchInterval: (query) => {
      // Poll every 5s if any task is not complete
      const data = query.state.data as any
      if (!data?.tasks) return false
      
      const isProcessing = Object.values(data.tasks).some(
        (t: any) => t.status === 'processing' || t.status === 'pending'
      )
      return isProcessing ? 5000 : false
    },
    retry: 1,
  })
}

export function useRefreshInsights(datasource = 'default') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => refreshInsights(datasource),
    onSuccess:  (data) => qc.setQueryData(['insights', datasource], data),
  })
}

export function useDeleteInsights(datasource = 'default') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => deleteInsights(datasource),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['insights', datasource] }),
  })
}
