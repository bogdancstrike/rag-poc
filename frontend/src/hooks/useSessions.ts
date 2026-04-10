import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listSessions, createSession, deleteSession, renameSession, getMessages } from '@/api/sessions'
import { useSessionStore } from '@/stores/sessionStore'

export function useSessions(datasource?: string) {
  return useQuery({
    queryKey: ['sessions', datasource],
    queryFn:  () => listSessions(datasource),
    staleTime: 30_000,
  })
}

export function useCreateSession() {
  const qc = useQueryClient()
  const setActive = useSessionStore((s) => s.setActiveSession)
  return useMutation({
    mutationFn: ({ title, datasource }: { title?: string; datasource?: string }) =>
      createSession(title, datasource),
    onSuccess: (session) => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
      setActive(session.id)
    },
  })
}

export function useDeleteSession() {
  const qc = useQueryClient()
  const { activeSessionId, setActiveSession } = useSessionStore()
  return useMutation({
    mutationFn: (id: string) => deleteSession(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
      if (activeSessionId === id) setActiveSession(null)
    },
  })
}

export function useRenameSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameSession(id, title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
}

export function useMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ['messages', sessionId],
    queryFn:  () => getMessages(sessionId!),
    enabled:  !!sessionId,
    staleTime: 0,
  })
}
