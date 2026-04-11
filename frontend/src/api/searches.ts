import { apiClient } from './client'
import type { SavedSearch, SavedSearchFilters } from '@/types'

export const fetchSearches = async (): Promise<SavedSearch[]> => {
  const { data } = await apiClient.get<{ searches: SavedSearch[]; total: number }>('/v1/searches')
  return data.searches
}

export const createSearch = async (payload: {
  name: string
  description?: string
  query: string
  filters?: SavedSearchFilters
}): Promise<SavedSearch> => {
  const { data } = await apiClient.post<SavedSearch>('/v1/searches', payload)
  return data
}

export const updateSearch = async (
  id: string,
  payload: {
    name?: string
    description?: string
    query?: string
    filters?: SavedSearchFilters
  },
): Promise<SavedSearch> => {
  const { data } = await apiClient.put<SavedSearch>(`/v1/searches/${id}`, payload)
  return data
}

export const deleteSearch = async (id: string): Promise<void> => {
  await apiClient.delete(`/v1/searches/${id}`)
}
