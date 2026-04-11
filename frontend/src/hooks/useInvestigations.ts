import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchInvestigations,
  createInvestigation,
  fetchInvestigation,
  deleteInvestigation,
} from '@/api/investigations'
import type { Investigation } from '@/types'

export function useInvestigations() {
  const query = useQuery({
    queryKey: ['investigations'],
    queryFn: fetchInvestigations,
    staleTime: 10_000,
    refetchInterval: (query) => {
      const data = query.state.data as Investigation[] | undefined
      if (data?.some((inv) => inv.status === 'creating')) return 3000
      return false
    },
  })
  return query
}

export function useInvestigation(id: string) {
  return useQuery({
    queryKey: ['investigation', id],
    queryFn: () => fetchInvestigation(id),
    enabled: !!id,
    staleTime: 5_000,
    refetchInterval: (query) => {
      const data = query.state.data as Investigation | undefined
      if (data?.status === 'creating') return 3000
      return false
    },
  })
}

export function useCreateInvestigation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { name: string; description?: string; search_ids: string[] }) =>
      createInvestigation(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['investigations'] })
    },
  })
}

export function useDeleteInvestigation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteInvestigation(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['investigations'] })
    },
  })
}
