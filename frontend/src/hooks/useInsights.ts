import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchInsights, refreshInsights } from '@/api/insights'

export function useInsights(datasource = 'default') {
  return useQuery({
    queryKey:  ['insights', datasource],
    queryFn:   () => fetchInsights(datasource),
    staleTime: 5 * 60 * 1000,   // 5 min — server-side TTL is 30 min
    retry:     1,
  })
}

export function useRefreshInsights(datasource = 'default') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => refreshInsights(datasource),
    onSuccess:  (data) => qc.setQueryData(['insights', datasource], data),
  })
}
