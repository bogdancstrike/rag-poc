import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchUploads, uploadFile, fetchUpload, confirmMapping,
  deleteUpload, fetchAcceptedFormats, fetchParserProfiles,
  deleteParserProfile,
} from '@/api/uploads'
import type { UploadedFile, UploadMapping } from '@/types'

/**
 * Live list of uploads for one investigation. Polls every 2.5s while any
 * upload is in a non-terminal state so the UI status badges advance without
 * requiring SSE.
 */
export function useUploads(investigationId: string) {
  return useQuery({
    queryKey: ['uploads', investigationId],
    queryFn: () => fetchUploads(investigationId),
    enabled: !!investigationId,
    staleTime: 2_000,
    refetchInterval: (query) => {
      const data = query.state.data as UploadedFile[] | undefined
      const live = data?.some((u) =>
        ['pending', 'parsing', 'mapping_review', 'indexing'].includes(u.status),
      )
      return live ? 2_500 : false
    },
  })
}

export function useUpload(fileId: string) {
  return useQuery({
    queryKey: ['upload', fileId],
    queryFn: () => fetchUpload(fileId),
    enabled: !!fileId,
    staleTime: 2_000,
  })
}

export function useUploadFile(investigationId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => uploadFile(investigationId, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['uploads', investigationId] })
    },
  })
}

export function useConfirmMapping(investigationId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: {
      fileId: string
      mapping: UploadMapping
      options?: Record<string, unknown>
      save_as_profile?: boolean
      name?: string
    }) =>
      confirmMapping(payload.fileId, {
        mapping: payload.mapping,
        options: payload.options,
        save_as_profile: payload.save_as_profile,
        name: payload.name,
      }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['upload', vars.fileId] })
      if (investigationId) {
        qc.invalidateQueries({ queryKey: ['uploads', investigationId] })
      }
    },
  })
}

export function useDeleteUpload(investigationId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { fileId: string; purgeEs?: boolean }) =>
      deleteUpload(payload.fileId, payload.purgeEs ?? false),
    onSuccess: () => {
      if (investigationId) {
        qc.invalidateQueries({ queryKey: ['uploads', investigationId] })
      }
    },
  })
}

export function useAcceptedFormats() {
  return useQuery({
    queryKey: ['uploads', 'formats'],
    queryFn: fetchAcceptedFormats,
    // Static data — only changes when handlers are added in the codebase.
    staleTime: 60 * 60 * 1000,
  })
}

export function useParserProfiles(handlerName?: string) {
  return useQuery({
    queryKey: ['parser-profiles', handlerName ?? 'all'],
    queryFn: () => fetchParserProfiles(handlerName),
    staleTime: 30_000,
  })
}

export function useDeleteParserProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => deleteParserProfile(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['parser-profiles'] })
    },
  })
}
