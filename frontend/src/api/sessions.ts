import { apiClient } from './client'
import type { Session, Message } from '@/types'

export const listSessions = async (datasource?: string): Promise<Session[]> => {
  const { data } = await apiClient.get<{ sessions: Session[] }>('/v1/sessions', {
    params: datasource ? { datasource } : {},
  })
  return data.sessions
}

export const createSession = async (title?: string, datasource = 'default'): Promise<Session> => {
  const { data } = await apiClient.post<Session>('/v1/sessions', { title, datasource })
  return data
}

export const deleteSession = async (id: string): Promise<void> => {
  await apiClient.delete(`/v1/sessions/${id}`)
}

export const renameSession = async (id: string, title: string): Promise<Session> => {
  const { data } = await apiClient.patch<Session>(`/v1/sessions/${id}`, { title })
  return data
}

export const getMessages = async (sessionId: string): Promise<Message[]> => {
  const { data } = await apiClient.get<{ messages: Message[] }>(`/v1/sessions/${sessionId}/messages`)
  return data.messages
}
