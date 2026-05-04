import { useQuery, useQueries, useMutation, useQueryClient, useQueryClient as _useQC } from '@tanstack/react-query'
import { useEffect, useState, useRef, useMemo } from 'react'
import { API_BASE } from '@/api/client'
import { fetchIndices, fetchDocuments, fetchDocumentById, fetchEnrichedDocIds, enrichDocument, reloadEnrichmentField, fetchDocumentStatuses, setDocumentStatus, fetchDocumentLabels, setDocumentLabels, fetchDocumentFields, DocReviewStatus, EnrichmentField, DocumentFilters } from '@/api/explore'

export function useIndices() {
  return useQuery({
    queryKey: ['indices'],
    queryFn: fetchIndices,
    staleTime: 60_000,
  })
}

export function useDocuments(
  datasource: string,
  page: number,
  pageSize: number,
  query: string,
  filters: DocumentFilters = {},
) {
  const offset = (page - 1) * pageSize
  return useQuery({
    queryKey: ['documents', datasource, offset, pageSize, query, filters],
    queryFn: () => fetchDocuments(datasource, offset, pageSize, query, filters),
    // Allow empty datasource for global explore (all-index search)
    enabled: true,
    staleTime: 10_000,
  })
}

export function useDocumentFields(datasource = '', indexPatterns: string[] = []) {
  return useQuery({
    queryKey: ['documentFields', datasource, indexPatterns.join(',')],
    queryFn: () => fetchDocumentFields(datasource, indexPatterns),
    staleTime: 60_000,
  })
}

/** Fetch the set of enriched doc IDs — used to mark rows with a star in DataTable. */
export function useEnrichedDocIds(datasource: string) {
  return useQuery({
    queryKey: ['enrichedDocIds', datasource],
    queryFn: () => fetchEnrichedDocIds(datasource),
    enabled: !!datasource,
    staleTime: 30_000,
    refetchInterval: 30_000,
  })
}

/**
 * Fetch enriched doc IDs for multiple datasources in parallel and merge into
 * a single Set. Used by DataTable in global-explore mode (datasource="") where
 * documents span multiple indices — each doc carries `_source_index`.
 *
 * Uses the same per-datasource cache keys as `useEnrichedDocIds`, so cache
 * invalidations from SSE enrichment completion propagate automatically.
 */
export function useMultiEnrichedDocIds(datasources: string[]): Set<string> {
  const results = useQueries({
    queries: datasources.map((ds) => ({
      queryKey: ['enrichedDocIds', ds] as const,
      queryFn: () => fetchEnrichedDocIds(ds),
      staleTime: 30_000,
      refetchInterval: 30_000,
    })),
  })

  return useMemo(() => {
    const combined = new Set<string>()
    for (const r of results) {
      for (const id of r.data ?? []) combined.add(id)
    }
    return combined
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results.map((r) => r.dataUpdatedAt).join(',')])
}

/** Fetch a single document by ID — used when navigating directly to /explore/:index/:docId. */
export function useDocumentById(datasource: string, docId: string | undefined) {
  return useQuery({
    queryKey: ['document', datasource, docId],
    queryFn: () => fetchDocumentById(datasource, docId!),
    enabled: !!datasource && !!docId,
    staleTime: 30_000,
    retry: 1,
  })
}

/**
 * useEnrichDocument — fetches (and polls) enrichment for a single document.
 *
 * The backend returns 202 Accepted when enrichment is in-progress, so we poll
 * every 3 s while status is pending/processing.
 */
export function useEnrichDocument(datasource: string, docId: string, text: string, enabled: boolean) {
  return useQuery({
    queryKey: ['enrich', datasource, docId],
    queryFn: () => enrichDocument(datasource, docId, text),
    enabled: enabled && !!datasource && !!docId && !!text,
    staleTime: Infinity, // Enriched data doesn't expire automatically
    refetchInterval: (query) => {
      const data = query.state.data as any
      if (data?.status === 'processing' || data?.status === 'pending') {
        return 3000
      }
      return false
    },
    retry: 1,
  })
}

export type EnrichStreamStatus = 'idle' | 'streaming' | 'complete' | 'error'

export interface EnrichStreamResult {
  /** Accumulated enrichment payload — updates after each step */
  payload: Record<string, any> | null
  status: EnrichStreamStatus
  error: string | null
  /** Call to force a re-stream (re-enrichment) */
  restream: () => void
}

/**
 * useEnrichDocumentStream — streams enrichment results via SSE POST.
 *
 * The backend runs each enrichment step (LLM → IOC → geocoding → translation)
 * inline in a generator, yielding partial payloads as each step completes.
 * The hook accumulates these partials so the UI can show fields as they arrive.
 */
export function useEnrichDocumentStream(
  datasource: string,
  docId: string,
  text: string,
  enabled: boolean,
): EnrichStreamResult {
  const qc = useQueryClient()
  const [payload, setPayload]   = useState<Record<string, any> | null>(null)
  const [status, setStatus]     = useState<EnrichStreamStatus>('idle')
  const [error, setError]       = useState<string | null>(null)
  const [forceKey, setForceKey] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!enabled || !datasource || !docId || !text) return

    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setStatus('streaming')
    setError(null)

    const force = forceKey > 0

    ;(async () => {
      try {
        const resp = await fetch(`${API_BASE}/v1/documents/enrich/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ datasource, doc_id: docId, text, force }),
          signal: ctrl.signal,
        })
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

        const reader = resp.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const evt = JSON.parse(line.slice(6))
              if (evt.type === 'cached' || evt.type === 'partial') {
                setPayload(evt.payload ?? null)
                if (evt.type === 'cached') {
                  setStatus('complete')
                }
              } else if (evt.type === 'complete') {
                setPayload(evt.payload ?? null)
                setStatus('complete')
                // Update enriched-doc-ids cache so star appears immediately
                qc.invalidateQueries({ queryKey: ['enrichedDocIds', datasource] })
              } else if (evt.type === 'error') {
                setError(evt.error ?? 'Unknown error')
                setStatus('error')
              }
            } catch {}
          }
        }
      } catch (e: any) {
        if (e.name !== 'AbortError') {
          setError(e.message)
          setStatus('error')
        }
      }
    })()

    return () => ctrl.abort()
  }, [datasource, docId, enabled, forceKey])

  const restream = () => {
    setPayload(null)
    setStatus('idle')
    setError(null)
    setForceKey((k) => k + 1)
  }

  return { payload, status, error, restream }
}

/**
 * useReloadEnrichmentField — trigger per-field enrichment reload.
 * Invalidates the enrichment query on success so the panel refreshes.
 */
export function useReloadEnrichmentField(datasource: string, docId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ text, field }: { text: string; field: EnrichmentField }) =>
      reloadEnrichmentField(datasource, docId, text, field),
    onSuccess: () => {
      // Invalidate so refetch picks up the new partial result
      qc.invalidateQueries({ queryKey: ['enrich', datasource, docId] })
    },
  })
}

/** Fetch all analyst review statuses for a datasource. */
export function useDocumentStatuses(datasource: string) {
  return useQuery({
    queryKey: ['docStatuses', datasource],
    queryFn: () => fetchDocumentStatuses(datasource),
    enabled: datasource !== undefined, // Allow empty string for global explore
    staleTime: 30_000,
  })
}

/** Set or clear the analyst review status for a single document. */
export function useSetDocumentStatus(datasource: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ docId, status, datasource: dsOverride }: { docId: string; status: DocReviewStatus | null; datasource?: string }) =>
      setDocumentStatus(dsOverride || datasource, docId, status),
    onSuccess: (_data, vars) => {
      const ds = vars.datasource || datasource
      qc.invalidateQueries({ queryKey: ['docStatuses', ds] })
      if (ds) qc.invalidateQueries({ queryKey: ['docStatuses', ''] })
    },
  })
}

/** Fetch all analyst labels for a datasource. */
export function useDocumentLabels(datasource: string) {
  return useQuery({
    queryKey: ['docLabels', datasource],
    queryFn: () => fetchDocumentLabels(datasource),
    enabled: datasource !== undefined,
    staleTime: 30_000,
  })
}

/** Set or clear analyst labels for a single document. */
export function useSetDocumentLabels(datasource: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ docId, labels, datasource: dsOverride }: { docId: string; labels: string[]; datasource?: string }) =>
      setDocumentLabels(dsOverride || datasource, docId, labels),
    onSuccess: (_data, vars) => {
      const ds = vars.datasource || datasource
      qc.invalidateQueries({ queryKey: ['docLabels', ds] })
      if (ds) qc.invalidateQueries({ queryKey: ['docLabels', ''] })
    },
  })
}

/** Force a full enrichment re-run. */
export function useForceReenrich(datasource: string, docId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => enrichDocument(datasource, docId, text, true),
    onSuccess: (data) => {
      qc.setQueryData(['enrich', datasource, docId], data)
    },
  })
}
