import { apiClient } from './client'
import type { Insights } from '@/types'

export const fetchInsights = async (datasource = 'default'): Promise<Insights> => {
  const { data } = await apiClient.get<Insights>('/v1/insights', { params: { datasource } })
  return data
}

export const refreshInsights = async (datasource = 'default'): Promise<Insights> => {
  const { data } = await apiClient.post<Insights>('/v1/insights/refresh', { datasource })
  return data
}
