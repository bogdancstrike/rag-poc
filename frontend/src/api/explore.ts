import { apiClient } from './client'

export const fetchIndices = async (): Promise<string[]> => {
  const { data } = await apiClient.get<{ indices: string[] }>('/v1/datasource/indices')
  return data.indices
}

export interface Document {
  id: string
  title?: string
  text?: string
  source?: string
  created_at?: string
  [key: string]: any
}

export interface DocumentFilters {
  sentiment?: string
  status?: string
  labels?: string[]
  classification?: string
  date_from?: string
  date_to?: string
  index_patterns?: string[]
  enriched?: boolean
  advanced_query?: Record<string, any>
}

export interface DocumentField {
  name: string
  label: string
  type: 'string' | 'number' | 'date' | 'boolean'
  es_type: string
  searchable: boolean
}

export const fetchDocuments = async (
  datasource: string,
  offset = 0,
  limit = 50,
  query = '',
  filters: DocumentFilters = {},
): Promise<{ documents: Document[]; total: number }> => {
  const params: Record<string, any> = { offset, limit, query }
  // Only send datasource param when a specific index is targeted
  if (datasource) params.datasource = datasource
  if (filters.sentiment)          params.filter_sentiment      = filters.sentiment
  if (filters.status)             params.filter_status         = filters.status
  if (filters.labels?.length)     params.filter_labels         = filters.labels.join(',')
  if (filters.classification)     params.filter_classification = filters.classification
  if (filters.date_from)          params.filter_date_from      = filters.date_from
  if (filters.date_to)            params.filter_date_to        = filters.date_to
  if (filters.index_patterns?.length) {
    params.index_pattern = filters.index_patterns.join(',')
  }
  if (filters.enriched)            params.filter_enriched       = 'true'
  if (filters.advanced_query)       params.advanced_query        = JSON.stringify(filters.advanced_query)
  const { data } = await apiClient.get<{ documents: Document[]; total: number }>('/v1/documents', { params })
  return data
}

export const fetchDocumentFields = async (
  datasource = '',
  indexPatterns: string[] = [],
): Promise<DocumentField[]> => {
  const params: Record<string, any> = {}
  if (datasource) params.datasource = datasource
  else if (indexPatterns.length) params.index_pattern = indexPatterns.join(',')
  const { data } = await apiClient.get<{ fields: DocumentField[] }>('/v1/documents/fields', { params })
  return data.fields
}

export interface DocumentEnrichmentPayload {
  summary?: string
  sentiment?: string
  classification?: string
  entities?: { name: string; type: string }[]
}

export interface DocumentEnrichment {
  doc_id: string
  datasource: string
  status: 'pending' | 'processing' | 'complete' | 'error'
  payload?: DocumentEnrichmentPayload
  error?: string
  generated_at?: string
}

/** Fetch the set of doc IDs that have complete enrichment for a datasource. */
export const fetchEnrichedDocIds = async (datasource: string): Promise<string[]> => {
  const { data } = await apiClient.get<{ doc_ids: string[] }>('/v1/documents/enriched', {
    params: { datasource },
  })
  return data.doc_ids
}

/** Fetch a single document by its Elasticsearch _id. */
export const fetchDocumentById = async (
  datasource: string,
  docId: string,
): Promise<Document | null> => {
  const { data } = await apiClient.get<{ documents: Document[]; total: number }>('/v1/documents', {
    params: { datasource, query: `_id:${docId}`, limit: 1, offset: 0 },
  })
  return data.documents[0] ?? null
}

/** Start or retrieve enrichment for a document (async — may return 202 Accepted). */
export const enrichDocument = async (
  datasource: string,
  doc_id: string,
  text: string,
  force = false,
): Promise<DocumentEnrichment> => {
  const { data } = await apiClient.post<DocumentEnrichment>('/v1/documents/enrich', {
    datasource,
    doc_id,
    text,
    force,
  })
  return data
}

export type DocReviewStatus = 'in_progress' | 'done'

/** Fetch all analyst review statuses for a datasource. Returns a map of doc_id → status. */
export const fetchDocumentStatuses = async (
  datasource: string,
): Promise<Record<string, DocReviewStatus>> => {
  const { data } = await apiClient.get<{ statuses: Record<string, DocReviewStatus> }>(
    '/v1/documents/status',
    { params: { datasource } },
  )
  return data.statuses
}

/** Set or clear the analyst review status for a document. Pass null to clear. */
export const setDocumentStatus = async (
  datasource: string,
  doc_id: string,
  status: DocReviewStatus | null,
): Promise<void> => {
  await apiClient.post('/v1/documents/status', { datasource, doc_id, status })
}

export type EnrichmentField =
  | 'sentiment'
  | 'classification'
  | 'entities'
  | 'summary'
  | 'graph'
  | 'timeline'
  | 'locations'
  | 'iocs'
  | 'translation'

/** Reload a single enrichment field. */
export const reloadEnrichmentField = async (
  datasource: string,
  doc_id: string,
  text: string,
  field: EnrichmentField,
): Promise<DocumentEnrichment> => {
  const { data } = await apiClient.post<DocumentEnrichment>('/v1/documents/enrich/field', {
    datasource,
    doc_id,
    text,
    field,
  })
  return data
}

/** Fetch all labels for a datasource. Returns a map of doc_id → string[]. */
export const fetchDocumentLabels = async (
  datasource: string,
): Promise<Record<string, string[]>> => {
  const { data } = await apiClient.get<{ labels: Record<string, string[]> }>(
    '/v1/documents/labels',
    { params: { datasource } },
  )
  return data.labels
}

/** Set labels for a document. Pass [] to clear all labels. */
export const setDocumentLabels = async (
  datasource: string,
  doc_id: string,
  labels: string[],
): Promise<void> => {
  await apiClient.post('/v1/documents/labels', { datasource, doc_id, labels })
}
