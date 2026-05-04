import { apiClient } from './client'
import type {
  AcceptedFormats, ParserProfile, UploadedFile, UploadMapping,
} from '@/types'

/**
 * List all uploads attached to one investigation, newest first.
 */
export const fetchUploads = async (investigationId: string): Promise<UploadedFile[]> => {
  const { data } = await apiClient.get<{ uploads: UploadedFile[] }>(
    `/v1/investigations/${investigationId}/uploads`,
  )
  return data.uploads
}

/**
 * Multipart upload of a single file. Multi-GB-safe — axios streams the
 * FormData body without buffering and the server's storage layer hashes
 * + writes in chunks. Reports progress via the optional onProgress callback.
 *
 * Returns the freshly-created UploadedFile row (status="pending"); the
 * actual parsing happens server-side in a background task.
 */
export const uploadFile = async (
  investigationId: string,
  file: File,
  onProgress?: (loaded: number, total: number) => void,
): Promise<UploadedFile> => {
  const fd = new FormData()
  fd.append('file', file, file.name)

  const { data } = await apiClient.post<UploadedFile>(
    `/v1/investigations/${investigationId}/uploads`,
    fd,
    {
      // Browsers set the multipart boundary themselves; clearing this header
      // lets the boundary slot in correctly.
      headers: { 'Content-Type': 'multipart/form-data' },
      // Server is streaming-write — give it generous time for big files.
      timeout: 0,
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(e.loaded, e.total)
      },
    },
  )
  return data
}

export const fetchUpload = async (fileId: string): Promise<UploadedFile> => {
  const { data } = await apiClient.get<UploadedFile>(`/v1/uploads/${fileId}`)
  return data
}

export const confirmMapping = async (
  fileId: string,
  payload: {
    mapping: UploadMapping
    options?: Record<string, unknown>
    save_as_profile?: boolean
    name?: string
  },
): Promise<UploadedFile> => {
  const { data } = await apiClient.post<UploadedFile>(
    `/v1/uploads/${fileId}/confirm`, payload,
  )
  return data
}

export const deleteUpload = async (fileId: string, purgeEs = false): Promise<void> => {
  await apiClient.delete(`/v1/uploads/${fileId}`, {
    params: purgeEs ? { purge_es: 'true' } : {},
  })
}

export const downloadUploadUrl = (fileId: string): string =>
  `${apiClient.defaults.baseURL}/v1/uploads/${fileId}/download`

export const fetchAcceptedFormats = async (): Promise<AcceptedFormats> => {
  const { data } = await apiClient.get<AcceptedFormats>('/v1/uploads/formats')
  return data
}

export const fetchParserProfiles = async (
  handlerName?: string,
): Promise<ParserProfile[]> => {
  const { data } = await apiClient.get<{ profiles: ParserProfile[] }>(
    '/v1/parser-profiles',
    { params: handlerName ? { handler: handlerName } : {} },
  )
  return data.profiles
}

export const deleteParserProfile = async (id: string): Promise<void> => {
  await apiClient.delete(`/v1/parser-profiles/${id}`)
}
