import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchSearches, createSearch, updateSearch, deleteSearch } from '@/api/searches'
import type { SavedSearch, SavedSearchFilters } from '@/types'

export function useSavedSearches() {
  return useQuery({
    queryKey: ['savedSearches'],
    queryFn: fetchSearches,
    staleTime: 30_000,
  })
}

export function useCreateSearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      name: string
      description?: string
      query: string
      filters?: SavedSearchFilters
    }) => createSearch(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['savedSearches'] })
    },
  })
}

export function useUpdateSearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string
      name?: string
      description?: string
      query?: string
      filters?: SavedSearchFilters
    }) => updateSearch(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['savedSearches'] })
    },
  })
}

export function useDeleteSearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteSearch(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['savedSearches'] })
    },
  })
}
