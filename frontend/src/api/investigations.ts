import { apiClient } from './client'
import type { Investigation } from '@/types'

export const fetchInvestigations = async (): Promise<Investigation[]> => {
  const { data } = await apiClient.get<{ investigations: Investigation[]; total: number }>(
    '/v1/investigations',
  )
  return data.investigations
}

export const createInvestigation = async (payload: {
  name: string
  description?: string
  search_ids: string[]
}): Promise<Investigation> => {
  const { data } = await apiClient.post<Investigation>('/v1/investigations', payload)
  return data
}

export const fetchInvestigation = async (id: string): Promise<Investigation> => {
  const { data } = await apiClient.get<Investigation>(`/v1/investigations/${id}`)
  return data
}

export const deleteInvestigation = async (id: string): Promise<void> => {
  await apiClient.delete(`/v1/investigations/${id}`)
}
